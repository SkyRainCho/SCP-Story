from __future__ import annotations

import re
from collections.abc import Iterable
from html import escape
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from scp_epub.models import PageRef, ProcessedPage
from scp_epub.urls import normalize_url, slug_from_url


NON_DOWNLOADABLE_ASSET_SCHEMES = {"data", "mailto", "tel"}
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
CSS_RULE_RE = re.compile(r"(?P<selectors>[^{}@][^{}]*)\{(?P<body>[^{}]*)\}")
CSS_CONTENT_PROPERTY_RE = re.compile(
    r"""(?:^|;)\s*content\s*:\s*(?P<value>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*(?=;|$)""",
    re.IGNORECASE | re.DOTALL,
)
CSS_ESCAPED_CHAR_RE = re.compile(r"\\(?P<escape>[0-9a-fA-F]{1,6}\s?|.)", re.DOTALL)
CSS_PSEUDO_RE = re.compile(r"::?[a-zA-Z-]+(?:\([^)]*\))?")
CSS_CLASS_SELECTOR_RE = re.compile(r"\.([_a-zA-Z][-_a-zA-Z0-9]*)")
CSS_ID_SELECTOR_RE = re.compile(r"#([_a-zA-Z][-_a-zA-Z0-9]*)")
UNSUPPORTED_PAGE_STYLE_SELECTOR_FRAGMENTS = (
    ".anom-bar",
    ".anom-bar-container",
    ".arrows",
    ".bottom-box",
    ".bottom-icon",
    ".class-category",
    ".class-text",
    ".clearance",
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
)
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

    page_styles = _applicable_page_styles(soup, page_content)

    for tag in list(page_content.find_all(_is_unwanted_element)):
        tag.decompose()

    _materialize_generated_before_content(soup, page_content, page_styles)
    _convert_grid_tables(soup, page_content)
    _stabilize_float_layout(soup, page_content)

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
    if page_styles:
        xhtml = f"<style>{escape(page_styles)}</style>\n{xhtml}"
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
    return tag.find(class_="scp-image-block") is not None


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
            selector for selector in selectors if not _is_unsupported_page_style_selector(selector)
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
    return any(fragment in lowered for fragment in UNSUPPORTED_PAGE_STYLE_SELECTOR_FRAGMENTS)


def _materialize_generated_before_content(
    soup: BeautifulSoup,
    page_content: Tag,
    page_styles: str,
) -> None:
    for match in CSS_RULE_RE.finditer(page_styles):
        content_value = _css_content_value(match.group("body"))
        if content_value is None:
            continue

        label_style = _sanitize_style_value(_style_without_content(match.group("body")))
        selectors = [
            selector.strip()
            for selector in match.group("selectors").split(",")
            if "::before" in selector.lower()
        ]
        for selector in selectors:
            base_selector = CSS_PSEUDO_RE.sub("", selector).strip()
            if base_selector.startswith("#page-content "):
                base_selector = base_selector[len("#page-content ") :].strip()
            if not base_selector or not _is_simple_generated_before_selector(base_selector):
                continue

            for target in page_content.select(base_selector):
                if target.find(class_="generated-before", recursive=False) is not None:
                    continue
                label = soup.new_tag("div")
                label["class"] = "generated-before"
                if label_style:
                    label["style"] = label_style
                label.string = content_value
                target.insert(0, label)


def _is_simple_generated_before_selector(selector: str) -> bool:
    if any(token in selector for token in (">", "+", "~", "*", "[", "]", ":")):
        return False
    return re.search(r"\s", selector) is None


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
        style = child.get("style")
        return isinstance(style, str) and "clear" in style.lower() and "both" in style.lower()
    return False


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
