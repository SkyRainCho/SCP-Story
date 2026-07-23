from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html import escape, unescape
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

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
CSS_CUSTOM_PROPERTY_VALUE_RE = re.compile(
    r"(?P<name>--[a-z0-9_-]+)\s*:\s*(?P<value>[^;{}]+)",
    re.IGNORECASE,
)
CSS_VAR_FUNCTION_RE = re.compile(
    r"var\(\s*(?P<name>--[a-z0-9_-]+)\s*(?:,\s*(?P<fallback>[^()]+))?\)",
    re.IGNORECASE,
)
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
CSS_SEMICOLON_AT_RULE_RE = re.compile(
    r"@(import|charset|namespace)\b[^;{}]*;",
    re.IGNORECASE,
)
CSS_NUMERIC_TRIPLET_RE = re.compile(
    r"\d+(?:\.\d+)?\s*,\s*\d+(?:\.\d+)?\s*,\s*\d+(?:\.\d+)?"
)
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
CSS_BACKGROUND_IMAGE_URL_RE = re.compile(
    r"""background-image\s*:\s*url\(\s*(?:"(?P<double>[^"]+)"|'(?P<single>[^']+)'|(?P<bare>[^)\s]+))\s*\)""",
    re.IGNORECASE,
)
CSS_BACKGROUND_COLOR_RE = re.compile(
    r"background-color\s*:\s*(?P<value>[^;]+)",
    re.IGNORECASE,
)
MALFORMED_WIKIDOT_IMG_WIDTH_ATTRIBUTE_RE = re.compile(
    r'''width:(?:\d+(?:\.\d+)?(?:%|px|em|rem|vw|vh)?)?["']*''',
    re.IGNORECASE,
)
MALFORMED_WIKIDOT_IMG_WIDTH_SUFFIX_RE = re.compile(
    r'''=(?P<quote>["'])width:\s*\d+(?:\.\d+)?(?:%|px|em|rem|vw|vh)(?P=quote)$''',
    re.IGNORECASE,
)
CSS_ESCAPED_CHAR_RE = re.compile(r"\\(?P<escape>[0-9a-fA-F]{1,6}\s?|.)", re.DOTALL)
CSS_PSEUDO_RE = re.compile(r"::?[a-zA-Z-]+(?:\([^)]*\))?")
CSS_CLASS_SELECTOR_RE = re.compile(r"\.([_a-zA-Z][-_a-zA-Z0-9]*)")
CSS_ID_SELECTOR_RE = re.compile(r"#([_a-zA-Z][-_a-zA-Z0-9]*)")
CSS_PAGE_STYLE_TARGET_TOKEN_RE = re.compile(
    r"\.(?P<class>[_a-zA-Z][-_a-zA-Z0-9]*)|#(?P<id>[_a-zA-Z][-_a-zA-Z0-9]*)"
)
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
PAGE_EPUB_STYLE_RULES = {
    "scp-6747": (
        ".admo-episode_splash {display: block; height: auto; margin: 1.5em 0; "
        "text-align: center;}"
        "\n.admo-episode_splash .ctrl {font-size: 2.4em; line-height: 1.2;}"
        "\n.admo-episode_splash .cond {font-size: 1.2em;}"
        "\n.admo-episode_splash .admo-rate_splash {margin-top: 0; padding-bottom: 0;}"
        "\n.admo-end_card .admo-credits {display: block; text-align: center;}"
    ),
    "secure-facility-dossier-site-7": (
        ".scp-image-caption {background-color: #262626;}"
    ),
    "secure-facility-dossier-area-12": (
        "#page-content .floatbox.metam {background-color: #080808 !important; "
        "color: #d2d2d2 !important; border: 1px solid #333;}"
        "\n#page-content .floatbox.metam .fncon {background-color: #030303; "
        "color: #fff; padding: 0.1em 0.25em;}"
    ),
}
ANOMALY_CLEARANCE_LABELS = {
    "clear-1": "公开",
    "clear-2": "受限",
    "clear-3": "保密",
    "clear-4": "机密",
    "clear-5": "最高机密",
    "clear-6": "宇宙绝密",
}
ANOMALY_DIAMOND_FRAME_PATH = (
    "M136.1,133.3l23.9-23.9V51.2l-24-24l19.1-19.1l4.9,4.9l0-12.9"
    "l-12.9,0l4.9,4.9L133,24.2l-24-24H51l-24,24L8,5.2l4.9-4.9"
    "L0,0.2l0,12.9l4.9-4.9L24,27.3l-24,24v58.2l23.9,23.9l-19,19"
    "L0,147.3l0,12.9l12.9,0L8,155.3l19-19l23.9,23.9h58.4l23.9-23.9"
    "l19,19l-4.9,4.9l12.9,0l0-12.9l-4.9,4.9L136.1,133.3z"
    "M155.7,53v54.6l-22.6,22.6l-50-50L133,30.3L155.7,53z"
    "M52.8,4.5h54.4l22.7,22.7L80,77.2L30.1,27.3L52.8,4.5z"
    "M4.3,107.6V53L27,30.3L77,80.2l-50,50L4.3,107.6z"
    "M107.4,155.9H52.6L30,133.3l50-50l50,50L107.4,155.9z"
)
ANOMALY_DIAMOND_QUADRANT_POINTS = (
    "51.226,3.456 108.250,3.456 132.096,27.264 "
    "80.256,80.256 28.416,27.264"
)
ANOMALY_DIAMOND_QUADRANT_TRANSFORMS = {
    "top": None,
    "right": "rotate(90 80.256 80.256)",
    "left": "rotate(270 80.256 80.256)",
    "bottom": "rotate(180 80.256 80.256)",
}
ANOMALY_QUADRANT_FALLBACK_COLORS = {
    ("contain-class", "safe"): ("#009f6b", "0.25"),
    ("contain-class", "euclid"): ("#ffd300", "0.25"),
    ("contain-class", "keter"): ("#c40233", "0.25"),
    ("contain-class", "esoteric"): ("#424248", "0.15"),
    ("contain-class", "机密"): ("#424248", "0.15"),
    ("contain-class", "機密"): ("#424248", "0.15"),
    ("contain-class", "neutralized"): ("#424248", "0.25"),
    ("contain-class", "neutralised"): ("#424248", "0.25"),
    ("contain-class", "无效化"): ("#424248", "0.25"),
    ("contain-class", "無效化"): ("#424248", "0.25"),
    ("contain-class", "pending"): ("#0c0c0c", "0.25"),
    ("contain-class", "等待分级"): ("#0c0c0c", "0.25"),
    ("contain-class", "等待分級"): ("#0c0c0c", "0.25"),
    ("disrupt-class", "dark"): ("#009f6b", "0.25"),
    ("disrupt-class", "vlam"): ("#0087bd", "0.25"),
    ("disrupt-class", "keneq"): ("#ffd300", "0.25"),
    ("disrupt-class", "ekhi"): ("#ff6d00", "0.25"),
    ("disrupt-class", "amida"): ("#c40233", "0.25"),
    ("risk-class", "notice"): ("#009f6b", "0.25"),
    ("risk-class", "待观察"): ("#009f6b", "0.25"),
    ("risk-class", "待觀察"): ("#009f6b", "0.25"),
    ("risk-class", "caution"): ("#0087bd", "0.25"),
    ("risk-class", "需谨慎"): ("#0087bd", "0.25"),
    ("risk-class", "需謹慎"): ("#0087bd", "0.25"),
    ("risk-class", "warning"): ("#ffd300", "0.25"),
    ("risk-class", "警告"): ("#ffd300", "0.25"),
    ("risk-class", "danger"): ("#ff6d00", "0.25"),
    ("risk-class", "危险"): ("#ff6d00", "0.25"),
    ("risk-class", "危險"): ("#ff6d00", "0.25"),
    ("risk-class", "critical"): ("#c40233", "0.25"),
    ("risk-class", "危急"): ("#c40233", "0.25"),
}
CLASSIFICATION_FAMILY_ATTRIBUTE = "data-epub-classification-family"
CLASSIFICATION_STATUS_ATTRIBUTE = "data-epub-classification-status"
ACS_REQUIRED_SELECTORS = (
    ".top-box",
    ".top-left-box",
    ".top-center-box",
    ".top-right-box",
    ".bottom-box",
    ".text-part",
    ".main-class",
    ".contain-class",
    ".diamond-part",
    ".danger-diamond",
)
WOED_LEVEL_RE = re.compile(r"lv([0-6])", re.IGNORECASE)
WOED_REQUIRED_SELECTORS = (
    ".class1",
    ".class1image",
    ".item1",
    ".itemnum",
    ".objclass",
    ".obj-text",
)
WOED_OBJECT_CLASS_NAMES = {
    "safe": "safe",
    "euclid": "euclid",
    "keter": "keter",
    "thaumiel": "thaumiel",
    "neutralized": "neutralized",
    "neutralised": "neutralized",
}
ANOMALY_ICON_BASE_URL = (
    "https://scp-wiki.wdfiles.com/local--files/component%3Aanomaly-class-bar"
)
ACS_ANOMALY_ICON_PLACEHOLDER_URL = "https://example.com/acs-image.svg"
ANOMALY_ICON_NAMES = {
    "safe": "safe",
    "euclid": "euclid",
    "keter": "keter",
    "esoteric": "esoteric",
    "机密": "esoteric",
    "機密": "esoteric",
    "pending": "pending",
    "等待分级": "pending",
    "等待分級": "pending",
    "explained": "explained",
    "已解明": "explained",
    "thaumiel": "thaumiel",
    "archon": "archon",
    "cernunnos": "cernunnos",
    "ticonderoga": "ticonderoga",
    "tiamat": "tiamat",
    "cantas": "cantas",
    "neutralized": "neutralized",
    "neutralised": "neutralized",
    "无效化": "neutralized",
    "無效化": "neutralized",
    "dark": "dark",
    "vlam": "vlam",
    "keneq": "keneq",
    "ekhi": "ekhi",
    "amida": "amida",
    "notice": "notice",
    "待观察": "notice",
    "待觀察": "notice",
    "caution": "caution",
    "需谨慎": "caution",
    "需謹慎": "caution",
    "warning": "warning",
    "警告": "warning",
    "danger": "danger",
    "危险": "danger",
    "危險": "danger",
    "critical": "critical",
    "危急": "critical",
}
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
RECOMMENDATION_PANEL_LABELS = frozenset({"你可能也会喜欢", "您可能也会喜欢"})
SUBSTANTIVE_MEDIA_TAGS = ("audio", "figure", "img", "object", "picture", "svg", "table", "video")
TWO_LINK_TERMINAL_NAVIGATION_SLUGS = frozenset({"scp-7261", "scp-3662"})


