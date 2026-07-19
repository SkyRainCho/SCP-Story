from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html import escape
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from scp_epub.models import InlineDocumentSpec, PageRef, ProcessedPage
from scp_epub.urls import normalize_url, slug_from_url


NON_DOWNLOADABLE_ASSET_SCHEMES = {"data", "mailto", "tel"}
HEADING_NAMES = frozenset(f"h{level}" for level in range(1, 7))
INLINE_ANCHOR_BLOCK_TAGS = frozenset(
    {
        "article",
        "aside",
        "blockquote",
        "div",
        "dl",
        "figure",
        "footer",
        "header",
        *HEADING_NAMES,
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    }
)
UNWANTED_TAGS = {"script", "style", "iframe", "nav", "aside"}
SAFE_STYLE_PROPERTIES = {
    "background",
    "background-color",
    "border",
    "border-bottom",
    "border-collapse",
    "border-left",
    "border-radius",
    "border-right",
    "border-top",
    "box-shadow",
    "clear",
    "color",
    "float",
    "font-size",
    "font-style",
    "font-weight",
    "height",
    "margin",
    "margin-bottom",
    "margin-left",
    "margin-right",
    "margin-top",
    "max-height",
    "max-width",
    "min-height",
    "min-width",
    "opacity",
    "padding",
    "padding-bottom",
    "padding-left",
    "padding-right",
    "padding-top",
    "table-layout",
    "text-align",
    "text-decoration",
    "vertical-align",
    "width",
}
UNSAFE_STYLE_VALUE_TOKENS = ("behavior:", "expression(", "javascript:", "-moz-binding", "url(")
CSS_CODE_MARKERS = (
    "@import",
    ":root",
    "#page-content",
    "blankstyle css",
    "variables",
    "--logo-img",
)
CSS_CUSTOM_PROPERTY_RE = re.compile(r"--\s*[a-z0-9_-]+\s*:", re.IGNORECASE)
WIKIDOT_TEMPLATE_PLACEHOLDER_RE = re.compile(
    r"(?:\{\$[A-Za-z0-9_-]+\}|\\\{\\\$[A-Za-z0-9_-]+\\\})"
)
CSS_RULE_RE = re.compile(
    rf"(?P<selectors>[^{{}}@](?:{WIKIDOT_TEMPLATE_PLACEHOLDER_RE.pattern}|[^{{}}])*)"
    rf"\{{(?P<body>[^{{}}]*)\}}"
)
CSS_CONTENT_PROPERTY_RE = re.compile(
    r"""(?:^|;)\s*content\s*:\s*(?P<value>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*(?=;|$)""",
    re.IGNORECASE | re.DOTALL,
)
CSS_ESCAPED_CHAR_RE = re.compile(r"\\(?P<escape>[0-9a-fA-F]{1,6}\s?|.)", re.DOTALL)
CSS_PSEUDO_RE = re.compile(r"::?[a-zA-Z-]+(?:\([^)]*\))?")
CSS_CLASS_SELECTOR_RE = re.compile(r"\.([_a-zA-Z][-_a-zA-Z0-9]*)")
CSS_ID_SELECTOR_RE = re.compile(r"#([_a-zA-Z][-_a-zA-Z0-9]*)")
GENERATED_BEFORE_FONT_SIZE = "0.875em"
POSITIONED_GENERATED_BEFORE_STYLE = (
    "margin-top: -1.75em; margin-left: -0.5em; margin-bottom: 0.75em"
)
INTERACTIVE_ARTICLE_STYLE_SELECTOR_FRAGMENTS = (
    ".colmod-link",
    ".desktop-display",
    ".foldable-list-container",
    ".glitch-",
    ".hover",
    ".mobile-display",
    ".scptop-bg",
    ".t-real",
    ".unfolded",
)
INTERACTIVE_ARTICLE_EPUB_STYLE_RULES = (
    ".terminal .blockquote {background: #2b2b2b; color: #ededed; "
    "border: 1px dashed #ededed; margin: 1.5em auto; padding: 1em; max-width: 80%;}"
    "\n.declaration ul {list-style-type: square;}"
    "\n.glitch-body {font-size: 4em; line-height: 1.1; text-align: center; "
    "transform: rotate(-1deg); margin: 0.75em 0;}"
    "\n.glitch-stack span {font-weight: bold; text-shadow: -2px 3px 0 red, 2px -3px 0 #4d52ff;}"
)
UNSUPPORTED_PAGE_STYLE_SELECTOR_FRAGMENTS = (
    ".anom-bar",
    ".anom-bar-container",
    ".arrows",
    ".bottom-box",
    ".bottom-icon",
    ".class-category",
    ".class-text",
    ".clearance",
    ".collapsible-block-folded",
    ".collapsible-block-link",
    ".collapsible-block-unfolded",
    ".contain-class",
    ".danger-diamond",
    ".diamond-part",
    ".disrupt-class",
    ".left-icon",
    ".main-class",
    ".octagon",
    ".quadrants",
    ".right-icon",
    ".risk-class",
    ".second-class",
    ".text-part",
    ".top-box",
    ".top-center-box",
    ".top-icon",
    ".top-left-box",
    ".top-right-box",
    ".licensebox",
    ".wiki-content-table",
    "#page-content .collapsible-block",
)
UNSUPPORTED_PAGE_STYLE_SELECTORS = {
    "#page-content",
}
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
    "u-credit-view",
    "u-author_block",
}
UNWANTED_CLASSES = {
    "authorbox",
    "creditbutton",
    "creditbuttonstandalone",
    "creditbottomrate",
    "creditrate",
    "collapsible-block-unfolded-link",
    "footer-wikiwalk-nav",
    "info-container",
    "license-area",
    "licensebox",
    "modalbox",
    "modalcontainer",
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
    "translation_block",
    "u-faq",
}
FLOAT_CLEAR_TARGET_CLASSES = {
    "blockquote",
    "collapsible-block",
    "collapsible-block-content",
    "content-panel",
}
ASSET_ATTRIBUTES = {
    "img": "src",
    "source": "src",
    "link": "href",
    "object": "data",
}
GRID_TABLE_STYLE = (
    "width: 100%; border-collapse: collapse; table-layout: fixed; "
    "background-color: #21252E; color: #EDEDED; margin: 1em 0"
)
GRID_TABLE_HEADER_STYLE = (
    "border: solid 1px #ff1d45; background-color: #ff1d45; color: #21252E; "
    "padding: 0.625em; text-align: center; font-weight: bold; vertical-align: middle"
)
GRID_TABLE_CELL_STYLE = (
    "border: solid 1px #ff1d45; background-color: #21252E; color: #EDEDED; "
    "padding: 0.625em; vertical-align: middle"
)
SCENE_BREAK_IMAGE_STYLE = {
    "width": "96px",
    "max-width": "40%",
    "margin-left": "auto",
    "margin-right": "auto",
}

