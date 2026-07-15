from __future__ import annotations

import io
import os
import time
from typing import Callable, Iterator, TypeVar

import requests

from .config import USER_AGENT

T = TypeVar("T")

CDN_TIMEOUT = int(os.environ.get("CDN_TIMEOUT", "300"))
CDN_LARGE_TIMEOUT = int(os.environ.get("CDN_LARGE_TIMEOUT", "600"))
CDN_RETRIES = int(os.environ.get("CDN_RETRIES", "5"))


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


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code >= 500
    return False


def _retry_call(fn: Callable[[], T], label: str) -> T:
    last: Exception | None = None
    for attempt in range(CDN_RETRIES):
        try:
            return fn()
        except CdnError:
            raise
        except Exception as e:
            if not _is_retryable(e):
                raise
            last = e
            if attempt + 1 >= CDN_RETRIES:
                break
            wait = min(2 ** attempt * 5, 60)
            print(f"CDN retry {attempt + 1}/{CDN_RETRIES} for {label} in {wait}s: {e}")
            time.sleep(wait)
    raise last  # type: ignore[misc]


def fetch_bytes(url: str, timeout: int = CDN_TIMEOUT) -> bytes:
    def _do() -> bytes:
        resp = _SESSION.get(url, timeout=timeout)
        if resp.status_code == 403:
            raise CdnError(f"403 Forbidden (missing User-Agent?): {url}")
        resp.raise_for_status()
        return resp.content

    return _retry_call(_do, url)


def fetch_text(url: str, timeout: int = CDN_TIMEOUT) -> str:
    return fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")


def fetch_stream(url: str, timeout: int = CDN_LARGE_TIMEOUT) -> Iterator[bytes]:
    def _open() -> requests.Response:
        resp = _SESSION.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
        return resp

    resp = _retry_call(_open, url)
    try:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                yield chunk
    finally:
        resp.close()


def fetch_stream_to_buffer(url: str, timeout: int = CDN_LARGE_TIMEOUT) -> io.BytesIO:
    def _do() -> io.BytesIO:
        buf = io.BytesIO()
        for chunk in fetch_stream(url, timeout=timeout):
            buf.write(chunk)
        buf.seek(0)
        return buf

    return _retry_call(_do, url)


def download_to_file(url: str, dest: os.PathLike[str] | str, timeout: int = CDN_LARGE_TIMEOUT) -> int:
    """Stream URL to disk; returns written byte count."""
    path = os.fspath(dest)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.part"

    def _do() -> int:
        written = 0
        with open(tmp, "wb") as f:
            for chunk in fetch_stream(url, timeout=timeout):
                f.write(chunk)
                written += len(chunk)
        os.replace(tmp, path)
        return written

    try:
        return _retry_call(_do, url)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def head_ok(url: str, timeout: int = 30) -> bool:
    def _do() -> bool:
        resp = _SESSION.head(url, timeout=timeout, allow_redirects=True)
        return resp.status_code == 200

    try:
        return _retry_call(_do, url)
    except (requests.Timeout, requests.ConnectionError, requests.HTTPError):
        return False
