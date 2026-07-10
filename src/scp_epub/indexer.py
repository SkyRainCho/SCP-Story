from __future__ import annotations

import re
import warnings
from collections.abc import Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup, FeatureNotFound, Tag

from .models import PageRef
from .urls import normalize_url, slug_from_url


HEADING_NAMES = frozenset(f"h{level}" for level in range(1, 7))
SECTION_RANGE_RE = re.compile(
    r"(?:SCP[-\s]*)?(?P<start>\d{1,3})\s*"
    r"(?:到|至|--|—|–|-|~)\s*"
    r"(?:SCP[-\s]*)?(?P<end>\d{1,3})",
    re.IGNORECASE,
)
SCP_RE = re.compile(r"^scp-\d{3}$", re.IGNORECASE)
SCP_001_PROPOSAL_RE = re.compile(r"(?<!\d)0*1(?!\d).*提案")
SCP_001_PROPOSAL_SLUG_RE = re.compile(
    r"^(?:[a-z0-9][a-z0-9-]*:)?[a-z0-9][a-z0-9-]*"
    r"-proposal(?:-(?:[ivxlcdm]+|\d+))?$",
    re.IGNORECASE,
)
SCP_001_CODE_NAME_RE = re.compile(r"^代[号號]\s*[：:]?")
SCP_001_EXACT_IGNORED_CONTAINER_TOKENS = frozenset({"nav"})
SCP_001_IGNORED_CONTAINER_PARTS = frozenset(
    {
        "breadcrumbs",
        "edit",
        "footer",
        "page-options",
        "side-bar",
        "sidebar",
    }
)


def parse_tales_index(html: str, base_url: str, start: int, end: int) -> list[PageRef]:
    if start > end:
        raise ValueError("start must be <= end")

    soup = _parse_html(html)
    content = soup.select_one("#page-content")
    if content is None:
        raise ValueError("Index page does not contain #page-content")

    entries: list[PageRef] = []
    for heading in content.find_all(HEADING_NAMES):
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


def parse_scp001_proposals(html: str, base_url: str) -> list[PageRef]:
    soup = _parse_html(html)
    content = soup.select_one("#page-content")
    if content is None:
        raise ValueError("SCP-001 page does not contain #page-content")

    entries: list[PageRef] = []
    seen_slugs: set[str] = set()
    for anchor in content.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue
        if _is_ignored_scp001_anchor(anchor, content):
            continue

        href = anchor.get("href")
        if not isinstance(href, str) or not _is_scp001_page_href(href):
            continue

        url = normalize_url(base_url, href)
        if not _same_site_url(url, base_url):
            continue

        slug = slug_from_url(url)
        anchor_text = anchor.get_text(" ", strip=True)
        if slug in seen_slugs or not _is_scp001_proposal_link(slug, anchor_text):
            continue

        seen_slugs.add(slug)
        entries.append(
            PageRef(
                title=anchor_text or slug,
                url=url,
                slug=slug,
                level=2,
                role="proposal",
                parent_slug="scp-001",
                source="scp-001",
            )
        )

    return [_with_order(entry, order) for order, entry in enumerate(entries, start=1)]


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
        if anchor is not None and not _is_newpage_anchor(anchor) and _is_page_href(anchor["href"]):
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


def _is_scp001_page_href(href: str) -> bool:
    stripped = href.strip().lower()
    return (
        _is_page_href(stripped)
        and stripped != "#"
        and not stripped.startswith("#")
        and not stripped.startswith("data:")
        and not stripped.startswith("javascript:")
        and not stripped.startswith("mailto:")
        and not stripped.startswith("tel:")
    )


def _same_site_url(url: str, base_url: str) -> bool:
    parsed_url = urlparse(url)
    parsed_base = urlparse(base_url)
    if not parsed_url.netloc or not parsed_base.netloc:
        return True
    return parsed_url.netloc.lower() == parsed_base.netloc.lower()


def _is_scp001_proposal_slug(slug: str) -> bool:
    normalized_slug = slug.strip().lower()
    return normalized_slug != "scp-001" and bool(
        SCP_001_PROPOSAL_SLUG_RE.match(normalized_slug)
    )


def _is_scp001_proposal_link(slug: str, anchor_text: str) -> bool:
    normalized_slug = slug.strip().lower()
    if normalized_slug == "scp-001":
        return False
    return _is_scp001_proposal_slug(slug) or _is_scp001_code_name_text(anchor_text)


def _is_scp001_code_name_text(anchor_text: str) -> bool:
    return bool(SCP_001_CODE_NAME_RE.match(anchor_text.strip()))


def _is_newpage_anchor(anchor: Tag) -> bool:
    return "newpage" in _tag_class_tokens(anchor)


def _is_ignored_scp001_anchor(anchor: Tag, content: Tag) -> bool:
    if _is_newpage_anchor(anchor):
        return True

    for parent in anchor.parents:
        if parent is content:
            return False
        if not isinstance(parent, Tag):
            continue
        if parent.name == "nav":
            return True
        if _has_ignored_scp001_token(parent):
            return True
    return False


def _has_ignored_scp001_token(tag: Tag) -> bool:
    tokens = [str(tag.get("id", ""))]
    tokens.extend(_tag_class_tokens(tag))

    normalized_tokens = [token.lower() for token in tokens]
    if any(token in SCP_001_EXACT_IGNORED_CONTAINER_TOKENS for token in normalized_tokens):
        return True

    return any(
        ignored_part in token
        for token in normalized_tokens
        for ignored_part in SCP_001_IGNORED_CONTAINER_PARTS
    )


def _tag_class_tokens(tag: Tag) -> list[str]:
    classes = tag.get("class") or []
    if isinstance(classes, str):
        return classes.split()
    return [str(class_name) for class_name in classes]


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
