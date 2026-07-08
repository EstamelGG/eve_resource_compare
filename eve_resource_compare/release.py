from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests

from .config import USER_AGENT

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

    def latest_compare_new_version(self) -> int | None:
        versions: list[int] = []
        for rel in self.list_releases():
            m = _COMPARE_TAG.match(rel.get("tag_name", ""))
            if m:
                versions.append(int(m.group(2)))
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
        url = f"https://uploads.github.com/repos/{self.repo}/releases/{release_id}/assets"
        with filepath.open("rb") as f:
            resp = self.session.post(
                url,
                params={"name": filepath.name},
                data=f,
                headers={"Content-Type": content_type},
                timeout=300,
            )
        resp.raise_for_status()

    def publish_compare(
        self,
        old_version: int,
        new_version: int,
        diff: dict,
        workdir: Path,
        path_index: dict[str, dict] | None = None,
    ) -> None:
        tag = f"compare-{old_version}-{new_version}"
        if self.release_exists(tag):
            print(f"Compare release {tag} already exists, skipping")
            return
        workdir.mkdir(parents=True, exist_ok=True)
        from .html_report import write_diff_html

        json_name = f"diff_{old_version}_{new_version}.json"
        html_name = f"diff_{old_version}_{new_version}.html"
        json_path = workdir / json_name
        html_path = workdir / html_name
        json_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
        write_diff_html(diff, html_path, path_index)
        rel = self.create_release(
            tag,
            f"Compare {old_version} → {new_version}",
            f"Resource index diff between builds {old_version} and {new_version}.\n\n"
            f"Assets: **{json_name}** (raw data), **{html_name}** (report page).",
        )
        self.upload_asset(rel["id"], json_path, "application/json")
        self.upload_asset(rel["id"], html_path, "text/html")
