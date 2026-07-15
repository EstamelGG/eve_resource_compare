USER_AGENT = "eve-resource-compare/0.1.0 (github-actions)"

ESI_STATUS_URL = "https://esi.evetech.net/latest/status/?datasource=tranquility"
SDE_LATEST_URL = "https://developers.eveonline.com/static-data/tranquility/latest.jsonl"
SDE_ZIP_URL = "https://developers.eveonline.com/static-data/eve-online-static-data-latest-jsonl.zip"

BINARIES_BASE = "https://binaries.eveonline.com"
RESOURCES_BASE = "https://resources.eveonline.com"
MANIFEST_TEMPLATE = f"{BINARIES_BASE}/eveonline_{{version}}.txt"

# ESI server_version may not match manifest filename; fallback candidates.
MANIFEST_FALLBACK_VERSIONS = (
    3424810, 3421648, 3419624, 3417089, 3409592, 3407448, 3405148, 3383521,
)

RESFILEINDEX_NAMES = (
    "app:/resfileindex.txt",
    "app:/resfileindex_windows.txt",
    "app:/resfileindex_prefetch.txt",
)
DEPS_MANIFEST_PATH = "app:/resfiledependencies.yaml"

SOF_ROOT = "res:/dx9/model/spaceobjectfactory"
SOF_DATA_BLACK = f"{SOF_ROOT}/data.black"
SOF_GENERIC_BLACK = f"{SOF_ROOT}/generic.black"
