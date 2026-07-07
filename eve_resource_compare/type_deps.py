from __future__ import annotations

from dataclasses import dataclass, field

from . import config
from .indices_fetcher import parse_dependencies


@dataclass
class TypeDepInfo:
    type_id: int
    name_en: str
    name_zh: str
    paths: list[str] = field(default_factory=list)


def _type_names(type_row: dict) -> tuple[str, str]:
    name = type_row.get("name") or {}
    if isinstance(name, str):
        return name, ""
    return str(name.get("en") or ""), str(name.get("zh") or "")


def _sof_paths(hull: str, faction: str, race: str) -> list[str]:
    hull, faction, race = hull.lower(), faction.lower(), race.lower()
    root = config.SOF_ROOT
    return [
        config.SOF_DATA_BLACK,
        config.SOF_GENERIC_BLACK,
        f"{root}/hulls/{hull}.black",
        f"{root}/hulls/{hull}.red",
        f"{root}/factions/{faction}.black",
        f"{root}/factions/{faction}.red",
        f"{root}/races/{race}.black",
        f"{root}/races/{race}.red",
    ]


def _red_keys(hull: str, faction: str, race: str) -> list[str]:
    root = config.SOF_ROOT
    return [
        f"{root}/hulls/{hull.lower()}.red",
        f"{root}/factions/{faction.lower()}.red",
        f"{root}/races/{race.lower()}.red",
    ]


def _gr2_dirs(deps: list[str]) -> set[str]:
    dirs: set[str] = set()
    for p in deps:
        if p.endswith(".gr2"):
            rel = p.removeprefix("res:/")
            if "/" in rel:
                dirs.add(rel.rsplit("/", 1)[0] + "/")
    return dirs


def _same_dir_paths(res_index: dict[str, dict], dirs: set[str]) -> list[str]:
    if not dirs:
        return []
    found: list[str] = []
    for path in res_index:
        rel = path.removeprefix("res:/")
        for d in dirs:
            if rel.startswith(d):
                found.append(path)
                break
    return found


def _filter_paths(paths: set[str]) -> list[str]:
    return sorted(p for p in paths if p.startswith(("app:/", "res:/")))


def build_type_dependencies(
    types: dict[int, dict],
    graphics: dict[int, dict],
    dependencies_yaml: str,
    res_index: dict[str, dict],
) -> dict[str, TypeDepInfo]:
    deps_map = parse_dependencies(dependencies_yaml)
    result: dict[str, TypeDepInfo] = {}

    for type_id, type_row in types.items():
        graphic_id = type_row.get("graphicID")
        if graphic_id is None:
            continue
        g = graphics.get(int(graphic_id))
        if not g:
            continue
        hull = g.get("sofHullName")
        if not hull:
            continue
        faction = g.get("sofFactionName") or ""
        race = g.get("sofRaceName") or ""
        if not faction or not race:
            continue

        paths: set[str] = set(_sof_paths(hull, faction, race))
        direct: list[str] = []
        for red_key in _red_keys(hull, faction, race):
            direct.extend(deps_map.get(red_key, []))
        paths.update(direct)

        gr2_dirs = _gr2_dirs(direct)
        paths.update(_same_dir_paths(res_index, gr2_dirs))

        name_en, name_zh = _type_names(type_row)
        result[str(type_id)] = TypeDepInfo(
            type_id=type_id,
            name_en=name_en,
            name_zh=name_zh,
            paths=_filter_paths(paths),
        )
    return result


def invert_path_to_types(type_deps: dict[str, TypeDepInfo]) -> dict[str, list[TypeDepInfo]]:
    inv: dict[str, list[TypeDepInfo]] = {}
    for info in type_deps.values():
        for path in info.paths:
            inv.setdefault(path, []).append(info)
    return inv


def type_deps_to_json(type_deps: dict[str, TypeDepInfo]) -> dict:
    return {
        tid: {
            "name_en": info.name_en,
            "name_zh": info.name_zh,
            "paths": info.paths,
        }
        for tid, info in type_deps.items()
    }
