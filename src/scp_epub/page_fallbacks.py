from __future__ import annotations

import hashlib
import json
import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .models import FetchResult, PageFallback


TRANSLATABLE_ATTRIBUTES = frozenset({"alt", "title", "aria-label"})
_CSS_CONTENT_RE = re.compile(
    r"(?<![-\w])(\bcontent\s*:\s*)(['\"])(.*?)(?<!\\)\2",
    flags=re.IGNORECASE | re.DOTALL,
)


def snapshot_layout_signature(html: str) -> str:
    """Return a stable signature for the structural parts of a page snapshot."""
    soup, page_content = _validated_snapshot(html)
    styles = [
        _CSS_CONTENT_RE.sub(
            lambda match: f"{match.group(1)}{match.group(2)}#translated{match.group(2)}",
            style.get_text(),
        )
        for style in soup.find_all("style")
    ]
    structure: list[object] = []
    _append_structure_tokens(page_content, structure)
    payload = {"styles": styles, "page_content": structure}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_fallback_fetch_result(slug: str, fallback: PageFallback) -> FetchResult:
    """Validate a stored fallback snapshot and describe it as a cache hit."""
    try:
        html = fallback.snapshot_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"fallback snapshot for {slug} is unreadable: {exc}") from exc

    signature = snapshot_layout_signature(html)
    if signature != fallback.layout_signature:
        raise ValueError(
            f"fallback snapshot layout signature mismatch for {slug}: "
            f"expected {fallback.layout_signature}, got {signature}"
        )

    return FetchResult(
        url=fallback.source_url,
        path=fallback.snapshot_path,
        metadata_path=fallback.snapshot_path,
        from_cache=True,
        status_code=200,
        content_type="text/html; charset=utf-8",
    )


def _validated_snapshot(html: str) -> tuple[BeautifulSoup, Tag]:
    soup = BeautifulSoup(html, "html.parser")
    page_contents = soup.select("#page-content")
    if len(page_contents) != 1:
        raise ValueError("fallback snapshot must contain exactly one #page-content")
    if soup.find("script") is not None:
        raise ValueError("fallback snapshot must not contain script elements")
    return soup, page_contents[0]


def _append_structure_tokens(node: Tag, tokens: list[object]) -> None:
    attributes: list[list[object]] = []
    for name, value in sorted(node.attrs.items()):
        if name in TRANSLATABLE_ATTRIBUTES:
            normalized_value: object = "#translated"
        elif isinstance(value, list):
            normalized_value = list(value)
        else:
            normalized_value = str(value)
        attributes.append([name, normalized_value])
    tokens.append(["open", node.name, attributes])

    for child in node.children:
        if isinstance(child, Tag):
            _append_structure_tokens(child, tokens)
        elif (
            isinstance(child, NavigableString)
            and not isinstance(child, Comment)
            and child.strip()
        ):
            tokens.append(["text"])

    tokens.append(["close", node.name])
