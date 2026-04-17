"""Helpers for reconstructing and scoring web targets from observed paths."""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

_FILESYSTEM_ROOT_SEGMENTS = {
    "bin",
    "boot",
    "dev",
    "etc",
    "home",
    "lib",
    "lib64",
    "media",
    "mnt",
    "opt",
    "proc",
    "root",
    "run",
    "sbin",
    "srv",
    "sys",
    "tmp",
    "usr",
    "var",
    "windows",
    "users",
    "program files",
    "documents and settings",
}
_STATIC_RESOURCE_SUFFIXES = {
    ".avi",
    ".bz2",
    ".css",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".tar",
    ".tgz",
    ".ttf",
    ".txt",
    ".woff",
    ".woff2",
    ".xml",
    ".zip",
    ".7z",
}
_NON_CANDIDATE_WEB_PATHS = {
    "/favicon.ico",
    "/health",
    "/healthz",
    "/metrics",
    "/robots.txt",
    "/sitemap.xml",
}


def reconstruct_web_urls(*, target_url: str | None, file_paths: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Join relative web paths against the known HTTP(S) target root."""

    base_url = _normalized_http_root(target_url)
    if base_url is None:
        return ()
    reconstructed: list[str] = []
    seen: set[str] = set()
    for path in file_paths:
        normalized_path = str(path).strip()
        if not _looks_like_web_path(normalized_path):
            continue
        absolute_url = urljoin(base_url, normalized_path)
        if absolute_url in seen:
            continue
        seen.add(absolute_url)
        reconstructed.append(absolute_url)
    return tuple(reconstructed)


def derive_sqli_candidate_url(
    *,
    target_url: str | None,
    urls: tuple[str, ...] | list[str],
    file_paths: tuple[str, ...] | list[str] = (),
) -> str | None:
    """Prefer query-bearing URLs, then bounded app-like path discoveries."""

    combined_urls = list(urls)
    combined_urls.extend(reconstruct_web_urls(target_url=target_url, file_paths=file_paths))
    for url in combined_urls:
        if _has_explicit_query_candidate(url):
            return url
    for url in combined_urls:
        if _is_path_based_candidate_url(url):
            return url
    return None


def _normalized_http_root(target_url: str | None) -> str | None:
    if not target_url:
        return None
    parsed = urlparse(str(target_url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/"


def _has_explicit_query_candidate(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and ("?" in url or "=" in url)


def _is_path_based_candidate_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return _looks_like_sqli_candidate_path(parsed.path)


def _looks_like_web_path(path: str) -> bool:
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return False
    parts = [part for part in path.split("/") if part]
    if not parts:
        return False
    return parts[0].lower() not in _FILESYSTEM_ROOT_SEGMENTS


def _looks_like_sqli_candidate_path(path: str) -> bool:
    if not _looks_like_web_path(path):
        return False
    lowered = path.lower()
    if lowered in _NON_CANDIDATE_WEB_PATHS:
        return False
    suffix = PurePosixPath(lowered).suffix
    return suffix not in _STATIC_RESOURCE_SUFFIXES
