from __future__ import annotations

from html import escape
from urllib.parse import ParseResult, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from .models import PageRef
from .urls import normalize_url, slug_from_url


FACILITY_LINK_PREFIX = "安保设施档案："
APPENDIX_FACILITY_ROLE = "appendix-facility"
APPENDIX_TAB_ROLE = "appendix-tab"


def extract_facility_children(parent: PageRef, html: str, base_url: str) -> list[PageRef]:
    """Return direct facility dossier children explicitly labelled in ``html``."""

    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#page-content") or soup
    children: list[PageRef] = []
    seen_urls: set[str] = set()

    for anchor in content.find_all("a", href=True):
        title = anchor.get_text("", strip=True)
        if not title.startswith(FACILITY_LINK_PREFIX):
            continue

        url = _same_site_page_url(anchor.get("href", ""), base_url)
        if url is None or url in seen_urls:
            continue

        seen_urls.add(url)
        children.append(
            PageRef(
                title=title,
                url=url,
                slug=slug_from_url(url),
                level=parent.level + 1,
                role=APPENDIX_FACILITY_ROLE,
                parent_slug=parent.slug,
                source=parent.source,
            )
        )

    return children


def extract_tab_children(parent: PageRef, html: str) -> list[PageRef]:
    """Return one child entry for each direct panel of a direct Wikidot tabview."""

    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#page-content") or soup
    children: list[PageRef] = []

    for tabview in content.find_all("div", class_="yui-navset", recursive=False):
        nav = tabview.find("ul", class_="yui-nav", recursive=False)
        panel_container = tabview.find("div", class_="yui-content", recursive=False)
        if nav is None or panel_container is None:
            continue

        labels = _tab_labels(nav)
        panels = panel_container.find_all("div", recursive=False)
        for panel_index, _panel in enumerate(panels, start=1):
            tab_title = labels[panel_index - 1] if panel_index <= len(labels) else f"标签 {panel_index}"
            child_index = len(children) + 1
            children.append(
                PageRef(
                    title=tab_title,
                    url=parent.url,
                    slug=f"{parent.slug}--tab-{child_index}",
                    level=parent.level + 1,
                    role=APPENDIX_TAB_ROLE,
                    parent_slug=parent.slug,
                    source=parent.source,
                    tab_title=tab_title,
                )
            )

    return children


def appendix_group_html(entry: PageRef) -> str:
    """Build the minimal navigation-only page used for an appendix group."""

    title = escape(entry.title)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <meta charset="utf-8"/>
    <title>{title}</title>
  </head>
  <body>
    <h1>{title}</h1>
  </body>
</html>
'''


def _same_site_page_url(href: str, base_url: str) -> str | None:
    stripped = href.strip()
    if not stripped or stripped.startswith("#"):
        return None

    url = normalize_url(base_url, stripped)
    parsed_url = urlparse(url)
    parsed_base = urlparse(base_url)
    if parsed_url.scheme.lower() not in {"http", "https"}:
        return None
    if _normalized_authority(parsed_url) != _normalized_authority(parsed_base):
        return None
    if not parsed_url.path.strip("/"):
        return None

    slug = slug_from_url(url)
    return parsed_base._replace(
        scheme=parsed_base.scheme.lower(),
        netloc=parsed_base.netloc.lower(),
        path=f"/{slug}",
        params="",
        query="",
        fragment="",
    ).geturl()


def _tab_labels(nav: Tag | None) -> list[str]:
    if nav is None:
        return []

    labels: list[str] = []
    for index, item in enumerate(nav.find_all("li", recursive=False), start=1):
        labels.append(item.get_text(" ", strip=True) or f"标签 {index}")
    return labels


def _normalized_authority(parsed: ParseResult) -> tuple[str, int | None] | None:
    hostname = parsed.hostname
    if hostname is None:
        return None

    try:
        port = parsed.port
    except ValueError:
        return None

    default_port = {"http": 80, "https": 443}.get(parsed.scheme.lower())
    return hostname.lower(), None if port == default_port else port
