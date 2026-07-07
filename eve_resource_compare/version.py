from __future__ import annotations

import json

from . import config
from .cdn import fetch_text, head_ok
from .indices_fetcher import manifest_url


def get_server_version() -> int:
    data = json.loads(fetch_text(config.ESI_STATUS_URL))
    return int(data["server_version"])


def get_sde_build_number() -> int:
    for line in fetch_text(config.SDE_LATEST_URL).splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if record.get("_key") == "sde":
            return int(record["buildNumber"])
    raise RuntimeError("SDE buildNumber not found in latest.jsonl")


def sde_is_ready() -> tuple[bool, int, int]:
    server = get_server_version()
    sde_build = get_sde_build_number()
    return sde_build == server, server, sde_build


def resolve_manifest_version(server_version: int) -> int:
    candidates = [server_version, *config.MANIFEST_FALLBACK_VERSIONS]
    seen: set[int] = set()
    for v in candidates:
        if v in seen:
            continue
        seen.add(v)
        if head_ok(manifest_url(v)):
            return v
    raise RuntimeError(f"No manifest found for server_version {server_version}")


def find_previous_manifest_version(new_version: int) -> int | None:
    """Highest manifest build below new_version, from known candidates."""
    candidates = [v for v in config.MANIFEST_FALLBACK_VERSIONS if v < new_version]
    candidates.sort(reverse=True)
    for v in candidates:
        if head_ok(manifest_url(v)):
            return v
    return None
