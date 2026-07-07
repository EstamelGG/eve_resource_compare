from __future__ import annotations

import io
import json
import zipfile
from typing import Iterator

from . import config
from .cdn import fetch_stream_to_buffer

_SDE_ZIP: io.BytesIO | None = None


def _iter_jsonl(text: str) -> Iterator[dict]:
    for line in text.splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def _get_sde_zip() -> io.BytesIO:
    global _SDE_ZIP
    if _SDE_ZIP is None:
        print("Downloading SDE zip...")
        _SDE_ZIP = fetch_stream_to_buffer(config.SDE_ZIP_URL)
    return _SDE_ZIP


def load_sde_jsonl(filename: str) -> Iterator[dict]:
    with zipfile.ZipFile(_get_sde_zip()) as zf:
        for name in zf.namelist():
            if name.split("/")[-1] != filename:
                continue
            with zf.open(name) as f:
                text = io.TextIOWrapper(f, encoding="utf-8").read()
            yield from _iter_jsonl(text)
            return
    raise RuntimeError(f"{filename} not found in SDE zip")


def load_types() -> dict[int, dict]:
    types: dict[int, dict] = {}
    for row in load_sde_jsonl("types.jsonl"):
        types[int(row["_key"])] = row
    return types


def load_graphics() -> dict[int, dict]:
    graphics: dict[int, dict] = {}
    for row in load_sde_jsonl("graphics.jsonl"):
        graphics[int(row["_key"])] = row
    return graphics