AUTHOR_WORK_LIST_LABELS = (
    "More From This Author",
    "More by this author",
    "该作者的更多作品",
)
SUBSTANTIVE_MEDIA_TAGS = ("audio", "figure", "img", "object", "picture", "svg", "table", "video")
TWO_LINK_TERMINAL_NAVIGATION_SLUGS = frozenset({"scp-7261", "scp-3662"})


@dataclass(frozen=True)
class PageTransformOptions:
    remove_terminal_navigation: bool = False
    remove_leading_metadata: bool = False
    remove_adult_content_warning: bool = False
    remove_author_work_list: bool = False
    layout_profile: str | None = None


@dataclass(frozen=True)
class LayoutProfileRule:
    apply: Callable[[Tag], None]
    style_rules: str


def transform_page(
    entry: PageRef,
    html: str,
    base_url: str,
    manifest_slugs: set[str] | None = None,
    *,
    include_tab_titles: set[str] | None = None,
    unwrap_single_included_tab: bool = False,
    background_asset_url: str | None = None,
    page_options: PageTransformOptions | None = None,
) -> ProcessedPage:
    soup = BeautifulSoup(html, "html.parser")
    page_content = soup.select_one("#page-content")
    if page_content is None and entry.role == "appendix-group":
        page_content = soup.body
        if page_content is not None:
            page_content["id"] = "page-content"
    if page_content is None:
        raise ValueError("missing #page-content")

    page_styles = _applicable_page_styles(soup, page_content)

    _remove_creator_information_blocks(page_content)

    for tag in list(page_content.find_all(_is_unwanted_element)):
        tag.decompose()

    profile_style_rules = _apply_page_cleanup_options(
        entry,
        page_content,
        page_options or PageTransformOptions(),
    )
    page_styles = _append_page_style_rules(page_styles, profile_style_rules)

    if _has_interactive_article_layout(page_content):
        _linearize_interactive_article_layout(page_content)
        page_styles = _linearize_interactive_article_styles(page_styles)
        page_styles = _append_page_style_rules(page_styles, INTERACTIVE_ARTICLE_EPUB_STYLE_RULES)

    _normalize_ruby_annotations(soup, page_content)
    page_styles = _materialize_generated_before_content(soup, page_content, page_styles)
    _convert_grid_tables(soup, page_content)
    _stabilize_float_layout(soup, page_content)
    _normalize_scene_break_images(page_content)
    if entry.slug != "scp-001":
        _expand_wikidot_tabs(
            soup,
            page_content,
            include_tab_titles=include_tab_titles,
            unwrap_single_included_tab=unwrap_single_included_tab,
        )

    asset_urls: list[str] = []
    seen_assets: set[str] = set()
    _apply_configured_background_asset(
        page_content,
        background_asset_url,
        asset_urls,
        seen_assets,
    )
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
    if page_styles:
        xhtml = f"<style>{escape(page_styles)}</style>\n{xhtml}"
    return ProcessedPage(
        entry=entry,
        xhtml=xhtml,
        asset_urls=tuple(asset_urls),
        internal_links=tuple(internal_links),
        external_links=tuple(external_links),
    )


def insert_inline_fragments(
    owner: ProcessedPage,
    fragments: Iterable[tuple[InlineDocumentSpec, ProcessedPage]],
) -> ProcessedPage:
    soup = BeautifulSoup(f"<root>{owner.xhtml}</root>", "html.parser")
    root = soup.find("root")
    if root is None:
        return owner

    after_anchors: dict[int, Tag] = {}
    before_anchors: dict[int, Tag] = {}
    assets = list(owner.asset_urls)
    internal_links = list(owner.internal_links)
    external_links = list(owner.external_links)
    seen_assets = set(assets)
    seen_internal = set(internal_links)
    seen_external = set(external_links)

    for spec, fragment in fragments:
        section = _inline_document_section(soup, spec, fragment.xhtml)
        anchor = _find_exact_visible_text(root, spec.anchor_text)
        if spec.position == "after_text" and anchor is not None:
            insertion_point = after_anchors.get(id(anchor), anchor)
            insertion_point.insert_after(section)
            after_anchors[id(anchor)] = section
        elif spec.position == "before_text" and anchor is not None:
            insertion_point = before_anchors.get(id(anchor))
            if insertion_point is None:
                anchor.insert_before(section)
            else:
                insertion_point.insert_after(section)
            before_anchors[id(anchor)] = section
        else:
            root.append(section)

        for value in fragment.asset_urls:
            _append_once(assets, seen_assets, value)
        for value in fragment.internal_links:
            _append_once(internal_links, seen_internal, value)
        for value in fragment.external_links:
            _append_once(external_links, seen_external, value)

    return ProcessedPage(
        entry=owner.entry,
        xhtml="".join(str(child) for child in root.contents).strip(),
        asset_urls=tuple(assets),
        internal_links=tuple(internal_links),
        external_links=tuple(external_links),
    )


