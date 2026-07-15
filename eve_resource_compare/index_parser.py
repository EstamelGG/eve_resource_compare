from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class IndexEntry:
    path: str  # lowercase, for lookups / compare keys
    display_path: str  # original casing from index, for on-disk names
    storage: str
    hash: str
    size: int
    compressed_size: int
    flags: int


def normalize_path(path: str) -> str:
    """Canonical lowercase key used for matching."""
    p = path.strip().replace("\\", "/").lower()
    if not p.startswith(("app:/", "res:/", "cdn:/", "cdn:")):
        p = f"res:/{p.lstrip('/')}"
    return p


def display_path(path: str) -> str:
    """Preserve original casing; only normalize separators and scheme prefix."""
    p = path.strip().replace("\\", "/")
    low = p.lower()
    if low.startswith(("app:/", "res:/")):
        return p
    if low.startswith("cdn:/"):
        return "res:/" + p[5:].lstrip("/")
    if low.startswith("cdn:"):
        return "res:/" + p[4:].lstrip("/")
    return f"res:/{p.lstrip('/')}"


def parse_index_line(line: str) -> IndexEntry | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split(",")
    if len(parts) < 5:
        return None
    disp = display_path(parts[0])
    try:
        flags = int(parts[5]) if len(parts) >= 6 else 0
        return IndexEntry(
            path=disp.lower(),
            display_path=disp,
            storage=parts[1].strip(),
            hash=parts[2].strip().lower(),
            size=int(parts[3]),
            compressed_size=int(parts[4]),
            flags=flags,
        )
    except ValueError:
        return None


def parse_index_text(text: str) -> Iterator[IndexEntry]:
    for line in text.splitlines():
        entry = parse_index_line(line)
        if entry:
            yield entry


def entry_to_dict(entry: IndexEntry) -> dict:
    return {"hash": entry.hash, "size": entry.size, "storage": entry.storage}


def build_index_map(entries: Iterator[IndexEntry], prefix: str | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for entry in entries:
        if prefix and not entry.path.startswith(prefix):
            continue
        result[entry.path] = entry_to_dict(entry)
    return result
