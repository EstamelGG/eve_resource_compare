from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .compare import compare_indices
from .indices_fetcher import fetch_version_indices
from .release import GitHubReleases
from .sde_loader import load_graphics, load_types, set_cache_dir
from .type_deps import build_type_dependencies, invert_path_to_types, type_deps_to_json
from .version import resolve_manifest_version, sde_is_ready


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EVE resource version comparison pipeline")
    p.add_argument("--base-version", type=int, default=None, help="Manual baseline build number")
    p.add_argument("--github-token", default=None, help="GitHub token for releases")
    p.add_argument("--workdir", type=Path, default=None, help="Temp directory for assets")
    p.add_argument(
        "--sde-cache-dir",
        type=Path,
        default=None,
        help="Local directory for SDE zip and extracted jsonl (default: .cache/sde)",
    )
    p.add_argument(
        "--force-compare",
        action="store_true",
        help="Compare even when old_version == new_version",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if args.sde_cache_dir:
        set_cache_dir(args.sde_cache_dir)

    token = args.github_token or __import__("os").environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN required", file=sys.stderr)
        return 1

    ready, server_version, sde_build = sde_is_ready()
    if not ready:
        print(
            f"SKIP: SDE buildNumber ({sde_build}) != server_version ({server_version}); "
            "waiting for SDE update"
        )
        return 0

    new_version = resolve_manifest_version(server_version)
    print(f"Server version: {server_version}, manifest version: {new_version}, SDE: {sde_build}")

    gh = GitHubReleases(token)
    if args.base_version is not None:
        old_version = args.base_version
        base_source = "manual"
    else:
        old_version = gh.latest_snapshot_version()
        base_source = "latest_release"

    if old_version is None:
        print("First run: no previous snapshot release, creating baseline only")
    elif old_version == new_version and not args.force_compare and args.base_version is None:
        print(f"SKIP: already processed version {new_version}")
        return 0
    elif (
        old_version is not None
        and old_version != new_version
        and gh.compare_release_exists(old_version, new_version)
        and not args.force_compare
    ):
        print(f"SKIP: compare-{old_version}-{new_version} release already exists")
        return 0

    print("Loading SDE types and graphics...")
    types = load_types(sde_build)
    graphics = load_graphics(sde_build)

    print(f"Fetching indices for new version {new_version}...")
    new_indices = fetch_version_indices(new_version)

    print("Building type dependencies...")
    type_deps = build_type_dependencies(
        types,
        graphics,
        new_indices.dependencies_yaml,
        new_indices.res_index,
    )
    path_to_types = invert_path_to_types(type_deps)
    print(f"SOF types with dependencies: {len(type_deps)}")

    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="eve-compare-"))

    if old_version is None:
        meta = {
            "version": new_version,
            "sde_build": sde_build,
            "server_version": server_version,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        gh.publish_snapshot(
            new_version,
            meta,
            new_indices.app_index,
            new_indices.res_index,
            type_deps_to_json(type_deps),
            workdir,
        )
        print(f"Published baseline snapshot v{new_version}")
        return 0

    if old_version == new_version:
        print("Old and new version identical; skipping compare and snapshot")
        return 0

    print(f"Fetching indices for old version {old_version}...")
    old_indices = fetch_version_indices(old_version)

    print(f"Comparing {old_version} → {new_version}...")
    diff = compare_indices(
        old_indices.app_index,
        old_indices.res_index,
        new_indices.app_index,
        new_indices.res_index,
        path_to_types,
        old_version,
        new_version,
        sde_build,
        base_source,
    )
    summary = diff["summary"]
    print(
        f"Diff summary: changed={summary['changed']}, added={summary['added']}, "
        f"removed={summary['removed']}, affected_types={summary['affected_types']}"
    )

    gh.publish_compare(old_version, new_version, diff, workdir)
    print(f"Published compare-{old_version}-{new_version} (diff.json + diff.html)")

    meta = {
        "version": new_version,
        "sde_build": sde_build,
        "server_version": server_version,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    gh.publish_snapshot(
        new_version,
        meta,
        new_indices.app_index,
        new_indices.res_index,
        type_deps_to_json(type_deps),
        workdir,
    )
    print(f"Published snapshot v{new_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