def _inline_document_section(
    soup: BeautifulSoup,
    spec: InlineDocumentSpec,
    xhtml: str,
) -> Tag:
    section = soup.new_tag("section", attrs={"class": "inline-document-epub"})
    fragment_soup = BeautifulSoup(f"<root>{xhtml}</root>", "html.parser")
    fragment_root = fragment_soup.find("root")
    if fragment_root is not None:
        for style in fragment_root.find_all("style"):
            style.decompose()
        if fragment_root.find(("h1", "h2")) is None:
            heading = soup.new_tag("h2")
            heading.string = spec.title
            section.append(heading)
        for child in list(fragment_root.contents):
            section.append(child.extract())
    if section.find(_is_floated_image_block) is not None and not _last_child_clears_floats(
        section
    ):
        clearer = soup.new_tag("div")
        clearer["style"] = "clear: both"
        section.append(clearer)
    return section


def _find_exact_visible_text(root: Tag, anchor_text: str | None) -> Tag | None:
    if anchor_text is None:
        return None
    expected = _normalized_visible_text(anchor_text)
    for tag in root.find_all(True):
        if _normalized_visible_text(tag.get_text()) == expected:
            return _container_safe_inline_anchor(tag)
    return None


def _container_safe_inline_anchor(tag: Tag) -> Tag:
    footer = tag if "footnotes-footer" in _class_tokens(tag) else tag.find_parent(
        class_="footnotes-footer"
    )
    if isinstance(footer, Tag):
        return footer

    current: Tag | None = tag
    while current is not None:
        if current.name in INLINE_ANCHOR_BLOCK_TAGS:
            return current
        current = current.parent if isinstance(current.parent, Tag) else None
    return tag


def _normalized_visible_text(value: str) -> str:
    return " ".join(value.split())


def _apply_page_cleanup_options(
    entry: PageRef,
    page_content: Tag,
    options: PageTransformOptions,
) -> str:
    if options.remove_terminal_navigation:
        _remove_terminal_navigation(entry, page_content)
    if options.remove_leading_metadata and entry.slug == "scp-5464":
        _remove_scp_5464_leading_metadata(page_content)
    if options.remove_adult_content_warning and entry.slug == "scp-7069":
        _remove_scp_7069_adult_warning(page_content)
    if options.remove_author_work_list:
        _remove_terminal_author_work_list(page_content)

    layout_profile_rule = LAYOUT_PROFILE_RULES.get(options.layout_profile)
    if layout_profile_rule is None:
        return ""

    layout_profile_rule.apply(page_content)
    return layout_profile_rule.style_rules


def _remove_terminal_navigation(entry: PageRef, page_content: Tag) -> None:
    for block in _terminal_article_blocks(
        page_content,
        navigation_slug=entry.slug,
        allow_footnotes_footer_boundary=True,
    ):
        if _is_compact_guillemet_navigation(entry.slug, block) or (
            entry.slug == "scp-6781" and _is_scp_6781_previous_next_navigation(block)
        ):
            block.decompose()


def _terminal_article_blocks(
    page_content: Tag,
    *,
    navigation_slug: str | None = None,
    allow_footnotes_footer_boundary: bool = False,
) -> list[Tag]:
    return [
        block
        for block in page_content.find_all(("div", "section"))
        if _is_terminal_article_block(
            navigation_slug,
            block,
            page_content,
            allow_footnotes_footer_boundary=allow_footnotes_footer_boundary,
        )
    ]


def _is_terminal_article_block(
    navigation_slug: str | None,
    block: Tag,
    page_content: Tag,
    *,
    allow_footnotes_footer_boundary: bool = False,
) -> bool:
    current = block
    while current is not page_content:
        if _has_substantive_following_sibling(
            navigation_slug,
            current,
            allow_footnotes_footer_boundary=allow_footnotes_footer_boundary,
        ):
            return False
        parent = current.parent
        if not isinstance(parent, Tag):
            return False
        current = parent
    return True


def _has_substantive_following_sibling(
    navigation_slug: str | None,
    node: Tag,
    *,
    allow_footnotes_footer_boundary: bool = False,
) -> bool:
    for sibling in node.next_siblings:
        if isinstance(sibling, Tag):
            if allow_footnotes_footer_boundary and "footnotes-footer" in _class_tokens(sibling):
                continue
            if not _is_insignificant_trailing_node(navigation_slug, sibling):
                return True
        elif str(sibling).strip():
            return True
    return False


def _is_insignificant_trailing_node(navigation_slug: str | None, node: Tag) -> bool:
    if node.name in {"br", "hr"}:
        return True
    if navigation_slug == "scp-7261" and "earthworm" in _class_tokens(node):
        return True
    if node.name in SUBSTANTIVE_MEDIA_TAGS or node.find(SUBSTANTIVE_MEDIA_TAGS) is not None:
        return False
    text = node.get_text(" ", strip=True)
    if _looks_like_css_code(text):
        return True
    return not text


def _is_compact_guillemet_navigation(slug: str, block: Tag) -> bool:
    text = " ".join(block.get_text(" ", strip=True).split())
    link_count = len(block.find_all("a"))
    return (
        (link_count == 3 or (link_count == 2 and slug in TWO_LINK_TERMINAL_NAVIGATION_SLUGS))
        and len(text) <= 240
        and len(text) >= 2
        and text[0] in {"«", "‹"}
        and text[-1] in {"»", "›"}
    )


def _is_scp_6781_previous_next_navigation(block: Tag) -> bool:
    label_links = {
        node.get_text(" ", strip=True): node.find_parent("a")
        for node in block.find_all(True)
        if node.get_text(" ", strip=True) in {"前情", "后事"} and node.find_parent("a") is not None
    }
    return (
        set(label_links) == {"前情", "后事"}
        and len({id(link) for link in label_links.values()}) == 2
    )


