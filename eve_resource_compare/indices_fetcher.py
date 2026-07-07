from __future__ import annotations

from dataclasses import dataclass

import yaml

from . import config
from .cdn import fetch_text
from .index_parser import IndexEntry, build_index_map, parse_index_text


@dataclass
class VersionIndices:
    version: int
    app_index: dict[str, dict]
    res_index: dict[str, dict]
    dependencies_yaml: str
    manifest_entries: dict[str, IndexEntry]


def manifest_url(version: int) -> str:
    return config.MANIFEST_TEMPLATE.format(version=version)


def storage_url(storage: str) -> str:
    return f"{config.BINARIES_BASE}/{storage}"


def fetch_manifest(version: int) -> tuple[str, dict[str, IndexEntry]]:
    text = fetch_text(manifest_url(version))
    entries: dict[str, IndexEntry] = {}
    for entry in parse_index_text(text):
        entries[entry.path] = entry
    return text, entries


def _merge_res_index(target: dict[str, dict], text: str) -> None:
    for entry in parse_index_text(text):
        if entry.path.startswith("res:/"):
            target[entry.path] = {"hash": entry.hash, "size": entry.size}


def fetch_version_indices(version: int) -> VersionIndices:
    _, manifest_entries = fetch_manifest(version)

    app_index = build_index_map(
        (e for e in manifest_entries.values()),
        prefix="app:/",
    )

    res_index: dict[str, dict] = {}
    for name in config.RESFILEINDEX_NAMES:
        entry = manifest_entries.get(name)
        if entry:
            text = fetch_text(storage_url(entry.storage))
            _merge_res_index(res_index, text)

    deps_entry = manifest_entries.get(config.DEPS_MANIFEST_PATH)
    if not deps_entry:
        raise RuntimeError(f"{config.DEPS_MANIFEST_PATH} not found in manifest {version}")
    dependencies_yaml = fetch_text(storage_url(deps_entry.storage))

    return VersionIndices(
        version=version,
        app_index=app_index,
        res_index=res_index,
        dependencies_yaml=dependencies_yaml,
        manifest_entries=manifest_entries,
    )


def parse_dependencies(yaml_text: str) -> dict[str, list[str]]:
    data = yaml.safe_load(yaml_text) or {}
    result: dict[str, list[str]] = {}
    for key, deps in data.items():
        path = key.strip().replace("\\", "/")
        if not path.lower().startswith("res:/"):
            path = f"res:/{path.lstrip('/')}"
        path = path.lower()
        items = []
        for dep in deps or []:
            d = str(dep).strip().replace("\\", "/")
            if not d.lower().startswith(("res:/", "app:/")):
                d = f"res:/{d.lstrip('/')}"
            items.append(d.lower())
        result[path] = items
    return result
