"""Full pipeline smoke test (no GitHub Release)."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from eve_resource_compare.cdn_url import merge_path_index
from eve_resource_compare.compare import compare_indices
from eve_resource_compare.html_report import write_diff_html
from eve_resource_compare.indices_fetcher import fetch_version_indices
from eve_resource_compare.sde_loader import load_graphics, load_types
from eve_resource_compare.type_deps import (
    build_type_dependencies,
    invert_path_to_types,
    type_deps_to_json,
)
from eve_resource_compare.version import resolve_manifest_version, sde_is_ready

OLD_VERSION = 3421648
OUT_DIR = Path(".cache/test-output")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("=== 1/6 SDE gate ===")
    ready, server, sde_build = sde_is_ready()
    if not ready:
        print(f"SKIP: SDE {sde_build} != server {server}")
        return 0
    new_version = resolve_manifest_version(server)
    print(f"server={server} manifest={new_version} sde={sde_build}")

    print("=== 2/6 Fetch new indices ===")
    t = time.time()
    new_idx = fetch_version_indices(new_version)
    print(f"app={len(new_idx.app_index)} res={len(new_idx.res_index)} ({time.time()-t:.1f}s)")

    print("=== 3/6 Load SDE ===")
    t = time.time()
    types = load_types()
    graphics = load_graphics()
    print(f"types={len(types)} graphics={len(graphics)} ({time.time()-t:.1f}s)")

    print("=== 4/6 Build type dependencies ===")
    t = time.time()
    type_deps = build_type_dependencies(
        types, graphics, new_idx.dependencies_yaml, new_idx.res_index
    )
    path_to_types = invert_path_to_types(type_deps)
    print(f"SOF types={len(type_deps)} ({time.time()-t:.1f}s)")

    d640 = type_deps.get("640")
    if d640:
        print(f"type640: {d640.name_en} / {d640.name_zh}, paths={len(d640.paths)}")
    else:
        print("WARN: type 640 not in type_deps")

    deps_path = OUT_DIR / f"type-deps-{new_version}.json"
    deps_path.write_text(
        json.dumps(type_deps_to_json(type_deps), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {deps_path}")

    print(f"=== 5/6 Fetch old indices ({OLD_VERSION}) ===")
    t = time.time()
    old_idx = fetch_version_indices(OLD_VERSION, include_dependencies=False)
    print(f"app={len(old_idx.app_index)} res={len(old_idx.res_index)} ({time.time()-t:.1f}s)")

    print("=== 6/6 Compare ===")
    t = time.time()
    diff = compare_indices(
        old_idx.app_index,
        old_idx.res_index,
        new_idx.app_index,
        new_idx.res_index,
        path_to_types,
        OLD_VERSION,
        new_version,
        sde_build,
        "manual_test",
    )
    diff_path = OUT_DIR / f"diff-{OLD_VERSION}-{new_version}.json"
    diff_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = OUT_DIR / f"diff-{OLD_VERSION}-{new_version}.html"
    path_index = merge_path_index(
        old_idx.app_index, old_idx.res_index, new_idx.app_index, new_idx.res_index
    )
    write_diff_html(diff, html_path, path_index)
    print(f"Wrote {diff_path} and {html_path} ({time.time()-t:.1f}s)")

    s = diff["summary"]
    print(
        f"Summary: changed={s['changed']} added={s['added']} "
        f"removed={s['removed']} affected_types={s['affected_types']}"
    )

    affected = [
        (path, entry)
        for path, entry in diff["changes"].items()
        if entry.get("affected_type_ids")
    ]
    print(f"Paths with affected types: {len(affected)}")
    for path, entry in affected[:5]:
        ids = [a["typeID"] for a in entry["affected_type_ids"][:3]]
        print(f"  {path[:80]}... -> typeIDs {ids}")

    meta = {
        "test_at": datetime.now(timezone.utc).isoformat(),
        "old_version": OLD_VERSION,
        "new_version": new_version,
        "elapsed_sec": round(time.time() - t0, 1),
        "summary": s,
    }
    (OUT_DIR / "test-meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nOK total {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