def _remove_scp_5464_leading_metadata(page_content: Tag) -> None:
    for child in list(page_content.find_all(recursive=False)):
        if _is_scp_5464_setting_hub_breadcrumb(child) or _is_scp_5464_author_block(child):
            child.decompose()
            continue
        if _is_scp_5464_leading_template_or_empty_node(child):
            continue
        break


def _is_scp_5464_leading_template_or_empty_node(block: Tag) -> bool:
    text = block.get_text(" ", strip=True)
    return not text or _looks_like_css_code(text)


def _is_scp_5464_setting_hub_breadcrumb(block: Tag) -> bool:
    text = block.get_text(" ", strip=True)
    links = block.find_all("a", href=True)
    return (
        block.name in {"div", "p"}
        and "设定" in text
        and bool(links)
        and any("hub" in str(link.get("href", "")).lower() for link in links)
    )


def _is_scp_5464_author_block(block: Tag) -> bool:
    return block.name in {"div", "p"} and block.get_text(" ", strip=True).startswith(("作者：", "作者:"))


def _remove_scp_7069_adult_warning(page_content: Tag) -> None:
    for warning in list(page_content.select("#u-adult-warning")):
        warning.decompose()


def _remove_terminal_author_work_list(page_content: Tag) -> None:
    _remove_folded_author_work_lists(page_content)
    _remove_nested_author_work_links(page_content)

    for block in _terminal_article_blocks(page_content):
        text = block.get_text(" ", strip=True)
        if _starts_with_author_work_list_label(text):
            block.decompose()


def _remove_folded_author_work_lists(page_content: Tag) -> None:
    for heading in list(page_content.select(".collapsible-block-folded")):
        if not _is_author_work_list_label(heading.get_text(" ", strip=True)):
            continue
        work_list = heading.find_parent(class_="collapsible-block")
        if isinstance(work_list, Tag):
            work_list.decompose()


def _remove_nested_author_work_links(page_content: Tag) -> None:
    for link in list(page_content.find_all("a")):
        if not _is_author_work_list_label(link.get_text(" ", strip=True)):
            continue
        logical_link_wrapper = link.find_parent(class_="logical-link-wrap")
        if not isinstance(logical_link_wrapper, Tag) or not _is_terminal_article_block(
            None,
            logical_link_wrapper,
            page_content,
        ):
            continue
        layout_block = _nearest_standalone_layout_block(link, page_content)
        if layout_block is not None and _is_standalone_layout_wrapper(layout_block):
            layout_block.decompose()
        else:
            logical_link_wrapper.decompose()


def _nearest_standalone_layout_block(tag: Tag, page_content: Tag) -> Tag | None:
    current = tag.parent
    while isinstance(current, Tag) and current is not page_content:
        if current.name in {"div", "section"}:
            return current
        current = current.parent
    return None


def _is_standalone_layout_wrapper(block: Tag) -> bool:
    style = str(block.get("style", "")).lower()
    return block.name in {"div", "section"} and "text-align" in style


def _is_author_work_list_label(text: str) -> bool:
    normalized_text = _normalized_visible_text(text)
    return normalized_text in AUTHOR_WORK_LIST_LABELS


def _starts_with_author_work_list_label(text: str) -> bool:
    normalized_text = _normalized_visible_text(text)
    for label in AUTHOR_WORK_LIST_LABELS:
        if normalized_text == label:
            return True
        if (
            normalized_text.startswith(label)
            and len(normalized_text) > len(label)
            and normalized_text[len(label)].isspace()
        ):
            return True
    return False


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

    if _is_hidden_css_code_container(tag) or _is_hidden_scp_image_container(tag) or _is_css_code_collapsible(tag):
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


def _is_hidden_css_code_container(tag: Tag) -> bool:
    if not _is_hidden_by_style(tag):
        return False
    return _contains_code_block(tag) and _looks_like_css_code(tag.get_text("\n", strip=True))


def _is_hidden_scp_image_container(tag: Tag) -> bool:
    if not _is_hidden_by_style(tag):
        return False
    classes = _class_tokens(tag)
    if "collapsible-block-unfolded" in classes:
        return False
    if _is_inside_wikidot_tab_content(tag):
        return False
    return tag.find(class_="scp-image-block") is not None


def _is_inside_wikidot_tab_content(tag: Tag) -> bool:
    return tag.find_parent("div", class_="yui-content") is not None


def _is_css_code_collapsible(tag: Tag) -> bool:
    classes = _class_tokens(tag)
    if "collapsible-block" not in classes:
        return False
    link_text = " ".join(
        link.get_text(" ", strip=True).replace("\xa0", " ")
        for link in tag.select(".collapsible-block-link")
    ).upper()
    if "CODE" not in link_text:
        return False
    return _contains_code_block(tag) and _looks_like_css_code(tag.get_text("\n", strip=True))


def _has_interactive_article_layout(page_content: Tag) -> bool:
    return page_content.select_one(".terminal.t-real") is not None and (
        page_content.select_one(".foldable-list-container") is not None
        or page_content.select_one(".colmod-content") is not None
    )


def _linearize_interactive_article_layout(page_content: Tag) -> None:
    for control in list(page_content.select(".foldable-list-container")):
        control.decompose()

    for mobile_display in list(page_content.select(".mobile-display")):
        mobile_display.decompose()

    for terminal in page_content.select(".terminal.t-real"):
        _remove_class_token(terminal, "t-real")

    for marker in list(page_content.find_all("li")):
        if marker.get_text(" ", strip=True) == "_":
            marker.decompose()

    for empty_container in list(page_content.select(".colmod-link-top, ul")):
        if not empty_container.get_text(" ", strip=True) and not empty_container.find("img"):
            empty_container.decompose()

    for stack in page_content.select(".glitch-stack"):
        spans = stack.find_all("span", recursive=False)
        texts = [span.get_text(strip=True) for span in spans if span.get_text(strip=True)]
        if not spans or len(set(texts)) != 1:
            continue
        for span in spans[1:]:
            span.decompose()


