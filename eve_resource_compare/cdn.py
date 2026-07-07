from __future__ import annotations

import os
from typing import Iterator

import requests

from .config import USER_AGENT


class CdnError(Exception):
    pass


def _proxies() -> dict[str, str] | None:
    http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not http and not https:
        return None
    return {"http": http or https, "https": https or http}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    s.trust_env = True
    proxies = _proxies()
    if proxies:
        s.proxies.update(proxies)
    return s


_SESSION = _session()


def fetch_bytes(url: str, timeout: int = 120) -> bytes:
    resp = _SESSION.get(url, timeout=timeout)
    if resp.status_code == 403:
        raise CdnError(f"403 Forbidden (missing User-Agent?): {url}")
    resp.raise_for_status()
    return resp.content


def fetch_text(url: str, timeout: int = 120) -> str:
    return fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")


def fetch_stream(url: str, timeout: int = 300) -> Iterator[bytes]:
    resp = _SESSION.get(url, timeout=timeout, stream=True)
    resp.raise_for_status()
    for chunk in resp.iter_content(chunk_size=65536):
        if chunk:
            yield chunk


def download_to_file(url: str, dest: os.PathLike[str] | str, timeout: int = 600) -> None:
    path = os.fspath(dest)
    tmp = f"{path}.part"
    with open(tmp, "wb") as f:
        for chunk in fetch_stream(url, timeout=timeout):
            f.write(chunk)
    os.replace(tmp, path)


def head_ok(url: str, timeout: int = 30) -> bool:
    resp = _SESSION.head(url, timeout=timeout, allow_redirects=True)
    return resp.status_code == 200
