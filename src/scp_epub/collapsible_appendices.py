from __future__ import annotations

from dataclasses import dataclass
import re

from bs4 import BeautifulSoup, Tag

from .models import CollapsibleAppendixSpec


_FOLD_MARKER_RE = re.compile(r"^[+-]\s*")
_FOOTNOTE_REFERENCE_RE = re.compile(r"footnoteref-(\d+)\Z")
_FOOTNOTE_ID_RE = re.compile(r"footnote-(\d+)\Z")


@dataclass(frozen=True)
class ExtractedCollapsibleAppendix:
    spec: CollapsibleAppendixSpec
    html: str


@dataclass(frozen=True)
class CollapsibleAppendixExtraction:
    owner_html: str
    appendices: tuple[ExtractedCollapsibleAppendix, ...]


class CollapsibleAppendixExtractionError(ValueError):
    pass


def extract_collapsible_appendices(
    html: str,
    specs: tuple[CollapsibleAppendixSpec, ...],
) -> CollapsibleAppendixExtraction:
    soup = BeautifulSoup(html, "html.parser")
    page_content = soup.select_one("#page-content")
    if page_content is None:
        raise CollapsibleAppendixExtractionError("page is missing #page-content")

    matched = _match_blocks(page_content, specs)
    extracted: list[ExtractedCollapsibleAppendix] = []
    for spec, block in matched:
        content = block.select_one(".collapsible-block-content")
        if content is None:
            raise CollapsibleAppendixExtractionError(
                f"{spec.slug} ({spec.title}) is missing .collapsible-block-content"
            )
        footnotes = _take_referenced_footnotes(soup, content, spec)
        fragment_html = _fragment_html(soup, content, footnotes)
        replacement = soup.new_tag(
            "p",
            attrs={"class": "collapsible-appendix-title"},
        )
        replacement.string = spec.title
        block.replace_with(replacement)
        extracted.append(
            ExtractedCollapsibleAppendix(spec=spec, html=fragment_html)
        )

    _remove_empty_footnotes_container(soup)
    return CollapsibleAppendixExtraction(
        owner_html=str(soup),
        appendices=tuple(extracted),
    )


def _match_blocks(
    page_content: Tag,
    specs: tuple[CollapsibleAppendixSpec, ...],
) -> tuple[tuple[CollapsibleAppendixSpec, Tag], ...]:
    blocks_by_label: dict[str, list[Tag]] = {}
    for block in page_content.select(".collapsible-block"):
        folded = _direct_child_with_class(block, "collapsible-block-folded")
        if folded is None:
            continue
        link = folded.select_one(".collapsible-block-link")
        if link is None:
            continue
        label = _normalized_folded_label(link.get_text(" ", strip=True))
        blocks_by_label.setdefault(label, []).append(block)

    matched: list[tuple[CollapsibleAppendixSpec, Tag]] = []
    for spec in specs:
        expected = _normalized_visible_text(spec.match_text)
        blocks = blocks_by_label.get(expected, [])
        if len(blocks) != 1:
            raise CollapsibleAppendixExtractionError(
                f"{spec.slug} ({spec.title}) expected exactly one collapsible block, "
                f"found {len(blocks)}"
            )
        matched.append((spec, blocks[0]))
    return tuple(matched)


def _direct_child_with_class(tag: Tag, class_name: str) -> Tag | None:
    for child in tag.find_all(recursive=False):
        if isinstance(child, Tag) and class_name in child.get("class", []):
            return child
    return None


def _normalized_folded_label(value: str) -> str:
    return _FOLD_MARKER_RE.sub("", _normalized_visible_text(value), count=1)


def _normalized_visible_text(value: str) -> str:
    return " ".join(value.split())


def _take_referenced_footnotes(
    soup: BeautifulSoup,
    content: Tag,
    spec: CollapsibleAppendixSpec,
) -> tuple[str, ...]:
    footnote_numbers: list[str] = []
    seen_numbers: set[str] = set()
    for anchor in content.find_all("a", id=True):
        match = _FOOTNOTE_REFERENCE_RE.fullmatch(str(anchor["id"]))
        if match is None:
            continue
        number = match.group(1)
        if number not in seen_numbers:
            seen_numbers.add(number)
            footnote_numbers.append(number)

    footnotes: list[str] = []
    for number in footnote_numbers:
        footnote_id = f"footnote-{number}"
        matches = soup.find_all(id=footnote_id)
        if len(matches) != 1:
            raise CollapsibleAppendixExtractionError(
                f"{spec.slug} ({spec.title}) expected exactly one {footnote_id}, "
                f"found {len(matches)}"
            )
        footnote = matches[0]
        footnotes.append(str(footnote))
        footnote.decompose()
    return tuple(footnotes)


def _fragment_html(
    soup: BeautifulSoup,
    content: Tag,
    footnotes: tuple[str, ...],
) -> str:
    styles = "".join(str(style) for style in soup.find_all("style"))
    content_markup = "".join(str(child) for child in content.contents)
    footer_markup = ""
    if footnotes:
        footer_title = _footnotes_title(soup)
        footer_markup = (
            '<div class="footnotes-footer">'
            f'<div class="title">{footer_title}</div>'
            f'{"".join(footnotes)}'
            "</div>"
        )
    return (
        f"<html><head>{styles}</head><body><div id=\"page-content\">"
        f"{content_markup}{footer_markup}</div></body></html>"
    )


def _footnotes_title(soup: BeautifulSoup) -> str:
    for container in soup.select(".footnotes-footer"):
        title = _direct_child_with_class(container, "title")
        if title is not None:
            return title.get_text(" ", strip=True) or "脚注"
    return "脚注"


def _remove_empty_footnotes_container(soup: BeautifulSoup) -> None:
    for container in list(soup.select(".footnotes-footer")):
        title = _direct_child_with_class(container, "title")
        if title is None:
            continue
        direct_footnotes = [
            child
            for child in container.find_all(recursive=False)
            if isinstance(child, Tag)
            and _FOOTNOTE_ID_RE.fullmatch(str(child.get("id", ""))) is not None
        ]
        if not direct_footnotes:
            container.decompose()