def _linearize_interactive_article_styles(page_styles: str) -> str:
    rules: list[str] = []
    for match in CSS_RULE_RE.finditer(page_styles):
        selectors = [selector.strip() for selector in match.group("selectors").split(",") if selector.strip()]
        kept_selectors = [
            selector
            for selector in selectors
            if not _is_interactive_article_layout_selector(selector)
        ]
        if kept_selectors:
            rules.append(f"{', '.join(kept_selectors)} {{{match.group('body').strip()}}}")
    return "\n".join(rules)


def _append_page_style_rules(page_styles: str, extra_rules: str) -> str:
    if not page_styles:
        return extra_rules
    return f"{page_styles}\n{extra_rules}"


def _normalize_ruby_annotations(soup: BeautifulSoup, page_content: Tag) -> None:
    for ruby_span in list(page_content.select("span.ruby")):
        rt_span = ruby_span.find("span", class_="rt", recursive=False)
        if rt_span is None:
            continue

        ruby = soup.new_tag("ruby")
        rt = soup.new_tag("rt")
        rt.string = rt_span.get_text("", strip=True)

        for child in list(ruby_span.contents):
            if child is rt_span:
                continue
            ruby.append(child.extract() if isinstance(child, Tag) else child)
        ruby.append(rt)
        ruby_span.replace_with(ruby)


def _is_interactive_article_layout_selector(selector: str) -> bool:
    lowered = selector.lower()
    return any(fragment in lowered for fragment in INTERACTIVE_ARTICLE_STYLE_SELECTOR_FRAGMENTS)


def _remove_class_token(tag: Tag, class_name: str) -> None:
    classes = tag.get("class", [])
    if isinstance(classes, str):
        tokens = classes.split()
    elif isinstance(classes, Iterable):
        tokens = [str(token) for token in classes]
    else:
        return

    remaining = [token for token in tokens if token.lower() != class_name.lower()]
    if remaining:
        tag["class"] = remaining
    else:
        tag.attrs.pop("class", None)


def _is_hidden_by_style(tag: Tag) -> bool:
    style = tag.get("style")
    return isinstance(style, str) and "display" in style.lower() and "none" in style.lower()


def _contains_code_block(tag: Tag) -> bool:
    return tag.find("pre") is not None or tag.find(class_="code") is not None


def _looks_like_css_code(text: str) -> bool:
    normalized = text.lower()
    hits = sum(1 for marker in CSS_CODE_MARKERS if marker in normalized)
    if hits >= 2:
        return True
    if CSS_RULE_RE.search(normalized) and (
        "#page-content" in normalized or ".collapsible-block" in normalized
    ):
        return True

    custom_property_hits = len(CSS_CUSTOM_PROPERTY_RE.findall(normalized))
    return ":root" in normalized and custom_property_hits >= 2


def _applicable_page_styles(soup: BeautifulSoup, page_content: Tag) -> str:
    rules: list[str] = []
    seen_rules: set[str] = set()
    targets = _page_style_targets(page_content)

    for style in soup.find_all("style"):
        for rule in _matching_css_rules(style.get_text("\n", strip=True), targets):
            if rule in seen_rules:
                continue
            seen_rules.add(rule)
            rules.append(rule)

    return "\n".join(rules)


def _matching_css_rules(css_text: str, targets: tuple[set[str], set[str]]) -> list[str]:
    rules: list[str] = []
    for match in CSS_RULE_RE.finditer(css_text):
        selector_text = re.sub(r"\s+", " ", match.group("selectors")).strip()
        body = match.group("body").strip()
        if not selector_text or not body:
            continue
        selectors = [selector.strip() for selector in selector_text.split(",") if selector.strip()]
        supported_selectors = [
            selector
            for selector in selectors
            if not WIKIDOT_TEMPLATE_PLACEHOLDER_RE.search(selector)
            and not _is_unsupported_page_style_selector(selector)
        ]
        matching_selectors = [
            selector
            for selector in supported_selectors
            if _selector_targets_page_content(selector, targets)
        ]
        if matching_selectors:
            rules.append(f"{', '.join(matching_selectors)} {{{body}}}")
    return rules


def _is_unsupported_page_style_selector(selector: str) -> bool:
    lowered = selector.lower()
    return (
        lowered in UNSUPPORTED_PAGE_STYLE_SELECTORS
        or any(fragment in lowered for fragment in UNSUPPORTED_PAGE_STYLE_SELECTOR_FRAGMENTS)
    )


def _remove_creator_information_blocks(page_content: Tag) -> None:
    for paragraph in list(page_content.find_all("p")):
        if _normalized_text(paragraph) not in {"创作者信息", "作者信息"}:
            continue

        previous = paragraph.previous_sibling
        while previous is not None and not isinstance(previous, Tag):
            previous = previous.previous_sibling
        if isinstance(previous, Tag) and previous.name == "hr":
            previous.decompose()

        for sibling in [paragraph, *_creator_information_siblings(paragraph)]:
            sibling.decompose()


def _creator_information_siblings(marker: Tag) -> list[Tag]:
    removable: list[Tag] = []
    for sibling in marker.next_siblings:
        if not isinstance(sibling, Tag):
            continue
        if _is_creator_information_boundary(sibling):
            break
        removable.append(sibling)
    return removable


def _is_creator_information_boundary(tag: Tag) -> bool:
    if tag.name in HEADING_NAMES:
        return True
    classes = _class_tokens(tag)
    return "footer-wikiwalk-nav" in classes or bool(classes & UNWANTED_CLASSES)


def _normalized_text(tag: Tag) -> str:
    return re.sub(r"\s+", "", tag.get_text(" ", strip=True))