@dataclass(frozen=True)
class PageTransformOptions:
    remove_terminal_navigation: bool = False
    remove_leading_metadata: bool = False
    remove_adult_content_warning: bool = False
    remove_author_work_list: bool = False
    remove_recommendation_panel: bool = False
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

    if page_content.select_one(".anom-bar-container") is not None:
        anomaly_icon_urls, anomaly_quadrant_colors = _anomaly_style_metadata(
            soup, base_url
        )
    else:
        anomaly_icon_urls, anomaly_quadrant_colors = {}, {}
    page_styles = _applicable_page_styles(soup, page_content)

    _remove_creator_information_blocks(page_content)

    for tag in list(page_content.find_all(_is_unwanted_element)):
        tag.decompose()

    _normalize_anomaly_classification_bars(
        soup,
        page_content,
        anomaly_icon_urls,
        anomaly_quadrant_colors,
    )
    _normalize_woed_classified_bars(soup, page_content)

    profile_style_rules = _apply_page_cleanup_options(
        entry,
        page_content,
        page_options or PageTransformOptions(),
    )
    page_styles = _append_page_style_rules(page_styles, profile_style_rules)
    page_styles = _append_page_style_rules(
        page_styles, PAGE_EPUB_STYLE_RULES.get(entry.slug, "")
    )
    if entry.slug == "scp-6747":
        _stabilize_scp_6747_splash(page_content)

    if _has_interactive_article_layout(page_content):
        _linearize_interactive_article_layout(page_content)
        page_styles = _linearize_interactive_article_styles(page_styles)
        page_styles = _append_page_style_rules(page_styles, INTERACTIVE_ARTICLE_EPUB_STYLE_RULES)

    _normalize_ruby_annotations(soup, page_content)
    page_styles = _materialize_generated_before_content(soup, page_content, page_styles)
    _convert_grid_tables(soup, page_content)
    _stabilize_float_layout(soup, page_content)
    _stabilize_text_message_layout(page_content)
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
    if options.remove_recommendation_panel:
        _remove_recommendation_panels(page_content)

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


