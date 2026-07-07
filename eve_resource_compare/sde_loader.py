from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Iterator

from . import config
from .cdn import download_to_file
from .version import get_sde_build_number

_CACHE_DIR: Path | None = None


def set_cache_dir(path: Path | str | None) -> None:
    global _CACHE_DIR
    _CACHE_DIR = Path(path) if path else None


def get_cache_dir() -> Path:
    if _CACHE_DIR is not None:
        return _CACHE_DIR
    env = os.environ.get("SDE_CACHE_DIR")
    return Path(env) if env else Path(config.SDE_CACHE_DIR)


def _iter_jsonl_file(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _extract_member(zf: zipfile.ZipFile, member: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member) as src, dest.open("wb") as dst:
        shutil.copyfileobj(src, dst)


def ensure_sde_cache(build: int | None = None, cache_dir: Path | None = None) -> Path:
    """Download SDE zip to disk and extract types/graphics jsonl. Returns cache root for build."""
    build = build or get_sde_build_number()
    root = (cache_dir or get_cache_dir()) / str(build)
    missing = [name for name in config.SDE_FILES if not (root / name).exists()]
    if not missing:
        return root

    root.mkdir(parents=True, exist_ok=True)
    zip_path = root / "sde.zip"
    if not zip_path.exists():
        print(f"Downloading SDE zip to {zip_path}...")
        download_to_file(config.SDE_ZIP_URL, zip_path, timeout=600)

    print(f"Extracting SDE files to {root}...")
    with zipfile.ZipFile(zip_path) as zf:
        members = {name.split("/")[-1]: name for name in zf.namelist()}
        for filename in missing:
            member = members.get(filename)
            if not member:
                raise RuntimeError(f"{filename} not found in SDE zip")
            _extract_member(zf, member, root / filename)

    return root


def load_types(build: int | None = None, cache_dir: Path | None = None) -> dict[int, dict]:
    root = ensure_sde_cache(build, cache_dir)
    types: dict[int, dict] = {}
    for row in _iter_jsonl_file(root / "types.jsonl"):
        types[int(row["_key"])] = row
    return types


def load_graphics(build: int | None = None, cache_dir: Path | None = None) -> dict[int, dict]:
    root = ensure_sde_cache(build, cache_dir)
    graphics: dict[int, dict] = {}
    for row in _iter_jsonl_file(root / "graphics.jsonl"):
        graphics[int(row["_key"])] = row
    return graphics