def _materialize_generated_before_content(
    soup: BeautifulSoup,
    page_content: Tag,
    page_styles: str,
) -> str:
    generated_labels: dict[int, dict[str, str | Tag | None]] = {}
    generated_order: list[int] = []
    materialized_rule_spans: list[tuple[int, int]] = []

    for match in CSS_RULE_RE.finditer(page_styles):
        content_value = _css_content_value(match.group("body"))
        label_style = _sanitize_style_value(_style_without_content(match.group("body")))
        selectors = [
            selector.strip()
            for selector in match.group("selectors").split(",")
            if "::before" in selector.lower()
        ]
        rule_was_materialized = False

        for selector in selectors:
            base_selector = CSS_PSEUDO_RE.sub("", selector).strip()
            if base_selector.startswith("#page-content "):
                base_selector = base_selector[len("#page-content ") :].strip()
            if not base_selector or not _is_supported_generated_before_selector(base_selector):
                continue

            for target in page_content.select(base_selector):
                target_id = id(target)
                if target_id not in generated_labels:
                    generated_labels[target_id] = {
                        "target": target,
                        "content": None,
                        "style": "",
                        "positioned": False,
                    }
                    generated_order.append(target_id)

                state = generated_labels[target_id]
                if content_value is not None:
                    state["content"] = content_value
                if label_style:
                    state["style"] = _merge_style_values(str(state["style"] or ""), label_style)
                if _is_positioned_generated_before_rule(match.group("body")):
                    state["positioned"] = True
                rule_was_materialized = True

        if rule_was_materialized and selectors:
            materialized_rule_spans.append(match.span())

    for target_id in generated_order:
        state = generated_labels[target_id]
        target = state["target"]
        content = state["content"]
        if not isinstance(target, Tag) or not isinstance(content, str) or not content.strip():
            continue
        if target.find(class_="generated-before", recursive=False) is not None:
            continue

        is_positioned = bool(state["positioned"])
        label = soup.new_tag("div" if is_positioned else "span")
        label["class"] = "generated-before"
        label_style = state["style"]
        if is_positioned:
            label["style"] = POSITIONED_GENERATED_BEFORE_STYLE
            badge = soup.new_tag("span")
            badge["class"] = "generated-before-label"
            if isinstance(label_style, str) and label_style:
                badge["style"] = _normalize_generated_before_style(label_style)
            badge.string = content
            label.append(badge)
        else:
            if isinstance(label_style, str) and label_style:
                label["style"] = _normalize_generated_before_style(label_style)
            label.string = content
        target.insert(0, label)

    return _remove_css_rule_spans(page_styles, materialized_rule_spans)


def _is_supported_generated_before_selector(selector: str) -> bool:
    if any(token in selector for token in ("+", "~", "*", "[", "]", "(", ")", ":")):
        return False

    parts = [part.strip() for part in selector.split(">")]
    return all(part and re.search(r"\s", part) is None for part in parts)


def _merge_style_values(base_style: str, override_style: str) -> str:
    properties: list[str] = []
    values: dict[str, str] = {}

    for style in (base_style, override_style):
        for declaration in style.split(";"):
            property_name, separator, raw_value = declaration.partition(":")
            if not separator:
                continue

            normalized_property = property_name.strip().lower()
            value = raw_value.strip()
            if not normalized_property or not value:
                continue
            if normalized_property not in values:
                properties.append(normalized_property)
            values[normalized_property] = value

    return "; ".join(f"{property_name}: {values[property_name]}" for property_name in properties)


def _is_positioned_generated_before_rule(style_body: str) -> bool:
    lowered = style_body.lower()
    return "position" in lowered and "absolute" in lowered


def _normalize_generated_before_style(style: str) -> str:
    declarations: list[str] = []
    for raw_declaration in style.split(";"):
        property_name, separator, raw_value = raw_declaration.partition(":")
        if not separator:
            continue

        normalized_property = property_name.strip().lower()
        value = raw_value.strip()
        if not normalized_property or not value:
            continue
        if normalized_property == "font-size" and _is_viewport_dependent_font_size(value):
            value = GENERATED_BEFORE_FONT_SIZE
        declarations.append(f"{normalized_property}: {value}")

    return "; ".join(declarations)


def _is_viewport_dependent_font_size(value: str) -> bool:
    lowered = value.lower()
    return "calc(" in lowered or "vw" in lowered