def _remove_recommendation_panels(page_content: Tag) -> None:
    for heading in list(page_content.select(".collapsible-block-folded")):
        if not _is_recommendation_panel_label(heading.get_text(" ", strip=True)):
            continue
        panel = heading.find_parent(class_="collapsible-block")
        if isinstance(panel, Tag):
            panel.decompose()


def _is_recommendation_panel_label(value: str) -> bool:
    normalized = re.sub(r"\s+", "", value).rstrip(".…")
    return normalized in RECOMMENDATION_PANEL_LABELS


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
        raw_url = _normalize_malformed_wikidot_img_src(tag, raw_url)

        if _should_ignore_url(raw_url):
            tag.attrs.pop(attribute, None)
            continue

        normalized = normalize_url(base_url, raw_url)
        tag[attribute] = normalized
        if _has_non_downloadable_asset_scheme(normalized):
            continue

        _append_once(asset_urls, seen_assets, normalized)


def _normalize_malformed_wikidot_img_src(tag: Tag, raw_url: str) -> str:
    if tag.name != "img":
        return raw_url

    embedded_width_markup = MALFORMED_WIKIDOT_IMG_WIDTH_SUFFIX_RE.search(raw_url)
    if embedded_width_markup is not None:
        return raw_url[: embedded_width_markup.start()]

    if not raw_url.endswith("="):
        return raw_url
    malformed_attributes = [
        name
        for name in tag.attrs
        if isinstance(name, str)
        and MALFORMED_WIKIDOT_IMG_WIDTH_ATTRIBUTE_RE.fullmatch(name) is not None
    ]
    if not malformed_attributes:
        return raw_url

    for name in malformed_attributes:
        del tag.attrs[name]
    return raw_url[:-1]


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

    if (
        _is_hidden_css_code_container(tag)
        or _is_hidden_scp_image_container(tag)
        or _is_css_code_collapsible(tag)
    ):
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


def _ordered_class_tokens(tag: Tag) -> tuple[str, ...]:
    raw_classes = tag.get("class", [])
    if isinstance(raw_classes, str):
        return tuple(token.casefold() for token in raw_classes.split())
    if isinstance(raw_classes, Iterable):
        return tuple(str(token).casefold() for token in raw_classes)
    return ()


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


