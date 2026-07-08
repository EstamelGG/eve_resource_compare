from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .cdn_url import merge_path_index
from .compare import compare_indices
from .indices_fetcher import fetch_version_indices
from .release import GitHubReleases
from .sde_loader import load_graphics, load_types
from .type_deps import build_type_dependencies, invert_path_to_types
from .version import find_previous_manifest_version, resolve_manifest_version, sde_is_ready


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EVE resource version comparison pipeline")
    p.add_argument("--base-version", type=int, default=None, help="Manual baseline build number")
    p.add_argument("--github-token", default=None, help="GitHub token for releases")
    p.add_argument("--workdir", type=Path, default=None, help="Temp directory for assets")
    p.add_argument(
        "--force-compare",
        action="store_true",
        help="Compare even when compare release already exists or versions match",
    )
    return p.parse_args()


def _resolve_old_version(
    gh: GitHubReleases,
    new_version: int,
    base_version: int | None,
    force: bool,
) -> tuple[int | None, str | None]:
    """Return (old_version, base_source) or (None, None) to skip."""
    if base_version is not None:
        return base_version, "manual"

    last_new = gh.latest_compare_new_version()
    prev_manifest = find_previous_manifest_version(new_version)

    if last_new == new_version and not force:
        if prev_manifest and not gh.compare_release_exists(prev_manifest, new_version):
            print(f"Compare-{prev_manifest}-{new_version} missing; will backfill")
            return prev_manifest, "auto_previous_manifest"
        print(f"SKIP: already compared up to version {new_version}")
        return None, None

    if last_new is not None and last_new < new_version:
        return last_new, "latest_compare"

    if prev_manifest is not None:
        return prev_manifest, "auto_previous_manifest"

    print("SKIP: no previous manifest version to compare against")
    return None, None


def main() -> int:
    args = _parse_args()

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
    old_version, base_source = _resolve_old_version(
        gh, new_version, args.base_version, args.force_compare
    )
    if old_version is None:
        return 0

    if old_version == new_version and not args.force_compare:
        print(f"SKIP: old and new version are both {new_version}")
        return 0

    if (
        gh.compare_release_exists(old_version, new_version)
        and not args.force_compare
    ):
        print(f"SKIP: compare-{old_version}-{new_version} release already exists")
        return 0

    print("Loading SDE types and graphics...")
    types = load_types()
    graphics = load_graphics()

    print(f"Fetching indices for old version {old_version}...")
    old_indices = fetch_version_indices(old_version, include_dependencies=False)

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
        base_source or "unknown",
    )
    summary = diff["summary"]
    print(
        f"Diff summary: changed={summary['changed']}, added={summary['added']}, "
        f"removed={summary['removed']}, affected_types={summary['affected_types']}"
    )

    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="eve-compare-"))
    path_index = merge_path_index(
        old_indices.app_index,
        old_indices.res_index,
        new_indices.app_index,
        new_indices.res_index,
    )
    gh.publish_compare(old_version, new_version, diff, workdir, path_index)
    print(f"Published compare-{old_version}-{new_version} (diff.json + diff.html)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