def _remove_css_rule_spans(css_text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return css_text

    chunks: list[str] = []
    cursor = 0
    for start, end in spans:
        chunks.append(css_text[cursor:start])
        cursor = end
    chunks.append(css_text[cursor:])

    return "\n".join(line for line in "".join(chunks).splitlines() if line.strip())


def _convert_grid_tables(soup: BeautifulSoup, page_content: Tag) -> None:
    for grid_table in list(page_content.select(".grid-table")):
        cells = [child for child in grid_table.find_all(recursive=False) if isinstance(child, Tag)]
        if len(cells) < 3 or not all("title" in _class_tokens(cell) for cell in cells[:3]):
            continue

        table = soup.new_tag("table")
        table["class"] = "grid-table-epub"
        table["style"] = GRID_TABLE_STYLE

        header_row = soup.new_tag("tr")
        for cell in cells[:3]:
            header = soup.new_tag("th")
            header["style"] = GRID_TABLE_HEADER_STYLE
            _move_children(cell, header)
            header_row.append(header)
        table.append(header_row)

        for index in range(3, len(cells), 3):
            row = soup.new_tag("tr")
            for cell in cells[index : index + 3]:
                table_cell = soup.new_tag("td")
                table_cell["style"] = GRID_TABLE_CELL_STYLE
                _move_children(cell, table_cell)
                row.append(table_cell)
            table.append(row)

        grid_table.replace_with(table)


def _move_children(source: Tag, destination: Tag) -> None:
    for child in list(source.contents):
        destination.append(child.extract())


def _stabilize_float_layout(soup: BeautifulSoup, page_content: Tag) -> None:
    for tag in page_content.find_all(True):
        if _should_clear_before_float_sensitive_block(tag):
            _append_style_declaration(tag, "clear", "both")

    for image_block in page_content.find_all(_is_floated_image_block):
        container = image_block.parent
        if not isinstance(container, Tag) or container is page_content:
            continue
        if _last_child_clears_floats(container):
            continue
        clearer = soup.new_tag("div")
        clearer["style"] = "clear: both"
        container.append(clearer)


def _normalize_scene_break_images(page_content: Tag) -> None:
    for image in page_content.find_all("img"):
        if "scene-break" not in _class_tokens(image):
            continue

        for property_name, value in SCENE_BREAK_IMAGE_STYLE.items():
            _append_style_declaration(image, property_name, value)

        parent = image.parent
        if isinstance(parent, Tag) and "image-container" in _class_tokens(parent):
            _append_style_declaration(parent, "text-align", "center")


def _expand_wikidot_tabs(
    soup: BeautifulSoup,
    page_content: Tag,
    *,
    include_tab_titles: set[str] | None = None,
    unwrap_single_included_tab: bool = False,
) -> None:
    normalized_include_titles = {
        _normalize_tab_label(label)
        for label in include_tab_titles or set()
    }
    for tabview in list(page_content.select("div.yui-navset")):
        nav = tabview.find("ul", class_="yui-nav", recursive=False)
        content = tabview.find("div", class_="yui-content", recursive=False)
        if nav is None or content is None:
            continue

        labels = _tab_labels(nav)
        panels = [child for child in content.find_all(recursive=False) if isinstance(child, Tag)]
        if not labels or not panels:
            continue

        expanded = soup.new_tag("div")
        expanded["class"] = "tabview-epub"

        for index, panel in enumerate(panels):
            label = labels[index] if index < len(labels) else f"标签 {index + 1}"
            if normalized_include_titles and _normalize_tab_label(label) not in normalized_include_titles:
                continue
            section = soup.new_tag("section")
            section["class"] = "tabview-panel-epub"

            heading = soup.new_tag("h3")
            heading["class"] = "tabview-panel-title"
            heading.string = f"标签：{label}"
            section.append(heading)

            _move_children(panel, section)
            expanded.append(section)

        sections = expanded.find_all("section", class_="tabview-panel-epub", recursive=False)
        if unwrap_single_included_tab and len(sections) == 1:
            heading = sections[0].find("h3", class_="tabview-panel-title", recursive=False)
            if heading is not None:
                heading.decompose()
            tabview.replace_with(sections[0])
            sections[0].unwrap()
            continue

        tabview.replace_with(expanded)


def _apply_configured_background_asset(
    page_content: Tag,
    background_asset_url: str | None,
    asset_urls: list[str],
    seen_assets: set[str],
) -> None:
    if not background_asset_url:
        return

    panel = page_content.find(class_="content-panel")
    if panel is None:
        return

    panel["data-epub-background-url"] = background_asset_url
    if background_asset_url not in seen_assets:
        seen_assets.add(background_asset_url)
        asset_urls.append(background_asset_url)


def _tab_labels(nav: Tag) -> list[str]:
    labels: list[str] = []
    for item in nav.find_all("li", recursive=False):
        label = item.get_text(" ", strip=True)
        labels.append(label or f"标签 {len(labels) + 1}")
    return labels


def _normalize_tab_label(label: str) -> str:
    return re.sub(r"\s+", "", label)


def _should_clear_before_float_sensitive_block(tag: Tag) -> bool:
    if tag.name == "blockquote":
        return True

    classes = _class_tokens(tag)
    if classes & FLOAT_CLEAR_TARGET_CLASSES:
        return True

    style = tag.get("style")
    if tag.name == "div" and isinstance(style, str):
        lowered = style.lower()
        return "border" in lowered and "dashed" in lowered

    return False


def _append_style_declaration(tag: Tag, property_name: str, value: str) -> None:
    style = str(tag.get("style", "")).strip()
    declarations = [declaration.strip() for declaration in style.split(";") if declaration.strip()]
    normalized_property = property_name.lower()
    declarations = [
        declaration
        for declaration in declarations
        if declaration.partition(":")[0].strip().lower() != normalized_property
    ]
    declarations.append(f"{property_name}: {value}")
    tag["style"] = "; ".join(declarations)


def _is_floated_image_block(tag: Tag) -> bool:
    if tag.name != "div":
        return False
    classes = _class_tokens(tag)
    return "scp-image-block" in classes and bool(classes & {"block-left", "block-right"})


def _last_child_clears_floats(tag: Tag) -> bool:
    for child in reversed(tag.contents):
        if not isinstance(child, Tag):
            if str(child).strip():
                return False
            continue
        if _is_floated_image_block(child):
            return False
        style = child.get("style")
        return isinstance(style, str) and "clear" in style.lower() and "both" in style.lower()
    return False


def _apply_scp_6183_layout_profile(page_content: Tag) -> None:
    for image_block in page_content.select("table .scp-image-block"):
        _stabilize_profile_image_block(
            image_block,
            "layout-profile-scp-6183-table-image",
        )


def _apply_scp_4612_layout_profile(page_content: Tag) -> None:
    for image_block in page_content.select(".scp-image-block.block-right"):
        _stabilize_profile_image_block(
            image_block,
            "layout-profile-scp-4612-image",
        )


def _apply_scp_6599_layout_profile(page_content: Tag) -> None:
    for reddit_body in page_content.select(".reddit-post > div"):
        if not _is_fixed_width_right_float(reddit_body):
            continue
        _add_class_token(reddit_body, "layout-profile-scp-6599-reddit-body")
        _append_style_declaration(reddit_body, "float", "none")
        _append_style_declaration(reddit_body, "width", "auto")
        _append_style_declaration(reddit_body, "max-width", "100%")
        _append_style_declaration(reddit_body, "clear", "both")

    for image_block in page_content.select(".scp-image-block.block-center"):
        if not _is_scp_6599_fixed_width_media(image_block):
            continue
        _stabilize_profile_image_block(
            image_block,
            "layout-profile-scp-6599-inline-media",
        )
        _append_style_declaration(image_block, "width", "100%")


def _stabilize_profile_image_block(image_block: Tag, class_name: str) -> None:
    _add_class_token(image_block, class_name)
    _append_style_declaration(image_block, "float", "none")
    _append_style_declaration(image_block, "clear", "both")
    _append_style_declaration(image_block, "max-width", "100%")
    for image in image_block.find_all("img"):
        _append_style_declaration(image, "max-width", "100%")
        _append_style_declaration(image, "height", "auto")


def _is_fixed_width_right_float(tag: Tag) -> bool:
    return (
        _style_property_value(tag, "float") == "right"
        and _style_property_value(tag, "width") == "93.5%"
    )


def _is_scp_6599_fixed_width_media(image_block: Tag) -> bool:
    return _style_property_value(image_block, "width") == "100px" and any(
        _style_property_value(image, "width") == "300px"
        for image in image_block.find_all("img")
    )


def _style_property_value(tag: Tag, property_name: str) -> str | None:
    style = tag.get("style")
    if not isinstance(style, str):
        return None
    normalized_property = property_name.lower()
    for declaration in style.split(";"):
        name, separator, value = declaration.partition(":")
        if separator and name.strip().lower() == normalized_property:
            return value.strip().lower()
    return None


def _add_class_token(tag: Tag, class_name: str) -> None:
    classes = list(tag.get("class", []))
    if class_name not in classes:
        classes.append(class_name)
    tag["class"] = classes


LAYOUT_PROFILE_RULES: dict[str, LayoutProfileRule] = {
    "scp-6183": LayoutProfileRule(
        apply=_apply_scp_6183_layout_profile,
        style_rules=(
            ".layout-profile-scp-6183-table-image {float: none; clear: both; max-width: 100%;}"
            "\n.layout-profile-scp-6183-table-image img {max-width: 100%; height: auto;}"
        ),
    ),
    "scp-4612": LayoutProfileRule(
        apply=_apply_scp_4612_layout_profile,
        style_rules=(
            ".layout-profile-scp-4612-image {float: none; clear: both; max-width: 100%;}"
            "\n.layout-profile-scp-4612-image img {max-width: 100%; height: auto;}"
        ),
    ),
    "scp-6599": LayoutProfileRule(
        apply=_apply_scp_6599_layout_profile,
        style_rules=(
            ".layout-profile-scp-6599-reddit-body {float: none; clear: both; width: auto; max-width: 100%;}"
            "\n.layout-profile-scp-6599-inline-media {float: none; clear: both; max-width: 100%;}"
            "\n.layout-profile-scp-6599-inline-media img {max-width: 100%; height: auto;}"
        ),
    ),
}


def _css_content_value(style_body: str) -> str | None:
    match = CSS_CONTENT_PROPERTY_RE.search(style_body)
    if match is None:
        return None

    return _decode_css_string(match.group("value"))


def _decode_css_string(value: str) -> str:
    text = value[1:-1]

    def replace_escape(match: re.Match[str]) -> str:
        escaped = match.group("escape")
        stripped = escaped.strip()
        if stripped and all(char in "0123456789abcdefABCDEF" for char in stripped):
            return chr(int(stripped, 16))
        return escaped

    return CSS_ESCAPED_CHAR_RE.sub(replace_escape, text)


def _style_without_content(style_body: str) -> str:
    declarations = [
        declaration.strip()
        for declaration in style_body.split(";")
        if not declaration.strip().lower().startswith("content:")
    ]
    return "; ".join(declarations)


def _selector_targets_page_content(selector: str, targets: tuple[set[str], set[str]]) -> bool:
    page_classes, page_ids = targets
    simplified = CSS_PSEUDO_RE.sub("", selector).strip()
    if not simplified:
        return False

    selector_classes = {token.lower() for token in CSS_CLASS_SELECTOR_RE.findall(simplified)}
    if selector_classes & page_classes:
        return True

    selector_ids = {token.lower() for token in CSS_ID_SELECTOR_RE.findall(simplified)}
    if selector_ids & page_ids:
        return True

    if "#page-content" in simplified:
        return True

    return False


def _page_style_targets(page_content: Tag) -> tuple[set[str], set[str]]:
    classes: set[str] = set()
    ids: set[str] = set()

    for tag in [page_content, *page_content.find_all(True)]:
        tag_id = tag.get("id")
        if isinstance(tag_id, str) and tag_id:
            ids.add(tag_id.lower())
        classes.update(_class_tokens(tag))

    return classes, ids


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
        if lowered.startswith("on"):
            tag.attrs.pop(attribute, None)
            continue
        if lowered == "style":
            sanitized_style = _sanitize_style_value(str(tag.attrs[attribute]))
            if sanitized_style:
                tag.attrs[attribute] = sanitized_style
            else:
                tag.attrs.pop(attribute, None)


def _sanitize_style_value(style: str) -> str:
    declarations: list[str] = []
    for raw_declaration in style.split(";"):
        property_name, separator, raw_value = raw_declaration.partition(":")
        if not separator:
            continue

        normalized_property = property_name.strip().lower()
        value = raw_value.strip()
        if normalized_property not in SAFE_STYLE_PROPERTIES:
            continue
        if not value or _has_unsafe_style_value(value):
            continue

        declarations.append(f"{normalized_property}: {value}")

    return "; ".join(declarations)


def _has_unsafe_style_value(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in UNSAFE_STYLE_VALUE_TOKENS)


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