def _stabilize_scp_6747_splash(page_content: Tag) -> None:
    for splash in page_content.select(".admo-episode_splash, .admo-intermission_splash"):
        classes = [
            class_name
            for class_name in splash.get("class", [])
            if class_name not in {"admo-episode_splash", "admo-intermission_splash"}
        ]
        splash["class"] = [*classes, "admo-episode-splash-epub"]
        for title in splash.select(".ctrl"):
            title["style"] = "font-size: 2.4em; line-height: 1.2"
        for subtitle in splash.select(".cond"):
            subtitle["style"] = "font-size: 1.2em"


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
    if not isinstance(style, str):
        return False
    for declaration in style.split(";"):
        property_name, separator, value = declaration.partition(":")
        if not separator or property_name.strip().casefold() != "display":
            continue
        normalized_value = re.sub(
            r"\s*!important\s*$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        if normalized_value.casefold() == "none":
            return True
    return False


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
    custom_properties = _numeric_css_custom_properties(soup)

    for style in soup.find_all("style"):
        css_text = _css_rule_source(style.get_text("\n", strip=True))
        if not _style_block_may_target_page_content(css_text, targets):
            continue
        for rule in _matching_css_rules(css_text, targets, custom_properties):
            if rule in seen_rules:
                continue
            seen_rules.add(rule)
            rules.append(rule)

    return "\n".join(rules)


def _style_block_may_target_page_content(
    css_text: str, targets: tuple[set[str], set[str]]
) -> bool:
    page_classes, page_ids = targets
    normalized_css = css_text.casefold()
    if "#page-content" in normalized_css:
        return True

    selector_classes: set[str] = set()
    selector_ids: set[str] = set()
    for match in CSS_PAGE_STYLE_TARGET_TOKEN_RE.finditer(normalized_css):
        class_name = match.group("class")
        if class_name is not None:
            selector_classes.add(class_name)
            continue
        selector_ids.add(match.group("id"))

    return bool(selector_classes & page_classes or selector_ids & page_ids)


def _css_rule_source(css_text: str) -> str:
    without_comments = CSS_COMMENT_RE.sub(" ", unescape(css_text))
    return CSS_SEMICOLON_AT_RULE_RE.sub(" ", without_comments)


def _matching_css_rules(
    css_text: str,
    targets: tuple[set[str], set[str]],
    custom_properties: dict[str, str],
) -> list[str]:
    rules: list[str] = []
    for match in CSS_RULE_RE.finditer(css_text):
        selector_text = re.sub(r"\s+", " ", match.group("selectors")).strip()
        body = _resolve_numeric_css_variables(
            match.group("body").strip(), custom_properties
        )
        if not selector_text or not body:
            continue
        selectors = _split_css_selector_list(selector_text)
        supported_selectors = [
            selector
            for selector in selectors
            if not WIKIDOT_TEMPLATE_PLACEHOLDER_RE.search(selector)
            and not _is_unsupported_page_style_selector(selector)
        ]
        matching_selectors = [
            _epub_page_style_selector(selector)
            for selector in supported_selectors
            if _selector_targets_page_content(selector, targets)
        ]
        if matching_selectors:
            rules.append(f"{', '.join(matching_selectors)} {{{body}}}")
    return rules


def _epub_page_style_selector(selector: str) -> str:
    selector = re.sub(r"#page-content\b\s*", "", selector).strip()
    return re.sub(r"^>\s*", "", selector).strip()


def _split_css_selector_list(selector_text: str) -> list[str]:
    selectors: list[str] = []
    current: list[str] = []
    nesting = 0
    quote: str | None = None
    escaped = False

    for character in selector_text:
        if quote is not None:
            current.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character in "([":
            nesting += 1
        elif character in ")]":
            nesting = max(0, nesting - 1)
        elif character == "," and nesting == 0:
            selector = "".join(current).strip()
            if selector:
                selectors.append(selector)
            current = []
            continue
        current.append(character)

    selector = "".join(current).strip()
    if selector:
        selectors.append(selector)
    return selectors


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


def _mark_classification_component(tag: Tag, family: str, status: str) -> None:
    tag[CLASSIFICATION_FAMILY_ATTRIBUTE] = family
    tag[CLASSIFICATION_STATUS_ATTRIBUTE] = status


def _has_required_descendants(component: Tag, selectors: tuple[str, ...]) -> bool:
    return all(component.select_one(selector) is not None for selector in selectors)


def _wrap_anomaly_lower_fields(soup: BeautifulSoup, container: Tag) -> None:
    text_part = container.select_one(".text-part")
    if (
        text_part is None
        or text_part.select_one(":scope > .anomaly-lower-row") is not None
    ):
        return
    fields = [
        field
        for selector in (":scope > .disrupt-class", ":scope > .risk-class")
        if (field := text_part.select_one(selector)) is not None
    ]
    if not fields:
        return
    lower = soup.new_tag("div", attrs={"class": "anomaly-lower-row"})
    for field in fields:
        lower.append(field.extract())
    text_part.append(lower)


def _build_anomaly_diamond_layout(
    soup: BeautifulSoup,
    container: Tag,
    field_values: dict[str, str],
    ordered_classes: tuple[str, ...],
    page_quadrant_colors: dict[tuple[str, str], tuple[str, str]],
) -> None:
    diamond = container.select_one(".danger-diamond")
    if diamond is None:
        return
    if diamond.select_one(":scope > .anomaly-diamond-frame") is None:
        frame = soup.new_tag(
            "svg",
            attrs={
                "class": "anomaly-diamond-frame",
                "viewBox": "0 0 160 160",
                "preserveAspectRatio": "xMidYMid meet",
                "aria-hidden": "true",
                "focusable": "false",
            },
        )
        quadrant_fields = {
            "top": "contain-class",
            "right": "risk-class",
            "left": "disrupt-class",
            "bottom": "second-class",
        }
        for quadrant, field_class in quadrant_fields.items():
            fill, opacity = _anomaly_quadrant_color(
                quadrant,
                field_class,
                field_values.get(field_class, ""),
                ordered_classes,
                page_quadrant_colors,
            )
            attrs = {
                "class": "anomaly-diamond-quadrant",
                "data-quadrant": quadrant,
                "points": ANOMALY_DIAMOND_QUADRANT_POINTS,
                "fill": fill,
                "fill-opacity": opacity,
            }
            transform = ANOMALY_DIAMOND_QUADRANT_TRANSFORMS[quadrant]
            if transform is not None:
                attrs["transform"] = transform
            frame.append(soup.new_tag("polygon", attrs=attrs))
        frame_path = soup.new_tag(
            "path",
            attrs={
                "d": ANOMALY_DIAMOND_FRAME_PATH,
                "fill": "#010101",
            },
        )
        frame.append(frame_path)
        diamond.insert(0, frame)
    if diamond.select_one(":scope > .anomaly-diamond-layout") is not None:
        return
    slots = {
        name: diamond.select_one(f":scope > .{name}-icon")
        for name in ("top", "left", "right", "bottom")
    }
    table = soup.new_tag(
        "table",
        attrs={"class": "anomaly-diamond-layout", "role": "presentation"},
    )
    tbody = soup.new_tag("tbody")
    table.append(tbody)
    for row_slots in (
        (None, "top", None),
        ("left", None, "right"),
        (None, "bottom", None),
    ):
        row = soup.new_tag("tr")
        for slot_name in row_slots:
            cell = soup.new_tag(
                "td",
                attrs={"class": f"anomaly-diamond-{slot_name or 'empty'}"},
            )
            if slot_name is not None and slots[slot_name] is not None:
                cell.append(slots[slot_name].extract())
            row.append(cell)
        tbody.append(row)
    diamond.append(table)


def _normalize_anomaly_classification_bars(
    soup: BeautifulSoup,
    page_content: Tag,
    page_icon_urls: dict[tuple[str, str], str],
    page_quadrant_colors: dict[tuple[str, str], tuple[str, str]],
) -> None:
    _remove_hidden_unexpanded_anomaly_templates(page_content)
    for container in list(page_content.select(".anom-bar-container")):
        if container.parent is None:
            continue
        _remove_placeholder_class_tokens(container)
        ordered_classes = _ordered_class_tokens(container)
        classes = set(ordered_classes)
        clearance = container.select_one(".top-right-box .clearance")
        clearance_label = next(
            (
                label
                for class_name, label in ANOMALY_CLEARANCE_LABELS.items()
                if class_name in classes
            ),
            None,
        )
        if (
            clearance is not None
            and clearance_label is not None
            and not clearance.get_text(" ", strip=True)
        ):
            label = soup.new_tag(
                "span",
                attrs={"class": "anomaly-clearance-label"},
            )
            label.string = clearance_label
            clearance.append(label)

        field_specs = (
            ("contain-class", "top-icon"),
            ("second-class", "bottom-icon"),
            ("disrupt-class", "left-icon"),
            ("risk-class", "right-icon"),
        )
        field_values: dict[str, str] = {}
        for field_class, diamond_class in field_specs:
            field = container.select_one(f".{field_class}")
            if field is None:
                continue
            class_text = field.select_one(".class-text")
            value = class_text.get_text(" ", strip=True) if class_text else ""
            field_values[field_class] = value
            if field_class != "contain-class" and _is_missing_anomaly_value(value):
                field.decompose()
                continue
            icon_url = _anomaly_icon_url(
                value,
                field_class,
                ordered_classes,
                page_icon_urls,
            )
            if icon_url is None:
                continue
            _insert_anomaly_icon(
                soup,
                field,
                icon_url,
                value,
                "anomaly-field-icon",
            )
            diamond_slot = container.select_one(f".danger-diamond .{diamond_class}")
            if diamond_slot is not None:
                _insert_anomaly_icon(
                    soup,
                    diamond_slot,
                    icon_url,
                    value,
                    "anomaly-diamond-icon",
                )

        main_class = container.select_one(".main-class")
        if main_class is not None and main_class.select_one(".second-class") is None:
            _add_class_token(main_class, "anomaly-single-containment")

        if not _has_required_descendants(container, ACS_REQUIRED_SELECTORS):
            _mark_classification_component(container, "acs", "unrecognized")
            continue
        _wrap_anomaly_lower_fields(soup, container)
        _build_anomaly_diamond_layout(
            soup,
            container,
            field_values,
            ordered_classes,
            page_quadrant_colors,
        )
        _mark_classification_component(container, "acs", "normalized")


def _normalize_woed_classified_bars(
    soup: BeautifulSoup,
    page_content: Tag,
) -> None:
    for scale in list(page_content.select(".scale")):
        level_region = scale.select_one(":scope > .class1image")
        if level_region is None or level_region.select_one(".classified-bar") is None:
            continue
        level_match = WOED_LEVEL_RE.fullmatch(
            str(level_region.get("data-level", ""))
        )
        if (
            not _has_required_descendants(scale, WOED_REQUIRED_SELECTORS)
            or level_match is None
        ):
            _mark_classification_component(scale, "woed", "unrecognized")
            continue
        level = int(level_match.group(1))
        object_text = scale.select_one(".obj-text")
        object_class = (
            WOED_OBJECT_CLASS_NAMES.get(
                object_text.get_text(" ", strip=True).casefold()
            )
            if object_text is not None
            else None
        )
        _materialize_woed_level_text(scale)
        _add_class_token(scale, f"woed-level-{level}")
        _add_class_token(scale, f"woed-class-{object_class or 'other'}")
        level_region.clear()
        _add_class_token(level_region, "woed-level-segments")
        for segment_number in range(1, level + 1):
            segment = soup.new_tag(
                "span",
                attrs={
                    "class": [
                        "woed-level-segment",
                        f"woed-level-segment-{segment_number}",
                    ],
                    "aria-hidden": "true",
                },
            )
            level_region.append(segment)
        _mark_classification_component(scale, "woed", "normalized")


def _materialize_woed_level_text(scale: Tag) -> None:
    level_text = scale.select_one(".level-text")
    if level_text is None:
        return
    base_spans = level_text.find_all("span", class_="base", recursive=False)
    if len(base_spans) < 2:
        return
    label = " ".join(
        str(child).strip()
        for child in level_text.children
        if isinstance(child, NavigableString) and str(child).strip()
    )
    false_variant = "false" in _class_tokens(base_spans[0])
    value_span = base_spans[1] if false_variant else base_spans[0]
    value = value_span.get_text(" ", strip=True)
    visible_text = f"{label} {value}" if false_variant else f"{value} {label}"
    level_text.clear()
    level_text.string = visible_text.strip()


def _anomaly_style_metadata(
    soup: BeautifulSoup,
    base_url: str,
) -> tuple[
    dict[tuple[str, str], str],
    dict[tuple[str, str], tuple[str, str]],
]:
    icon_urls: dict[tuple[str, str], str] = {}
    colors: dict[tuple[str, str], tuple[str, str]] = {}
    custom_properties = _numeric_css_custom_properties(soup)
    for style in soup.find_all("style"):
        for rule in CSS_RULE_RE.finditer(style.get_text("\n", strip=True)):
            url_match = CSS_BACKGROUND_IMAGE_URL_RE.search(rule.group("body"))
            if url_match is not None:
                raw_url = next(
                    (
                        value
                        for value in (
                            url_match.group("double"),
                            url_match.group("single"),
                            url_match.group("bare"),
                        )
                        if value
                    ),
                    None,
                )
                if (
                    raw_url is not None
                    and WIKIDOT_TEMPLATE_PLACEHOLDER_RE.search(raw_url) is None
                ):
                    normalized_url = normalize_url(base_url, raw_url)
                    if normalized_url != ACS_ANOMALY_ICON_PLACEHOLDER_URL:
                        for selector in rule.group("selectors").split(","):
                            field_class = _anomaly_field_class_for_selector(selector)
                            if field_class is None:
                                continue
                            normalized_selector = selector.replace("\\", "").casefold()
                            placeholder_names = {
                                "contain-class": (
                                    "container-class",
                                    "containment-class",
                                ),
                                "second-class": ("secondary-class",),
                                "disrupt-class": ("disruption-class",),
                                "risk-class": ("risk-class",),
                            }[field_class]
                            if any(
                                "{$" + placeholder_name + "}" in normalized_selector
                                for placeholder_name in placeholder_names
                            ):
                                icon_urls[("*", field_class)] = normalized_url
                                continue
                            if WIKIDOT_TEMPLATE_PLACEHOLDER_RE.search(selector) is not None:
                                continue
                            for class_name in re.findall(
                                r"\.anom-bar-container\.([^\s.:#>+~,\[\](){}]+)",
                                selector,
                            ):
                                icon_urls[(class_name.casefold(), field_class)] = normalized_url
            color = _last_resolved_background_color(
                rule.group("body"), custom_properties
            )
            if color is None:
                continue
            for selector in rule.group("selectors").split(","):
                quadrants = set(
                    re.findall(
                        r"\.(top|right|left|bottom)-quad\b",
                        selector,
                        re.IGNORECASE,
                    )
                )
                if not quadrants and re.search(
                    r"\.quadrants\s*>\s*div\b", selector, re.IGNORECASE
                ):
                    quadrants = {"top", "right", "left", "bottom"}
                if not quadrants:
                    continue
                class_names = re.findall(
                    r"\.anom-bar-container\.([^\s.:#>+~,\[\](){}]+)",
                    selector,
                )
                for quadrant in quadrants:
                    modifier_names = re.findall(
                        rf"\.{quadrant}-quad\.([^\s.:#>+~,\[\](){{}}]+)",
                        selector,
                        re.IGNORECASE,
                    )
                    names = class_names or modifier_names or ["*"]
                    for class_name in names:
                        colors[(class_name.replace("\\", "").casefold(), quadrant)] = color
    return icon_urls, colors


def _numeric_css_custom_properties(soup: BeautifulSoup) -> dict[str, str]:
    raw_properties: dict[str, str] = {}
    for style in soup.find_all("style"):
        css_text = CSS_COMMENT_RE.sub(" ", style.get_text("\n", strip=True))
        for match in CSS_CUSTOM_PROPERTY_VALUE_RE.finditer(css_text):
            raw_properties[match.group("name").casefold()] = re.sub(
                r"\s*!important\s*$",
                "",
                match.group("value"),
                flags=re.IGNORECASE,
            ).strip()

    resolved: dict[str, str] = {}
    resolving: set[str] = set()

    def resolve(name: str) -> str | None:
        if name in resolved:
            return resolved[name]
        if name in resolving:
            return None
        value = raw_properties.get(name)
        if value is None:
            return None
        if CSS_NUMERIC_TRIPLET_RE.fullmatch(value) or _parse_numeric_css_color(value):
            resolved[name] = value
            return value

        variable = CSS_VAR_FUNCTION_RE.fullmatch(value)
        if variable is None:
            return None

        resolving.add(name)
        replacement = resolve(variable.group("name").casefold())
        resolving.remove(name)
        fallback = (variable.group("fallback") or "").strip()
        result = replacement or (
            fallback
            if CSS_NUMERIC_TRIPLET_RE.fullmatch(fallback)
            or _parse_numeric_css_color(fallback)
            else None
        )
        if result is not None:
            resolved[name] = result
        return result

    for property_name in raw_properties:
        resolve(property_name)
    return resolved


def _resolve_numeric_css_variables(
    style_body: str,
    custom_properties: dict[str, str],
) -> str:
    return CSS_VAR_FUNCTION_RE.sub(
        lambda variable: custom_properties.get(
            variable.group("name").casefold(),
            (variable.group("fallback") or "").strip() or variable.group(0),
        ),
        style_body,
    )


def _last_resolved_background_color(
    style_body: str,
    custom_properties: dict[str, str],
) -> tuple[str, str] | None:
    result: tuple[str, str] | None = None
    for match in CSS_BACKGROUND_COLOR_RE.finditer(style_body):
        value = match.group("value").strip()
        value = CSS_VAR_FUNCTION_RE.sub(
            lambda variable: custom_properties.get(
                variable.group("name").casefold(),
                (variable.group("fallback") or "").strip(),
            ),
            value,
        )
        if "var(" in value.casefold():
            continue
        parsed = _parse_numeric_css_color(value)
        if parsed is not None:
            result = parsed
    return result


def _parse_numeric_css_color(value: str) -> tuple[str, str] | None:
    hex_match = re.fullmatch(r"#(?P<value>[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value)
    if hex_match is not None:
        hex_value = hex_match.group("value")
        if len(hex_value) == 3:
            hex_value = "".join(character * 2 for character in hex_value)
        return f"#{hex_value.lower()}", "1"

    function_match = re.fullmatch(
        r"rgba?\(\s*(?P<red>\d+(?:\.\d+)?)\s*,\s*"
        r"(?P<green>\d+(?:\.\d+)?)\s*,\s*"
        r"(?P<blue>\d+(?:\.\d+)?)"
        r"(?:\s*,\s*(?P<alpha>\d+(?:\.\d+)?))?\s*\)",
        value,
        re.IGNORECASE,
    )
    if function_match is None:
        return None
    channels = [
        max(0, min(255, round(float(function_match.group(name)))))
        for name in ("red", "green", "blue")
    ]
    alpha = max(0.0, min(1.0, float(function_match.group("alpha") or "1")))
    return "#" + "".join(f"{channel:02x}" for channel in channels), f"{alpha:g}"


def _anomaly_quadrant_color(
    quadrant: str,
    field_class: str,
    field_value: str,
    ordered_classes: tuple[str, ...],
    page_colors: dict[tuple[str, str], tuple[str, str]],
) -> tuple[str, str]:
    normalized_value = field_value.casefold()
    for class_name in (normalized_value, *ordered_classes):
        color = page_colors.get((class_name.casefold(), quadrant))
        if color is not None:
            return color
    fallback = ANOMALY_QUADRANT_FALLBACK_COLORS.get(
        (field_class, normalized_value)
    )
    if fallback is not None:
        return fallback
    wildcard = page_colors.get(("*", quadrant))
    if wildcard is not None:
        return wildcard
    return "#fcfcfc", "1"


def _anomaly_field_class_for_selector(selector: str) -> str | None:
    normalized = re.sub(r"\s+", "", selector).casefold()
    field_patterns = (
        (
            "contain-class",
            (
                r"\.contain-class::?(?:before|after)",
                r"\.main-class::?before",
                r"\.top-icon::?(?:before|after)",
            ),
        ),
        (
            "second-class",
            (
                r"\.second-class::?(?:before|after)",
                r"\.main-class::?after",
                r"\.bottom-icon::?(?:before|after)",
            ),
        ),
        (
            "disrupt-class",
            (
                r"\.disrupt-class::?(?:before|after)",
                r"\.left-icon::?(?:before|after)",
            ),
        ),
        (
            "risk-class",
            (
                r"\.risk-class::?(?:before|after)",
                r"\.right-icon::?(?:before|after)",
            ),
        ),
    )
    for field_class, patterns in field_patterns:
        if any(re.search(pattern, normalized) is not None for pattern in patterns):
            return field_class
    return None


def _anomaly_icon_url(
    value: str,
    field_class: str,
    container_classes: tuple[str, ...],
    page_icon_urls: dict[tuple[str, str], str],
) -> str | None:
    normalized_value = value.casefold()
    for class_name in (normalized_value, *container_classes):
        page_url = page_icon_urls.get((class_name.casefold(), field_class))
        if page_url is not None:
            return page_url
    wildcard_url = page_icon_urls.get(("*", field_class))
    if wildcard_url is not None:
        return wildcard_url
    icon_name = ANOMALY_ICON_NAMES.get(normalized_value)
    if icon_name is None:
        return None
    return f"{ANOMALY_ICON_BASE_URL}/{icon_name}-icon.svg"


def _remove_hidden_unexpanded_anomaly_templates(page_content: Tag) -> None:
    for component in list(page_content.select(".anom-bar-container")):
        if component.parent is None or component.name is None:
            continue
        number = component.select_one(".number")
        containment = component.select_one(".contain-class .class-text")
        identifying_markup = " ".join(
            value
            for value in (
                " ".join(str(token) for token in component.get("class", [])),
                number.get_text(" ", strip=True) if number else "",
                containment.get_text(" ", strip=True) if containment else "",
            )
            if value
        )
        if WIKIDOT_TEMPLATE_PLACEHOLDER_RE.search(identifying_markup) is None:
            continue
        hidden = (
            component
            if _is_hidden_by_style(component)
            else component.find_parent(_is_hidden_by_style)
        )
        if (
            not isinstance(hidden, Tag)
            or hidden is page_content
            or page_content not in hidden.parents
        ):
            continue
        hidden_parent = hidden.parent
        protects_dynamic_content = (
            "collapsible-block-unfolded" in _class_tokens(hidden)
            or "yui-content" in _class_tokens(hidden)
            or (
                isinstance(hidden_parent, Tag)
                and "yui-content" in _class_tokens(hidden_parent)
            )
        )
        (component if protects_dynamic_content else hidden).decompose()


def _remove_placeholder_class_tokens(tag: Tag) -> None:
    raw_classes = tag.get("class", [])
    classes = raw_classes.split() if isinstance(raw_classes, str) else list(raw_classes)
    kept = [
        str(class_name)
        for class_name in classes
        if WIKIDOT_TEMPLATE_PLACEHOLDER_RE.search(str(class_name)) is None
    ]
    if kept:
        tag["class"] = kept
    elif tag.has_attr("class"):
        del tag["class"]


def _is_missing_anomaly_value(value: str) -> bool:
    stripped = value.strip()
    return (
        not stripped
        or stripped.casefold() == "none"
        or WIKIDOT_TEMPLATE_PLACEHOLDER_RE.fullmatch(stripped) is not None
    )


def _insert_anomaly_icon(
    soup: BeautifulSoup,
    target: Tag,
    icon_url: str,
    label: str,
    class_name: str,
) -> None:
    if target.select_one(f"img.{class_name}") is not None:
        return
    icon = soup.new_tag(
        "img",
        attrs={
            "class": class_name,
            "src": icon_url,
            "alt": f"{label} 等级图标",
        },
    )
    target.insert(0, icon)
    if class_name == "anomaly-diamond-icon":
        _add_class_token(target, "anomaly-icon-slot")


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


def _stabilize_text_message_layout(page_content: Tag) -> None:
    for container in page_content.select(".text-container"):
        if container.select_one(".recv, .sent") is None:
            continue
        wrapper = container.find_parent(class_="text-container-wrap")
        if wrapper is not None:
            _append_style_declaration(wrapper, "width", "500px !important")
            _append_style_declaration(wrapper, "max-width", "100% !important")
        _append_style_declaration(container, "font-size", "0.72em !important")
        _append_style_declaration(container, "width", "450px !important")
        _append_style_declaration(container, "max-width", "90% !important")
        for bubble in container.select(".recv .text, .sent .text"):
            _append_style_declaration(bubble, "max-width", "85% !important")

    for message in page_content.select(".text-container .recv, .text-container .sent"):
        alignment = "right" if "sent" in _class_tokens(message) else "left"
        bubble_class = f"epub-chat-bubble-{alignment}"
        message["align"] = alignment
        _append_style_declaration(message, "text-align", f"{alignment} !important")
        for paragraph in message.find_all("p", recursive=False):
            paragraph["align"] = alignment
            _append_style_declaration(
                paragraph,
                "text-align",
                f"{alignment} !important",
            )
            bubbles = [
                bubble
                for bubble in paragraph.find_all("span", recursive=False)
                if "text" in _class_tokens(bubble)
            ]
            for bubble in bubbles:
                _add_class_token(bubble, bubble_class)
            if len(bubbles) > 1:
                for line_break in paragraph.find_all("br", recursive=False):
                    line_break.decompose()


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
    intermission = page_content.select_one(".admo-intermission_splash")
    if intermission is not None:
        _remove_class_token(intermission, "admo-intermission_splash")
        _add_class_token(intermission, "layout-profile-scp-6183-intermission")
        for property_name, value in (
            ("margin", "1.5em 0 0"),
            ("padding", "2em 1em"),
            ("background", "#000"),
            ("color", "#d8d8d8"),
            ("text-align", "center"),
        ):
            _append_style_declaration(intermission, property_name, value)
        ctrl = intermission.select_one(".ctrl")
        if ctrl is not None:
            _append_style_declaration(ctrl, "font-size", "2em")
            _append_style_declaration(ctrl, "font-weight", "bold")

    content = page_content.select_one(".fadeout-wrapper")
    if content is not None:
        _remove_class_token(content, "fadeout-wrapper")
        _add_class_token(content, "layout-profile-scp-6183-content")

        for animation_cover in list(content.select(".cover")):
            if (
                not animation_cover.get_text(" ", strip=True)
                and animation_cover.find(True) is None
            ):
                animation_cover.decompose()

        symbol = content.find("img", alt="rsm.png")
        if symbol is not None:
            _add_class_token(symbol, "layout-profile-scp-6183-symbol")
            _append_style_declaration(symbol, "width", "20%")
            _append_style_declaration(symbol, "max-width", "10rem")
            _append_style_declaration(symbol, "height", "auto")
            _append_style_declaration(symbol, "margin", "0 auto")
            symbol_panel = symbol.find_parent(class_="image-container")
            if isinstance(symbol_panel, Tag):
                _add_class_token(
                    symbol_panel,
                    "layout-profile-scp-6183-symbol-panel",
                )
                for property_name, value in (
                    ("margin", "0"),
                    ("padding", "1.5em 1em 0"),
                    ("background", "#000"),
                    ("text-align", "center"),
                ):
                    _append_style_declaration(symbol_panel, property_name, value)

        notice_heading = next(
            (
                heading
                for heading in content.find_all("h2")
                if _normalized_text(heading) == "本文档已被标记为待删除"
            ),
            None,
        )
        if notice_heading is not None:
            parent = notice_heading.parent
            notice = (
                parent
                if isinstance(parent, Tag) and parent is not content
                else notice_heading
            )
            _add_class_token(notice, "layout-profile-scp-6183-deletion-notice")
            for property_name, value in (
                ("padding", "0.75em 1em 1.5em"),
                ("background", "#000"),
                ("color", "#d8d8d8"),
                ("text-align", "center"),
            ):
                _append_style_declaration(notice, property_name, value)
            _append_style_declaration(notice, "margin", "0 0 1.5em")
            _append_style_declaration(notice_heading, "color", "#d8d8d8")
            _append_style_declaration(notice_heading, "font-size", "1.15em")
            if notice is not notice_heading:
                _append_style_declaration(notice_heading, "margin", "0")
            classification = content.select_one(".anom-bar-esoteric")
            sibling = notice.next_sibling
            while sibling is not None and sibling is not classification:
                next_sibling = sibling.next_sibling
                if (
                    isinstance(sibling, Tag)
                    and sibling.name == "p"
                    and not sibling.get_text(" ", strip=True)
                ):
                    sibling.decompose()
                sibling = next_sibling

    for image_block in page_content.select("table .scp-image-block"):
        _stabilize_profile_image_block(
            image_block,
            "layout-profile-scp-6183-table-image",
        )


def _apply_scp_4612_layout_profile(page_content: Tag) -> None:
    _normalize_scp_4612_classification(page_content)

    image_blocks = page_content.select(".scp-image-block.block-right")
    if image_blocks:
        _stabilize_scp_4612_intro_image(image_blocks[0])
    for image_block in image_blocks[1:]:
        _stabilize_profile_image_block(
            image_block,
            "layout-profile-scp-4612-image",
        )


def _normalize_scp_4612_classification(page_content: Tag) -> None:
    classification = page_content.select_one("table.scale")
    if classification is None:
        return

    _add_class_token(classification, "layout-profile-scp-4612-classification")
    for property_name, value in (
        ("width", "100%"),
        ("max-width", "100%"),
        ("table-layout", "fixed"),
        ("border-collapse", "collapse"),
        ("page-break-inside", "avoid"),
        ("break-inside", "avoid"),
    ):
        _append_style_declaration(classification, property_name, value)

    clearance_cell = classification.select_one("td.class1")
    decoration_cell = classification.select_one("td.class1image")
    item_cell = classification.select_one("td.item1")

    if clearance_cell is not None:
        _stabilize_scp_4612_classification_cell(clearance_cell, "34%", "left")
        level_spans = clearance_cell.select(".base")
        for duplicate in level_spans[1:]:
            duplicate.decompose()
        if level_spans:
            _append_style_declaration(level_spans[0], "display", "inline")
        clearance_headings = clearance_cell.find_all("h1")
        if clearance_headings:
            _stabilize_scp_4612_classification_heading(clearance_headings[0], "1.65em")
        for heading in clearance_headings[1:]:
            _stabilize_scp_4612_classification_heading(heading, "1.45em")

    if decoration_cell is not None:
        _stabilize_scp_4612_classification_cell(decoration_cell, "12%", "center")
        for image in decoration_cell.find_all("img"):
            _append_style_declaration(image, "display", "block")
            _append_style_declaration(image, "width", "4em")
            _append_style_declaration(image, "max-width", "100%")
            _append_style_declaration(image, "height", "auto")
            _append_style_declaration(image, "margin", "0 auto")

    if item_cell is not None:
        _stabilize_scp_4612_classification_cell(item_cell, "54%", "right")
        for heading in item_cell.find_all("h1"):
            _stabilize_scp_4612_classification_heading(heading, "1.25em")


def _stabilize_scp_4612_classification_cell(
    cell: Tag,
    width: str,
    text_align: str,
) -> None:
    _append_style_declaration(cell, "width", width)
    _append_style_declaration(cell, "white-space", "normal")
    _append_style_declaration(cell, "vertical-align", "middle")
    _append_style_declaration(cell, "text-align", text_align)
    _append_style_declaration(cell, "padding", "0.25em")


def _stabilize_scp_4612_classification_heading(
    heading: Tag,
    font_size: str,
) -> None:
    _append_style_declaration(heading, "font-size", font_size)
    _append_style_declaration(heading, "line-height", "1.2")
    _append_style_declaration(heading, "margin", "0.2em 0")
    _append_style_declaration(heading, "transform", "none")
    _append_style_declaration(heading, "overflow-wrap", "anywhere")


def _stabilize_scp_4612_intro_image(image_block: Tag) -> None:
    _add_class_token(image_block, "layout-profile-scp-4612-intro-image")
    _append_style_declaration(image_block, "float", "right")
    _append_style_declaration(image_block, "clear", "right")
    _append_style_declaration(image_block, "max-width", "45%")
    for image in image_block.find_all("img"):
        _append_style_declaration(image, "max-width", "100%")
        _append_style_declaration(image, "height", "auto")


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
            ".layout-profile-scp-6183-intermission {margin: 1.5em 0 0; padding: 2em 1em; "
            "background: #000; color: #d8d8d8; text-align: center;}"
            "\n.layout-profile-scp-6183-intermission p {margin: 0.25em 0;}"
            "\n.layout-profile-scp-6183-intermission .cond {font-size: 1em; line-height: 1.2;}"
            "\n.layout-profile-scp-6183-intermission .ctrl {font-size: 2em; line-height: 1.2; "
            "letter-spacing: 0; word-spacing: normal;}"
            "\n.layout-profile-scp-6183-symbol-panel {margin: 0; padding: 1.5em 1em 0; "
            "background: #000; text-align: center;}"
            "\n.layout-profile-scp-6183-symbol {display: block; width: 20%; max-width: 10rem; "
            "height: auto; margin: 0 auto; transform: rotate(180deg);}"
            "\n.layout-profile-scp-6183-deletion-notice {margin: 0 0 1.5em; "
            "padding: 0.75em 1em 1.5em; background: #000; color: #d8d8d8; text-align: center;}"
            "\n.layout-profile-scp-6183-deletion-notice h2 {margin: 0; color: #d8d8d8; "
            "font-size: 1.15em;}"
            "\nh2.layout-profile-scp-6183-deletion-notice {margin: 0 0 1.5em; color: #d8d8d8; "
            "font-size: 1.15em;}"
            "\n.layout-profile-scp-6183-table-image {float: none; clear: both; max-width: 100%;}"
            "\n.layout-profile-scp-6183-table-image img {max-width: 100%; height: auto;}"
        ),
    ),
    "scp-4612": LayoutProfileRule(
        apply=_apply_scp_4612_layout_profile,
        style_rules=(
            ".layout-profile-scp-4612-classification {width: 100%; max-width: 100%; "
            "table-layout: fixed; border-collapse: collapse; page-break-inside: avoid; break-inside: avoid;}"
            "\n.layout-profile-scp-4612-classification td {vertical-align: middle; border: 0;}"
            "\n.layout-profile-scp-4612-classification .class1, "
            ".layout-profile-scp-4612-classification .item1 {white-space: normal;}"
            "\n.layout-profile-scp-4612-classification h1 {line-height: 1.2; margin: 0.2em 0; "
            "transform: none; overflow-wrap: anywhere;}"
            "\n.layout-profile-scp-4612-intro-image {float: right; clear: right; max-width: 45%;}"
            "\n.layout-profile-scp-4612-intro-image img {max-width: 100%; height: auto;}"
            "\n.layout-profile-scp-4612-image {float: none; clear: both; max-width: 100%;}"
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
