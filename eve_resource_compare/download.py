"""Download a full EVE client SharedCache mirror for a given buildNumber.

Layout (matches client SharedCache):
  {out}/tq/...           ← binaries.eveonline.com (app:/ logical paths)
  {out}/ResFiles/{ss}/…  ← resources.eveonline.com (resfileindex storage keys)

Usage:
  python -m eve_resource_compare.download --build 3396210 --out D:\\SharedCache
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from . import config
from .cdn import CDN_LARGE_TIMEOUT, CDN_RETRIES, CdnError, download_to_file
from .index_parser import IndexEntry, parse_index_text
from .indices_fetcher import fetch_manifest, storage_url


@dataclass(frozen=True)
class DownloadJob:
    url: str
    dest: Path
    # Client cache stores uncompressed size; CDN may serve either size.
    expected_sizes: frozenset[int]
    expected_hash: str  # lowercase md5 hex of on-disk content
    label: str


def _app_rel_path(logical: str) -> str:
    """app:/carbon.json → carbon.json ; app:/bin64/x.dll → bin64/x.dll"""
    p = logical.strip().replace("\\", "/")
    if p.lower().startswith("app:/"):
        p = p[5:]
    return p.lstrip("/")


def _resource_url(storage: str) -> str:
    return f"{config.RESOURCES_BASE}/{storage}"


def _entry_sizes(entry: IndexEntry) -> frozenset[int]:
    return frozenset(s for s in (entry.size, entry.compressed_size) if s > 0)


def _file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _should_skip(dest: Path, expected_sizes: frozenset[int], expected_hash: str) -> bool:
    """Size gate first; MD5 only when size matches."""
    if not dest.is_file():
        return False
    if expected_sizes and dest.stat().st_size not in expected_sizes:
        return False
    if not expected_hash:
        return True
    return _file_md5(dest) == expected_hash


def collect_binary_jobs(outdir: Path, entries: dict[str, IndexEntry]) -> list[DownloadJob]:
    tq = outdir / "tq"
    jobs: list[DownloadJob] = []
    for path, entry in entries.items():
        if not path.startswith("app:/"):
            continue
        rel = _app_rel_path(entry.display_path)
        dest = tq / Path(*rel.split("/"))
        jobs.append(
            DownloadJob(
                url=storage_url(entry.storage),
                dest=dest,
                expected_sizes=_entry_sizes(entry),
                expected_hash=entry.hash,
                label=entry.display_path,
            )
        )
    return jobs


def collect_res_jobs(outdir: Path, index_texts: list[str]) -> list[DownloadJob]:
    res_files = outdir / "ResFiles"
    seen: set[str] = set()
    jobs: list[DownloadJob] = []
    for text in index_texts:
        for entry in parse_index_text(text):
            if not entry.path.startswith("res:/"):
                continue
            if entry.storage in seen:
                continue
            seen.add(entry.storage)
            dest = res_files / Path(*entry.storage.split("/"))
            jobs.append(
                DownloadJob(
                    url=_resource_url(entry.storage),
                    dest=dest,
                    expected_sizes=_entry_sizes(entry),
                    expected_hash=entry.hash,
                    label=entry.display_path,
                )
            )
    return jobs


def _partition_jobs(
    jobs: list[DownloadJob],
    *,
    skip_existing: bool,
    workers: int,
) -> tuple[list[DownloadJob], int]:
    """Return (need_download, skip_count)."""
    if not skip_existing:
        return jobs, 0

    total = len(jobs)
    print(f"Verifying {total} files (size gate + md5) with {workers} workers...")
    need: list[DownloadJob] = []
    skip = 0
    done = 0

    def _check(job: DownloadJob) -> tuple[DownloadJob, bool]:
        return job, _should_skip(job.dest, job.expected_sizes, job.expected_hash)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_check, job) for job in jobs]
        for fut in as_completed(futures):
            job, skipped = fut.result()
            done += 1
            if skipped:
                skip += 1
            else:
                need.append(job)
            if done % 2000 == 0 or done == total:
                print(f"  verify [{done}/{total}] skip={skip} need={len(need)}")

    return need, skip


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (aiohttp.ClientConnectionError, asyncio.TimeoutError)):
        return True
    if isinstance(exc, aiohttp.ClientResponseError):
        return exc.status >= 500
    return False


async def _aio_download_to_file(
    session: aiohttp.ClientSession,
    url: str,
    dest: Path,
) -> int:
    """Stream URL to disk; returns written byte count."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last: Exception | None = None

    for attempt in range(CDN_RETRIES):
        try:
            async with session.get(url) as resp:
                if resp.status == 403:
                    raise CdnError(f"403 Forbidden (missing User-Agent?): {url}")
                resp.raise_for_status()
                written = 0
                with open(tmp, "wb") as f:
                    async for chunk in resp.content.iter_chunked(65536):
                        f.write(chunk)
                        written += len(chunk)
            os.replace(tmp, dest)
            return written
        except CdnError:
            raise
        except Exception as e:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            if not _is_retryable(e):
                raise
            last = e
            if attempt + 1 >= CDN_RETRIES:
                break
            wait = min(2**attempt * 5, 60)
            print(f"CDN retry {attempt + 1}/{CDN_RETRIES} for {url} in {wait}s: {e}")
            await asyncio.sleep(wait)

    raise last  # type: ignore[misc]


