from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse


WINDOWS_RESERVED = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]+')
WINDOWS_RESERVED_BASENAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
REAL_SCHEMES = {"http", "https", "mailto", "ftp", "javascript", "data", "tel"}
WIKIDOT_PAGE_NAMESPACES = {"old", "alt"}


def normalize_url(base_url: str, href: str) -> str:
    parsed_href = urlparse(href)
    scheme = parsed_href.scheme.lower()
    if scheme in WIKIDOT_PAGE_NAMESPACES:
        href = f"./{href}"
    elif scheme in REAL_SCHEMES:
        return href
    return urljoin(base_url, href)


def slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.strip("/")
    return slug or "index"


def safe_filename(value: str) -> str:
    cleaned = WINDOWS_RESERVED.sub("_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._ ") or "item"
    return _avoid_windows_reserved_basename(cleaned)


def _avoid_windows_reserved_basename(value: str) -> str:
    basename, separator, remainder = value.partition(".")
    if basename.lower() not in WINDOWS_RESERVED_BASENAMES:
        return value
    return f"{basename}_{separator}{remainder}" if separator else f"{basename}_"
