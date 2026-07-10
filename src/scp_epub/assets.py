from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from bs4 import BeautifulSoup, Tag

from .models import FetchResult, ProcessedPage
from .transform import ASSET_ATTRIBUTES


@dataclass(frozen=True)
class AssetRef:
    source_url: str
    path: Path
    href: str
    content_type: str


class AssetFetcher(Protocol):
    def fetch_asset(self, url: str) -> FetchResult:
        ...


def localize_assets(
    pages: list[ProcessedPage],
    fetcher: AssetFetcher,
) -> tuple[list[ProcessedPage], list[AssetRef], list[str]]:
    localized_by_url: dict[str, AssetRef] = {}
    missing_assets: list[str] = []
    seen_missing: set[str] = set()
    used_hrefs: set[str] = set()

    for url in _unique(value for page in pages for value in page.asset_urls):
        try:
            result = fetcher.fetch_asset(url)
        except Exception:
            if url not in seen_missing:
                seen_missing.add(url)
                missing_assets.append(url)
            continue

        href = _asset_href(url, result.path, used_hrefs)
        used_hrefs.add(href)
        localized_by_url[url] = AssetRef(
            source_url=url,
            path=result.path,
            href=href,
            content_type=result.content_type,
        )

    localized_pages = [_rewrite_page_assets(page, localized_by_url) for page in pages]
    return localized_pages, list(localized_by_url.values()), missing_assets


def _asset_href(url: str, path: Path, used_hrefs: set[str]) -> str:
    href = f"assets/{path.name}"
    if href not in used_hrefs:
        return href

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    suffix = path.suffix or ".bin"
    return f"assets/{digest}{suffix}"


def _rewrite_page_assets(page: ProcessedPage, localized_by_url: dict[str, AssetRef]) -> ProcessedPage:
    if not page.asset_urls:
        return page

    soup = BeautifulSoup(f"<root>{page.xhtml}</root>", "html.parser")
    root = soup.find("root")
    if root is None:
        return page

    changed = False
    for tag in root.find_all(ASSET_ATTRIBUTES.keys()):
        if not isinstance(tag, Tag):
            continue
        attribute = ASSET_ATTRIBUTES[str(tag.name)]
        raw_url = tag.get(attribute)
        if not isinstance(raw_url, str):
            continue
        asset = localized_by_url.get(raw_url)
        if asset is None:
            continue
        tag[attribute] = f"../{asset.href}"
        changed = True

    if not changed:
        return page

    xhtml = "".join(str(child) for child in root.contents).strip()
    return replace(page, xhtml=xhtml)


def _unique(values) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values
