from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse


WINDOWS_RESERVED = re.compile(r'[<>:"/\\\\|?*]+')


def normalize_url(base_url: str, href: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", href)


def slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.strip("/")
    return slug or "index"


def safe_filename(value: str) -> str:
    cleaned = WINDOWS_RESERVED.sub("_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned.strip("._ ") or "item"