async def _download_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    job: DownloadJob,
) -> tuple[str, str]:
    """Returns (status, detail) status in {ok, fail}."""
    async with sem:
        try:
            await _aio_download_to_file(session, job.url, job.dest)
            return "ok", job.label
        except Exception as e:
            return "fail", f"{job.label}: {e}"


async def _run_jobs(jobs: list[DownloadJob], workers: int) -> tuple[int, int]:
    ok = fail = 0
    done = 0
    total = len(jobs)
    sem = asyncio.Semaphore(workers)
    timeout = aiohttp.ClientTimeout(total=CDN_LARGE_TIMEOUT)
    connector = aiohttp.TCPConnector(limit=workers)

    async with aiohttp.ClientSession(
        headers={"User-Agent": config.USER_AGENT},
        timeout=timeout,
        connector=connector,
        trust_env=True,
    ) as session:
        tasks = [
            asyncio.create_task(_download_one(session, sem, job))
            for job in jobs
        ]
        for fut in asyncio.as_completed(tasks):
            status, detail = await fut
            done += 1
            if status == "ok":
                ok += 1
            else:
                fail += 1
                print(f"FAIL {detail}")
            if done % 50 == 0 or done == total:
                print(f"[{done}/{total}] ok={ok} fail={fail}")

    return ok, fail


def run_download(
    build: int,
    outdir: Path,
    *,
    workers: int = 8,
    skip_existing: bool = True,
    binaries_only: bool = False,
    resources_only: bool = False,
) -> int:
    outdir = outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "tq").mkdir(exist_ok=True)
    (outdir / "ResFiles").mkdir(exist_ok=True)

    print(f"Manifest: eveonline_{build}.txt → {outdir}")
    _, entries = fetch_manifest(build)
    print(f"Manifest entries: {len(entries)}")

    jobs: list[DownloadJob] = []
    if not resources_only:
        jobs.extend(collect_binary_jobs(outdir, entries))
        print(f"Binary (app:/) jobs: {len(jobs)}")

    if not binaries_only:
        # Need index files on disk first (or in memory) before res downloads.
        index_texts: list[str] = []
        tq = outdir / "tq"
        for name in config.RESFILEINDEX_NAMES:
            entry = entries.get(name)
            if not entry:
                continue
            rel = _app_rel_path(entry.display_path)
            dest = tq / Path(*rel.split("/"))
            if not _should_skip(dest, _entry_sizes(entry), entry.hash):
                print(f"Fetching index {entry.display_path}...")
                download_to_file(storage_url(entry.storage), dest)
            print(f"Parsing {dest.name}...")
            index_texts.append(dest.read_text(encoding="utf-8", errors="replace"))

        res_jobs = collect_res_jobs(outdir, index_texts)
        print(f"Resource (res:/) jobs: {len(res_jobs)}")
        jobs.extend(res_jobs)

    if not jobs:
        print("Nothing to download")
        return 0

    need, skip = _partition_jobs(jobs, skip_existing=skip_existing, workers=workers)
    if not need:
        print(f"Done: ok=0 skip={skip} fail=0 → {outdir}")
        return 0

    print(f"Downloading {len(need)} files with {workers} aiohttp workers (skipped {skip})...")
    ok, fail = asyncio.run(_run_jobs(need, workers))
    print(f"Done: ok={ok} skip={skip} fail={fail} → {outdir}")
    return 1 if fail else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Download EVE SharedCache mirror for a buildNumber",
    )
    p.add_argument("--build", "-b", type=int, required=True, help="Client buildNumber")
    p.add_argument("--out", "-o", type=Path, required=True, help="Output SharedCache root")
    p.add_argument("--workers", "-j", type=int, default=8, help="Parallel downloads / verify")
    p.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-download even if dest file exists with matching size+md5",
    )
    p.add_argument("--binaries-only", action="store_true", help="Only download app:/ files")
    p.add_argument("--resources-only", action="store_true", help="Only download res:/ files")
    args = p.parse_args(argv)

    if args.binaries_only and args.resources_only:
        print("ERROR: --binaries-only and --resources-only are mutually exclusive", file=sys.stderr)
        return 1

    return run_download(
        args.build,
        args.out,
        workers=max(1, args.workers),
        skip_existing=not args.no_skip_existing,
        binaries_only=args.binaries_only,
        resources_only=args.resources_only,
    )


if __name__ == "__main__":
    sys.exit(main())
