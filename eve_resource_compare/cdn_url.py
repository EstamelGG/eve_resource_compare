from __future__ import annotations

from . import config


def path_basename(logical_path: str) -> str:
    rel = logical_path.split(":", 1)[-1] if ":" in logical_path else logical_path
    return rel.rstrip("/").rsplit("/", 1)[-1] or rel


def cdn_download_url(logical_path: str, storage: str) -> str:
    path = logical_path.lower()
    if path.startswith("app:/"):
        return f"{config.BINARIES_BASE}/{storage}"
    return f"{config.RESOURCES_BASE}/{storage}"


def merge_path_index(*indexes: dict[str, dict]) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for index in indexes:
        merged.update(index)
    return merged
