from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .type_deps import TypeDepInfo


def _merge_indices(app_index: dict[str, dict], res_index: dict[str, dict]) -> dict[str, dict]:
    merged = dict(app_index)
    merged.update(res_index)
    return merged


def _all_affected_types(path: str, path_to_types: dict[str, list[TypeDepInfo]]) -> list[dict]:
    seen: set[int] = set()
    out: list[dict] = []
    for info in path_to_types.get(path, []):
        if info.type_id in seen:
            continue
        seen.add(info.type_id)
        out.append({
            "typeID": info.type_id,
            "name_en": info.name_en,
            "name_zh": info.name_zh,
        })
    return sorted(out, key=lambda x: x["typeID"])


def _affected_types(path: str, path_to_types: dict[str, list[TypeDepInfo]]) -> list[dict]:
    return _all_affected_types(path, path_to_types)[:3]


def compare_indices(
    old_app: dict[str, dict],
    old_res: dict[str, dict],
    new_app: dict[str, dict],
    new_res: dict[str, dict],
    path_to_types: dict[str, list[TypeDepInfo]],
    old_version: int,
    new_version: int,
    sde_build: int,
    base_version_source: str,
) -> dict[str, Any]:
    old_all = _merge_indices(old_app, old_res)
    new_all = _merge_indices(new_app, new_res)
    all_paths = set(old_all) | set(new_all)

    changes: dict[str, Any] = {}
    changed = added = removed = 0
    affected_type_ids: set[int] = set()

    for path in sorted(all_paths):
        old_entry = old_all.get(path)
        new_entry = new_all.get(path)

        if old_entry and new_entry:
            if old_entry["hash"] == new_entry["hash"]:
                continue
            changed += 1
            affected = _affected_types(path, path_to_types)
            for a in _all_affected_types(path, path_to_types):
                affected_type_ids.add(a["typeID"])
            changes[path] = {
                "old": old_entry,
                "new": new_entry,
                "affected_type_ids": affected,
            }
        elif new_entry and not old_entry:
            added += 1
            affected = _affected_types(path, path_to_types)
            for a in _all_affected_types(path, path_to_types):
                affected_type_ids.add(a["typeID"])
            changes[path] = {
                "old": None,
                "new": new_entry,
                "affected_type_ids": affected,
            }
        elif old_entry and not new_entry:
            removed += 1
            affected = _affected_types(path, path_to_types)
            for a in _all_affected_types(path, path_to_types):
                affected_type_ids.add(a["typeID"])
            changes[path] = {
                "old": old_entry,
                "new": None,
                "affected_type_ids": affected,
            }

    return {
        "meta": {
            "old_version": old_version,
            "new_version": new_version,
            "sde_build": sde_build,
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "base_version_source": base_version_source,
        },
        "changes": changes,
        "summary": {
            "changed": changed,
            "added": added,
            "removed": removed,
            "affected_types": len(affected_type_ids),
        },
    }
