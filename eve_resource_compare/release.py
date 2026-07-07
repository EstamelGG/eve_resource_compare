from __future__ import annotations

import gzip
import json
import os
import re
from pathlib import Path

import requests

from .config import USER_AGENT

_VERSION_TAG = re.compile(r"^v(\d+)$")
_COMPARE_TAG = re.compile(r"^compare-(\d+)-(\d+)$")


class ReleaseError(Exception):
    pass


class GitHubReleases:
    def __init__(self, token: str, repo: str | None = None):
        self.token = token
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
        if not self.repo:
            raise ReleaseError("GITHUB_REPOSITORY not set")
        self.base = f"https://api.github.com/repos/{self.repo}"
        self.session = requests.Session()
        self.session.trust_env = True
        http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if http or https:
            self.session.proxies.update({
                "http": http or https,
                "https": https or http,
            })
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def list_releases(self) -> list[dict]:
        releases: list[dict] = []
        page = 1
        while True:
            resp = self.session.get(
                f"{self.base}/releases",
                params={"per_page": 100, "page": page},
                timeout=60,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            releases.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return releases

    def latest_snapshot_version(self) -> int | None:
        versions: list[int] = []
        for rel in self.list_releases():
            tag = rel.get("tag_name", "")
            m = _VERSION_TAG.match(tag)
            if m:
                versions.append(int(m.group(1)))
        return max(versions) if versions else None

    def compare_release_exists(self, old_version: int, new_version: int) -> bool:
        return self.release_exists(f"compare-{old_version}-{new_version}")

    def release_exists(self, tag: str) -> bool:
        resp = self.session.get(f"{self.base}/releases/tags/{tag}", timeout=30)
        return resp.status_code == 200

    def create_release(self, tag: str, title: str, body: str) -> dict:
        resp = self.session.post(
            f"{self.base}/releases",
            json={"tag_name": tag, "name": title, "body": body},
            timeout=60,
        )
        if resp.status_code == 422 and "already_exists" in resp.text:
            resp = self.session.get(f"{self.base}/releases/tags/{tag}", timeout=30)
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()

    def upload_asset(self, release_id: int, filepath: Path, content_type: str) -> None:
        name = filepath.name
        url = f"https://uploads.github.com/repos/{self.repo}/releases/{release_id}/assets"
        with filepath.open("rb") as f:
            resp = self.session.post(
                url,
                params={"name": name},
                data=f,
                headers={"Content-Type": content_type},
                timeout=300,
            )
        resp.raise_for_status()

    def publish_json(self, tag: str, title: str, body: str, filename: str, data: dict) -> None:
        rel = self.create_release(tag, title, body)
        tmp = Path(filename)
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            self.upload_asset(rel["id"], tmp, "application/json")
        finally:
            tmp.unlink(missing_ok=True)

    def publish_snapshot(
        self,
        version: int,
        meta: dict,
        app_index: dict[str, dict],
        res_index: dict[str, dict],
        type_deps: dict,
        workdir: Path,
    ) -> None:
        tag = f"v{version}"
        if self.release_exists(tag):
            print(f"Snapshot release {tag} already exists, skipping")
            return

        workdir.mkdir(parents=True, exist_ok=True)
        files = {
            "meta.json": meta,
            "app-index.jsonl": app_index,
            "res-index.jsonl": res_index,
            "type-deps.json": type_deps,
        }
        assets: list[Path] = []
        for name, payload in files.items():
            if name.endswith(".jsonl"):
                lines = [json.dumps({"path": p, **v}, ensure_ascii=False) for p, v in payload.items()]
                raw = "\n".join(lines).encode("utf-8")
            else:
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            gz_path = workdir / f"{name}.gz"
            with gzip.open(gz_path, "wb") as gz:
                gz.write(raw)
            assets.append(gz_path)

        rel = self.create_release(
            tag,
            f"EVE snapshot {version}",
            f"Index snapshot for client build {version}.\n\n"
            f"Contains gzipped index data. For HTML diff report see the "
            f"`compare-{{old}}-{version}` release.",
        )
        for asset in assets:
            self.upload_asset(rel["id"], asset, "application/gzip")

    def publish_compare(self, old_version: int, new_version: int, diff: dict, workdir: Path) -> None:
        tag = f"compare-{old_version}-{new_version}"
        if self.release_exists(tag):
            print(f"Compare release {tag} already exists, skipping")
            return
        workdir.mkdir(parents=True, exist_ok=True)
        from .html_report import write_diff_html

        json_path = workdir / "diff.json"
        html_path = workdir / "diff.html"
        json_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
        write_diff_html(diff, html_path)
        rel = self.create_release(
            tag,
            f"Compare {old_version} → {new_version}",
            f"Resource index diff between builds {old_version} and {new_version}.\n\n"
            f"Assets: **diff.json** (raw data), **diff.html** (report page).",
        )
        self.upload_asset(rel["id"], json_path, "application/json")
        self.upload_asset(rel["id"], html_path, "text/html")
