from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from scp_epub.models import PageRef, ProcessedPage
from scp_epub.urls import normalize_url, slug_from_url


NON_DOWNLOADABLE_ASSET_SCHEMES = {"data", "mailto", "tel"}
UNWANTED_TAGS = {"script", "style", "iframe", "nav", "aside"}
UNWANTED_IDS = {
    "action-area",
    "edit-page-form",
    "page-info",
    "page-options-bottom",
    "page-options-container",
    "page-options-top",
    "side-bar",
    "top-bar",
    "toc",
}
UNWANTED_CLASSES = {
    "page-options",
    "page-options-area",
    "page-options-bottom",
    "page-options-bottom-2",
    "page-options-top",
    "page-rate-widget-box",
    "rate-box",
    "rate-box-with-credit-button",
    "rating-box",
    "toc",
}
ASSET_ATTRIBUTES = {
    "img": "src",
    "source": "src",
    "link": "href",
    "object": "data",
}


def transform_page(
    entry: PageRef,
    html: str,
    base_url: str,
    manifest_slugs: set[str] | None = None,
) -> ProcessedPage:
    soup = BeautifulSoup(html, "html.parser")
    page_content = soup.select_one("#page-content")
    if page_content is None:
        raise ValueError("missing #page-content")

    for tag in list(page_content.find_all(_is_unwanted_element)):
        tag.decompose()

    asset_urls: list[str] = []
    seen_assets: set[str] = set()
    _normalize_assets(page_content, base_url, asset_urls, seen_assets)

    internal_links: list[str] = []
    external_links: list[str] = []
    seen_internal: set[str] = set()
    seen_external: set[str] = set()
    known_slugs = {slug.lower() for slug in manifest_slugs or set()}
    _normalize_links(
        page_content,
        base_url,
        known_slugs,
        internal_links,
        seen_internal,
        external_links,
        seen_external,
    )

    for tag in page_content.find_all(True):
        _sanitize_attributes(tag)

    xhtml = "".join(str(child) for child in page_content.contents).strip()
    return ProcessedPage(
        entry=entry,
        xhtml=xhtml,
        asset_urls=tuple(asset_urls),
        internal_links=tuple(internal_links),
        external_links=tuple(external_links),
    )


def _normalize_assets(page_content: Tag, base_url: str, asset_urls: list[str], seen_assets: set[str]) -> None:
    for tag in page_content.find_all(ASSET_ATTRIBUTES.keys()):
        if tag.name == "link" and not _is_stylesheet_link(tag):
            continue

        attribute = ASSET_ATTRIBUTES[str(tag.name)]
        raw_url = tag.get(attribute)
        if not isinstance(raw_url, str):
            continue

        if _should_ignore_url(raw_url):
            tag.attrs.pop(attribute, None)
            continue

        normalized = normalize_url(base_url, raw_url)
        tag[attribute] = normalized
        if _has_non_downloadable_asset_scheme(normalized):
            continue

        _append_once(asset_urls, seen_assets, normalized)


def _normalize_links(
    page_content: Tag,
    base_url: str,
    manifest_slugs: set[str],
    internal_links: list[str],
    seen_internal: set[str],
    external_links: list[str],
    seen_external: set[str],
) -> None:
    for anchor in page_content.find_all("a"):
        raw_href = anchor.get("href")
        if not isinstance(raw_href, str):
            continue

        if _should_ignore_url(raw_href):
            anchor.attrs.pop("href", None)
            continue

        normalized = normalize_url(base_url, raw_href)
        anchor["href"] = normalized
        normalized_slug = slug_from_url(normalized)

        if normalized_slug in manifest_slugs:
            _append_once(internal_links, seen_internal, normalized)
            continue

        if _has_external_scheme(normalized):
            _append_once(external_links, seen_external, normalized)


def _is_unwanted_element(tag: Tag) -> bool:
    if tag.name in UNWANTED_TAGS:
        return True

    tag_id = str(tag.get("id", "")).lower()
    if tag_id in UNWANTED_IDS:
        return True

    classes = _class_tokens(tag)
    if classes & UNWANTED_CLASSES:
        return True

    if any(
        token.startswith("page-options") or token.startswith("page-rate-") or token.startswith("rate-box")
        for token in classes
    ):
        return True

    role = str(tag.get("role", "")).lower()
    return role == "navigation"


def _class_tokens(tag: Tag) -> set[str]:
    raw_classes = tag.get("class", [])
    if isinstance(raw_classes, str):
        return {raw_classes.lower()}
    if isinstance(raw_classes, Iterable):
        return {str(token).lower() for token in raw_classes}
    return set()


def _is_stylesheet_link(tag: Tag) -> bool:
    rel = tag.get("rel", [])
    if isinstance(rel, str):
        return "stylesheet" in rel.lower().split()
    if isinstance(rel, Iterable):
        return any(str(token).lower() == "stylesheet" for token in rel)
    return False


def _has_non_downloadable_asset_scheme(url: str) -> bool:
    return urlparse(url).scheme.lower() in NON_DOWNLOADABLE_ASSET_SCHEMES


def _sanitize_attributes(tag: Tag) -> None:
    for attribute in list(tag.attrs):
        lowered = attribute.lower()
        if lowered == "style" or lowered.startswith("on"):
            tag.attrs.pop(attribute, None)


def _should_ignore_url(raw_url: str) -> bool:
    stripped = raw_url.strip()
    if not stripped or stripped.startswith("#"):
        return True
    return urlparse(stripped).scheme.lower() == "javascript"


def _has_external_scheme(url: str) -> bool:
    scheme = urlparse(url).scheme.lower()
    return bool(scheme)


def _append_once(values: list[str], seen: set[str], value: str) -> None:
    if value in seen:
        return
    seen.add(value)
    values.append(value)
