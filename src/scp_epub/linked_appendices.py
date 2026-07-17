from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from .cache import CacheStore
from .models import FetchResult, PageRef
from .urls import normalize_url, slug_from_url


LINKED_APPENDIX_GROUP_ROLE = "linked-appendix-group"
LINKED_APPENDIX_GROUP_TITLE = "原文附属文档"
LINKED_APPENDIX_ROLE = "linked-appendix"


@dataclass(frozen=True)
class LinkedAppendixCandidate:
    title: str
    url: str
    slug: str
    reason: str


@dataclass(frozen=True)
class LinkedAppendixDocument:
    entry: PageRef
    candidates: tuple[LinkedAppendixCandidate, ...]


DOCUMENT_TEXT_RE = re.compile(
    r"(附录|附件|补充|日志|记录|报告|文档|文件|档案|测试|实验|探索|探查|"
    r"访问|读取|资料|采访|访谈|回收|行动|任务|"
    r"log|test|document|addendum|appendix|interview|report|file|record|"
    r"exploration|mission)",
    re.IGNORECASE,
)
DOCUMENT_SLUG_RE = re.compile(
    r"(?:^|[-_/])("
    r"log|logs|test|tests|document|documents|addendum|appendix|interview|"
    r"report|file|files|record|records|exploration|mission|experiment|"
    r"incident|material|materials"
    r")(?:$|[-_/])",
    re.IGNORECASE,
)
PART_TEXT_RE = re.compile(
    r"^(part\s+[ivxlcdm0-9]+|第[一二三四五六七八九十0-9]+(?:部分|章|节|话)|"
    r"序幕|尾声|后记)$",
    re.IGNORECASE,
)
PROPOSAL_PATH_TEXT_RE = re.compile(r"^[^，。！？,.!?]{1,12}之[径路途]$")
PROPOSAL_PATH_SLUG_RE = re.compile(r"(?:^|[-_/])(path|trail|road)(?:$|[-_/])", re.IGNORECASE)
SCP_SLUG_RE = re.compile(r"^scp-(?P<number>\d{3,4})(?:$|[-_/])", re.IGNORECASE)

IGNORED_SLUGS = {
    "index",
    "licensing-guide",
    "most-recently-created",
    "system:page-tags",
}
IGNORED_PREFIXES = (
    "user:",
    "system:",
    "fragment:",
    "component:",
    "theme:",
    "nav:",
    "local--files",
    "forum",
    "category:",
)
IGNORED_PATH_PARTS = {
    "comments",
    "edit",
    "history",
    "local--files",
    "nav",
    "noredirect",
    "rate",
    "search",
    "system",
    "tag",
    "theme",
    "user",
}
IGNORED_CLASSES = {
    "author-box",
    "authorbox",
    "collapsible-block-link",
    "credit-button",
    "creditbutton",
    "creditrate",
    "footer-wikiwalk-nav",
    "interwiki",
    "license-area",
    "licensebox",
    "page-options-bottom",
    "page-rate-widget-box",
    "rate-box-with-credit-button",
    "scpnet-interwiki-wrapper",
    "u-author_block",
}
IGNORED_IDS = {"page-info", "page-options-bottom", "toc", "u-author_block"}


def scan_linked_appendices(
    manifest: list[PageRef],
    cache: CacheStore,
    base_url: str,
) -> list[LinkedAppendixDocument]:
    """Scan cached manifest pages for high-confidence linked appendices."""

    manifest_slugs = {entry.slug for entry in manifest}
    documents: list[LinkedAppendixDocument] = []

    for entry in manifest:
        page_path = cache.page_path(entry.slug)
        if not page_path.exists():
            continue

        candidates = _scan_page_html(
            entry,
            page_path.read_text(encoding="utf-8"),
            manifest_slugs,
            base_url,
        )
        if candidates:
            documents.append(LinkedAppendixDocument(entry=entry, candidates=tuple(candidates)))

    return documents


def scan_linked_appendices_from_fetch_results(
    manifest: list[PageRef],
    fetch_results: list[FetchResult],
    base_url: str,
) -> list[LinkedAppendixDocument]:
    manifest_slugs = {entry.slug for entry in manifest}
    documents: list[LinkedAppendixDocument] = []

    for entry, result in zip(manifest, fetch_results, strict=True):
        candidates = _scan_page_html(
            entry,
            result.path.read_text(encoding="utf-8"),
            manifest_slugs,
            base_url,
        )
        if candidates:
            documents.append(LinkedAppendixDocument(entry=entry, candidates=tuple(candidates)))

    return documents


