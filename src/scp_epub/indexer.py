from __future__ import annotations

import re
import warnings
from collections.abc import Iterable

from bs4 import BeautifulSoup, FeatureNotFound, Tag

from .models import PageRef
from .urls import normalize_url, slug_from_url


HEADING_NAMES = frozenset(f"h{level}" for level in range(1, 7))
SECTION_RANGE_RE = re.compile(
    r"(?P<start>\d{1,3})\s*(?:到|至|-|--|—|–|~)\s*(?P<end>\d{1,3})"
)
SCP_RE = re.compile(r"^scp-\d{3}$", re.IGNORECASE)
SCP_001_PROPOSAL_RE = re.compile(r"(?<!\d)0*1(?!\d).*提案")


def parse_tales_index(html: str, base_url: str, start: int, end: int) -> list[PageRef]:
    if start > end:
        raise ValueError("start must be <= end")

    soup = _parse_html(html)
    content = soup.select_one("#page-content")
    if content is None:
        raise ValueError("Index page does not contain #page-content")

    entries: list[PageRef] = []
    for heading in content.find_all(HEADING_NAMES, recursive=False):
        title = heading.get_text(" ", strip=True)
        if not _section_matches(title, start, end):
            continue
        for sibling in _section_siblings(heading):
            if _is_heading(sibling) and _heading_level(sibling) <= _heading_level(heading):
                break
            entries.extend(_parse_lists(sibling, base_url, level=1, parent_slug=None))

    return [
        _with_order(entry, order)
        for order, entry in enumerate(entries, start=1)
    ]


def _parse_html(html: str) -> BeautifulSoup:
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"The 'strip_cdata' option of HTMLParser\(\).*",
                category=DeprecationWarning,
            )
            return BeautifulSoup(html, "lxml")
    except FeatureNotFound:
        return BeautifulSoup(html, "html.parser")


def _section_matches(title: str, start: int, end: int) -> bool:
    compact_title = re.sub(r"\s+", "", title)
    range_match = SECTION_RANGE_RE.search(compact_title)
    if range_match:
        section_start = int(range_match.group("start"))
        section_end = int(range_match.group("end"))
        return section_start <= end and start <= section_end

    return bool(SCP_001_PROPOSAL_RE.search(compact_title)) and start <= 1 <= end


def _section_siblings(heading: Tag) -> Iterable[Tag]:
    for sibling in heading.next_siblings:
        if isinstance(sibling, Tag):
            yield sibling


def _parse_lists(node: Tag, base_url: str, level: int, parent_slug: str | None) -> list[PageRef]:
    if node.name == "ul":
        return _parse_ul(node, base_url, level, parent_slug)

    entries: list[PageRef] = []
    for child_ul in node.find_all("ul", recursive=False):
        entries.extend(_parse_ul(child_ul, base_url, level, parent_slug))
    return entries


def _parse_ul(ul: Tag, base_url: str, level: int, parent_slug: str | None) -> list[PageRef]:
    entries: list[PageRef] = []
    for li in ul.find_all("li", recursive=False):
        anchor = _first_anchor(li)
        current_parent_slug = parent_slug
        if anchor is not None and _is_page_href(anchor["href"]):
            url = normalize_url(base_url, anchor["href"])
            slug = slug_from_url(url)
            entries.append(
                PageRef(
                    title=anchor.get_text(" ", strip=True) or slug,
                    url=url,
                    slug=slug,
                    level=level,
                    role=_role_for_slug(slug),
                    parent_slug=parent_slug,
                    source="tales-index",
                )
            )
            current_parent_slug = slug

        for child_ul in li.find_all("ul", recursive=False):
            entries.extend(_parse_ul(child_ul, base_url, level + 1, current_parent_slug))

    return entries


def _first_anchor(li: Tag) -> Tag | None:
    for child in li.children:
        if not isinstance(child, Tag):
            continue
        if child.name == "ul":
            continue
        if child.name == "a" and child.has_attr("href"):
            return child
        anchor = child.find("a", href=True)
        if anchor is not None:
            return anchor
    anchor = li.find("a", href=True, recursive=False)
    return anchor if isinstance(anchor, Tag) else None


def _is_page_href(href: str) -> bool:
    stripped = href.strip().lower()
    return bool(stripped) and stripped != "#" and not stripped.startswith("javascript:")


def _role_for_slug(slug: str) -> str:
    return "scp" if SCP_RE.match(slug) else "related"


def _with_order(entry: PageRef, order: int) -> PageRef:
    return PageRef(
        title=entry.title,
        url=entry.url,
        slug=entry.slug,
        level=entry.level,
        role=entry.role,
        parent_slug=entry.parent_slug,
        source=entry.source,
        order=order,
        children=entry.children,
    )


def _is_heading(tag: Tag) -> bool:
    return tag.name in HEADING_NAMES


def _heading_level(tag: Tag) -> int:
    if tag.name is None or not tag.name.startswith("h"):
        return 7
    return int(tag.name[1:])