def expand_manifest_with_linked_appendices(
    manifest: list[PageRef],
    documents: list[LinkedAppendixDocument],
) -> list[PageRef]:
    documents_by_slug = {
        document.entry.slug: document
        for document in documents
        if document.candidates
    }
    known_slugs = {entry.slug for entry in manifest}
    expanded: list[PageRef] = []

    for entry in manifest:
        expanded.append(entry)
        document = documents_by_slug.get(entry.slug)
        if document is None:
            continue

        group_slug = linked_appendix_group_slug(entry.slug)
        group_added = False
        for candidate in document.candidates:
            if candidate.slug in known_slugs:
                continue
            if not group_added:
                expanded.append(
                    PageRef(
                        title=LINKED_APPENDIX_GROUP_TITLE,
                        url=f"{entry.url}#linked-appendices",
                        slug=group_slug,
                        level=entry.level + 1,
                        role=LINKED_APPENDIX_GROUP_ROLE,
                        parent_slug=entry.slug,
                    )
                )
                known_slugs.add(group_slug)
                group_added = True
            expanded.append(
                PageRef(
                    title=candidate.title or candidate.slug,
                    url=candidate.url,
                    slug=candidate.slug,
                    level=entry.level + 2,
                    role=LINKED_APPENDIX_ROLE,
                    parent_slug=group_slug,
                )
            )
            known_slugs.add(candidate.slug)

    return [
        PageRef(
            title=entry.title,
            url=entry.url,
            slug=entry.slug,
            level=entry.level,
            role=entry.role,
            parent_slug=entry.parent_slug,
            source=entry.source,
            order=index,
            children=entry.children,
            tab_title=entry.tab_title,
        )
        for index, entry in enumerate(expanded, start=1)
    ]


def linked_appendix_group_slug(source_slug: str) -> str:
    return f"{source_slug}--linked-appendices"


def write_linked_appendix_report(
    documents: list[LinkedAppendixDocument],
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_documents_to_json(documents), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _scan_page_html(
    entry: PageRef,
    html: str,
    manifest_slugs: set[str],
    base_url: str,
) -> list[LinkedAppendixCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#page-content")
    if content is None:
        return []
    return _scan_content_links(entry, content, manifest_slugs, base_url)


def _scan_content_links(
    entry: PageRef,
    content: Tag,
    manifest_slugs: set[str],
    base_url: str,
) -> list[LinkedAppendixCandidate]:
    candidates: list[LinkedAppendixCandidate] = []
    seen_slugs: set[str] = set()

    for anchor in content.find_all("a", href=True):
        if not isinstance(anchor, Tag) or _is_in_ignored_container(anchor):
            continue

        resolved = _resolve_candidate_url(entry, anchor.get("href", ""), base_url)
        if resolved is None:
            continue
        url, slug = resolved
        if slug in seen_slugs or slug in manifest_slugs or slug == entry.slug:
            continue
        if _is_ignored_slug(slug):
            continue

        title = anchor.get_text(" ", strip=True)
        reason = _candidate_reason(entry, title, slug)
        if reason is None:
            continue

        seen_slugs.add(slug)
        candidates.append(
            LinkedAppendixCandidate(
                title=title,
                url=url,
                slug=slug,
                reason=reason,
            )
        )

    return candidates


def _resolve_candidate_url(entry: PageRef, href: str, base_url: str) -> tuple[str, str] | None:
    href = href.strip()
    if not href or href.startswith("#") or href.lower().startswith(
        ("data:", "javascript:", "mailto:", "tel:")
    ):
        return None

    url = normalize_url(entry.url or base_url, href)
    parsed_url = urlparse(url)
    parsed_base = urlparse(base_url)
    if parsed_url.netloc.lower() != parsed_base.netloc.lower():
        return None

    path_parts = {part.lower() for part in parsed_url.path.strip("/").split("/") if part}
    if path_parts & IGNORED_PATH_PARTS:
        return None

    return url, slug_from_url(url)


def _candidate_reason(entry: PageRef, title: str, slug: str) -> str | None:
    if _is_same_scp_branch(entry.slug, slug) and (
        DOCUMENT_TEXT_RE.search(title) or DOCUMENT_SLUG_RE.search(slug)
    ):
        return "same-scp-appendix"

    if DOCUMENT_TEXT_RE.search(title) and DOCUMENT_SLUG_RE.search(slug):
        return "document-like-link"

    if slug.startswith(f"{entry.slug}-") and PART_TEXT_RE.search(title):
        return "same-page-part"

    if (
        entry.role == "proposal"
        and PROPOSAL_PATH_TEXT_RE.search(title)
        and PROPOSAL_PATH_SLUG_RE.search(slug)
    ):
        return "proposal-path-link"

    return None


def _is_same_scp_branch(source_slug: str, target_slug: str) -> bool:
    source_match = SCP_SLUG_RE.match(source_slug)
    if source_match is None:
        return False
    number = source_match.group("number")
    return target_slug.lower().startswith(f"scp-{number}-")


def _is_ignored_slug(slug: str) -> bool:
    lowered = slug.lower()
    if lowered in IGNORED_SLUGS or lowered.startswith(IGNORED_PREFIXES):
        return True
    return any(part in IGNORED_PATH_PARTS for part in lowered.split("/"))


def _is_in_ignored_container(anchor: Tag) -> bool:
    current: Tag | None = anchor
    while isinstance(current, Tag):
        classes = current.get("class") or []
        if isinstance(classes, str):
            classes = classes.split()
        if {str(class_name).lower() for class_name in classes} & IGNORED_CLASSES:
            return True
        if str(current.get("id") or "").lower() in IGNORED_IDS:
            return True
        current = current.parent if isinstance(current.parent, Tag) else None
    return False


def _documents_to_json(documents: list[LinkedAppendixDocument]) -> list[dict[str, object]]:
    return [
        {
            "source_title": document.entry.title,
            "source_slug": document.entry.slug,
            "source_url": document.entry.url,
            "candidates": [
                {
                    "title": candidate.title,
                    "slug": candidate.slug,
                    "url": candidate.url,
                    "reason": candidate.reason,
                }
                for candidate in document.candidates
            ],
        }
        for document in documents
    ]
