from __future__ import annotations

import hashlib
import io
import math
import re
import shutil
import struct
import subprocess
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from html import escape, unescape
from html.parser import HTMLParser
from importlib import resources
from pathlib import Path

from lxml import etree
from PIL import Image, UnidentifiedImageError
import resvg_py

from .assets import AssetRef
from .models import ProcessedPage
from .transform import ASSET_ATTRIBUTES


CLEARANCE_LABELS = {
    "clear-1": "PUBLIC",
    "clear-2": "RESTRICTED",
    "clear-3": "CONFIDENTIAL",
    "clear-4": "SECRET",
    "clear-5": "TOP SECRET",
    "clear-6": "COSMIC TOP SECRET",
}

Runner = Callable[..., subprocess.CompletedProcess[str]]


class KindleConversionError(RuntimeError):
    pass


def convert_epub_to_azw3(
    epub_path: Path,
    azw3_path: Path,
    *,
    executable: str | Path | None = None,
    runner: Runner = subprocess.run,
) -> Path:
    if not epub_path.is_file():
        raise KindleConversionError(f"Kindle EPUB does not exist: {epub_path}")

    temporary_path = azw3_path.with_name(f"{azw3_path.stem}.tmp{azw3_path.suffix}")
    temporary_path.unlink(missing_ok=True)
    resolved = (
        str(executable)
        if executable is not None
        else shutil.which("ebook-convert")
    )
    if not resolved:
        raise KindleConversionError(
            "Calibre ebook-convert was not found; install Calibre and ensure "
            "ebook-convert is available on PATH"
        )

    azw3_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        resolved,
        str(epub_path),
        str(temporary_path),
        "--output-profile=kindle_scribe",
        "--no-inline-toc",
    ]

    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise KindleConversionError(
            f"Failed to start Calibre command {command!r}: {exc}"
        ) from exc

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    log_search_values = (
        stdout,
        stderr,
        stdout + stderr,
        f"{stdout.rstrip()} {stderr.lstrip()}",
    )
    details = "\n".join(
        value.strip()
        for value in (stdout, stderr)
        if value and value.strip()
    )[-2000:]
    if any("bad image file" in value.lower() for value in log_search_values):
        temporary_path.unlink(missing_ok=True)
        raise KindleConversionError(
            f"Calibre command {command!r} reported an invalid image: {details}"
        )

    if result.returncode != 0:
        temporary_path.unlink(missing_ok=True)
        raise KindleConversionError(
            f"Calibre command {command!r} exited with {result.returncode}: {details}"
        )

    if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
        temporary_path.unlink(missing_ok=True)
        raise KindleConversionError(
            f"Calibre command {command!r} did not produce a nonempty AZW3"
        )

    try:
        temporary_path.replace(azw3_path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise KindleConversionError(
            f"Could not atomically replace Kindle AZW3 {azw3_path}: {exc}"
        ) from exc
    return azw3_path


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_REMOVED_PNG_CHUNKS = frozenset({b"zTXt", b"iCCP"})
_RASTER_SUFFIXES = frozenset(
    {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
)
_SVG_LANDSCAPE_WIDTH = 1400
_SVG_PORTRAIT_HEIGHT = 1600


def prepare_kindle_assets(
    pages: Sequence[ProcessedPage],
    assets: Sequence[AssetRef],
    output_dir: Path,
    missing_assets: Sequence[str] = (),
) -> tuple[list[ProcessedPage], list[AssetRef], list[str]]:
    """Validate and normalize raster assets for Calibre's AZW3 writer."""
    prepared_assets: list[AssetRef] = []
    href_replacements: dict[str, str] = {}
    invalid_hrefs: set[str] = set()
    merged_missing = list(missing_assets)
    seen_missing = set(merged_missing)
    expected_image_hrefs = _expected_image_hrefs(pages)

    for asset in assets:
        prepared = _prepare_kindle_asset(
            asset,
            output_dir,
            expects_image=asset.href in expected_image_hrefs,
        )
        if prepared is None:
            invalid_hrefs.add(asset.href)
            if asset.source_url not in seen_missing:
                seen_missing.add(asset.source_url)
                merged_missing.append(asset.source_url)
            continue
        prepared_assets.append(prepared)
        if prepared.href != asset.href:
            href_replacements[asset.href] = prepared.href

    prepared_pages = [
        _rewrite_kindle_asset_references(page, href_replacements, invalid_hrefs)
        for page in pages
    ]
    return prepared_pages, prepared_assets, merged_missing


def _prepare_kindle_asset(
    asset: AssetRef,
    output_dir: Path,
    *,
    expects_image: bool = False,
) -> AssetRef | None:
    try:
        data = asset.path.read_bytes()
    except OSError:
        return None

    content_type = asset.content_type.split(";", 1)[0].strip().lower()
    if _looks_like_html(data) or content_type in {"text/html", "application/xhtml+xml"}:
        return None

    raster_format = _raster_format(data)
    expects_raster = expects_image or (
        content_type.startswith("image/") and content_type != "image/svg+xml"
    ) or asset.path.suffix.lower() in _RASTER_SUFFIXES
    if raster_format is None:
        svg_root = _parse_safe_svg(data) if expects_image else None
        if svg_root is not None:
            rendered = _render_svg_png(data, svg_root)
            if rendered is None:
                return None
            return _write_prepared_png(asset, output_dir, rendered)
        return None if expects_raster else asset

    if raster_format in {"jpeg", "gif"}:
        if not _pillow_verifies(data):
            return None
        expected_content_type = {
            "jpeg": "image/jpeg",
            "gif": "image/gif",
        }[raster_format]
        if content_type == expected_content_type:
            return asset
        return replace(asset, content_type=expected_content_type)

    if raster_format == "png":
        try:
            cleaned = _strip_png_metadata(data)
        except ValueError:
            return None
        if not _pillow_verifies(cleaned):
            return None
        if cleaned == data and content_type == "image/png":
            return asset
        return _write_prepared_png(asset, output_dir, cleaned)

    if raster_format in {"webp", "bmp"}:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    image.seek(0)
                    image.load()
                    output = io.BytesIO()
                    image.save(output, format="PNG")
        except (
            OSError,
            UnidentifiedImageError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            return None
        return _write_prepared_png(asset, output_dir, output.getvalue())

    return None


def _write_prepared_png(asset: AssetRef, output_dir: Path, data: bytes) -> AssetRef:
    digest = hashlib.sha256(asset.source_url.encode("utf-8")).hexdigest()[:12]
    stem = Path(asset.href).stem or "image"
    filename = f"{stem}-{digest}.png"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    output_path.write_bytes(data)
    return replace(
        asset,
        path=output_path,
        href=f"assets/{filename}",
        content_type="image/png",
    )


def _raster_format(data: bytes) -> str | None:
    if data.startswith(_PNG_SIGNATURE):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"BM"):
        return "bmp"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def _parse_safe_svg(data: bytes) -> etree._Element | None:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        recover=False,
        huge_tree=False,
    )
    try:
        root = etree.fromstring(data, parser=parser)
        if root.getroottree().docinfo.doctype:
            return None
        if etree.QName(root).localname != "svg":
            return None
        return root
    except (etree.XMLSyntaxError, ValueError):
        return None


def _render_svg_png(data: bytes, root: etree._Element) -> bytes | None:
    try:
        svg_string = data.decode("utf-8-sig")
        render_options, max_size = _svg_render_options(root)
        rendered = resvg_py.svg_to_bytes(
            svg_string=svg_string,
            dpi=96,
            **render_options,
        )
    except Exception:
        return None
    if not rendered.startswith(_PNG_SIGNATURE):
        return None
    if not _pillow_verifies(rendered, max_size=max_size):
        return None
    return rendered


def _svg_render_options(
    root: etree._Element,
) -> tuple[dict[str, int], tuple[int, int]]:
    aspect_ratio = _svg_aspect_ratio(root)
    if aspect_ratio >= 1:
        return (
            {"width": _SVG_LANDSCAPE_WIDTH},
            (_SVG_LANDSCAPE_WIDTH, _SVG_LANDSCAPE_WIDTH),
        )
    return (
        {"height": _SVG_PORTRAIT_HEIGHT},
        (_SVG_PORTRAIT_HEIGHT, _SVG_PORTRAIT_HEIGHT),
    )


def _svg_aspect_ratio(root: etree._Element) -> float:
    view_box = root.get("viewBox")
    if view_box:
        try:
            values = [float(value) for value in re.split(r"[\s,]+", view_box.strip())]
        except ValueError:
            values = []
        if (
            len(values) == 4
            and math.isfinite(values[2])
            and math.isfinite(values[3])
            and values[2] > 0
            and values[3] > 0
        ):
            return values[2] / values[3]

    width = _svg_length(root.get("width"))
    height = _svg_length(root.get("height"))
    if width is not None and height is not None:
        return width / height
    return 1.0


_SVG_LENGTH_RE = re.compile(
    r"\s*(?P<value>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"\s*(?P<unit>px|pt|pc|in|cm|mm|q)?\s*",
    re.IGNORECASE,
)
_SVG_LENGTH_TO_PX = {
    "": 1.0,
    "px": 1.0,
    "pt": 96 / 72,
    "pc": 16.0,
    "in": 96.0,
    "cm": 96 / 2.54,
    "mm": 96 / 25.4,
    "q": 96 / 101.6,
}


def _svg_length(value: str | None) -> float | None:
    if value is None:
        return None
    match = _SVG_LENGTH_RE.fullmatch(value)
    if match is None:
        return None
    length = float(match.group("value")) * _SVG_LENGTH_TO_PX[
        (match.group("unit") or "").lower()
    ]
    if not math.isfinite(length) or length <= 0:
        return None
    return length


def _looks_like_html(data: bytes) -> bool:
    prefix = data[:4096]
    if prefix.startswith(b"\xef\xbb\xbf"):
        prefix = prefix[3:]
    prefix = prefix.lstrip().lower()
    while True:
        if prefix.startswith(b"<?xml"):
            end = prefix.find(b"?>")
            if end < 0:
                return False
            prefix = prefix[end + 2 :].lstrip()
            continue
        if prefix.startswith(b"<!--"):
            end = prefix.find(b"-->")
            if end < 0:
                return False
            prefix = prefix[end + 3 :].lstrip()
            continue
        break
    return prefix.startswith(
        (b"<!doctype html", b"<html", b"<head", b"<body", b"<title")
    )


def _pillow_verifies(
    data: bytes, *, max_size: tuple[int, int] | None = None
) -> bool:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if max_size is not None and (
                    image.width > max_size[0] or image.height > max_size[1]
                ):
                    return False
                image.verify()
    except (
        OSError,
        UnidentifiedImageError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        return False
    return True


def _strip_png_metadata(data: bytes) -> bytes:
    if not data.startswith(_PNG_SIGNATURE):
        raise ValueError("not a PNG")

    output = bytearray(_PNG_SIGNATURE)
    offset = len(_PNG_SIGNATURE)
    chunk_types: list[bytes] = []
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("truncated PNG chunk")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("truncated PNG payload")
        chunk_type = data[offset + 4 : offset + 8]
        if len(chunk_type) != 4:
            raise ValueError("invalid PNG chunk type")
        chunk_types.append(chunk_type)
        if chunk_type not in _REMOVED_PNG_CHUNKS:
            output.extend(data[offset:end])
        offset = end
        if chunk_type == b"IEND":
            if offset != len(data):
                raise ValueError("data follows PNG IEND")
            break

    if not chunk_types or chunk_types[0] != b"IHDR":
        raise ValueError("PNG is missing IHDR")
    if b"IDAT" not in chunk_types or not chunk_types or chunk_types[-1] != b"IEND":
        raise ValueError("PNG is missing image data or IEND")
    return bytes(output)


@dataclass
class _AssetHtmlElement:
    tag: str
    attrs: tuple[tuple[str, str | None], ...]
    start: int
    start_end: int
    parent: _AssetHtmlElement | None
    end_start: int | None = None
    end_end: int | None = None


class _AssetReferenceParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.elements: list[_AssetHtmlElement] = []
        self._stack: list[_AssetHtmlElement] = []
        self._line_starts = [0]
        self._line_starts.extend(
            index + 1 for index, value in enumerate(source) if value == "\n"
        )

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        element = self._new_element(tag, attrs)
        if tag not in _VOID_ELEMENTS:
            self._stack.append(element)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._new_element(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        start = self._offset()
        end = start + len(f"</{tag}>")
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag != tag:
                continue
            self._stack[index].end_start = start
            self._stack[index].end_end = end
            del self._stack[index:]
            return

    def _new_element(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> _AssetHtmlElement:
        start = self._offset()
        element = _AssetHtmlElement(
            tag=tag,
            attrs=tuple(attrs),
            start=start,
            start_end=start + len(self.get_starttag_text()),
            parent=self._stack[-1] if self._stack else None,
        )
        self.elements.append(element)
        return element

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column


_ATTRIBUTE_VALUE_RE_TEMPLATE = (
    r"(?P<prefix>(?<![\w:-]){attribute}\s*=\s*)"
    r"(?:(?P<quote>[\"'])(?P<quoted>.*?)(?P=quote)|(?P<bare>[^\s>]+))"
)
_CSS_URL_RE = re.compile(
    r"url\(\s*(?P<quote>[\"']?)(?P<url>.*?)(?P=quote)\s*\)",
    re.IGNORECASE,
)


def _expected_image_hrefs(pages: Sequence[ProcessedPage]) -> set[str]:
    hrefs: set[str] = set()
    for page in pages:
        parser = _parse_asset_references(page.xhtml)
        if parser is None:
            continue
        for element in parser.elements:
            attrs = dict(element.attrs)
            is_picture_source = (
                element.tag == "source"
                and element.parent is not None
                and element.parent.tag == "picture"
            )
            if element.tag == "img" or is_picture_source:
                href = _local_asset_href(attrs.get("src"))
                if href is not None:
                    hrefs.add(href)
            style = attrs.get("style")
            if style:
                hrefs.update(_background_asset_hrefs(style))
    return hrefs


def _parse_asset_references(xhtml: str) -> _AssetReferenceParser | None:
    parser = _AssetReferenceParser(xhtml)
    try:
        parser.feed(xhtml)
        parser.close()
    except (AssertionError, ValueError):
        return None
    return parser


def _local_asset_href(value: str | None) -> str | None:
    if not value or not value.startswith("../"):
        return None
    return value[3:].replace("\\", "/")


def _background_asset_hrefs(style: str) -> set[str]:
    hrefs: set[str] = set()
    for declaration in style.split(";"):
        property_name, separator, value = declaration.partition(":")
        if not separator or not property_name.strip().lower().startswith("background"):
            continue
        for match in _CSS_URL_RE.finditer(value):
            href = _local_asset_href(match.group("url"))
            if href is not None:
                hrefs.add(href)
    return hrefs


def _rewrite_kindle_asset_references(
    page: ProcessedPage,
    href_replacements: dict[str, str],
    invalid_hrefs: set[str],
) -> ProcessedPage:
    if not href_replacements and not invalid_hrefs:
        return page

    parser = _parse_asset_references(page.xhtml)
    if parser is None:
        return page
    edits: list[tuple[int, int, str]] = []
    for element in parser.elements:
        raw_tag = page.xhtml[element.start : element.start_end]
        attrs = dict(element.attrs)
        attribute = ASSET_ATTRIBUTES.get(element.tag)
        asset_href = _local_asset_href(attrs.get(attribute)) if attribute else None
        if asset_href in invalid_hrefs:
            edits.extend(_invalid_asset_edits(element, attrs, page.xhtml))
            continue
        if asset_href in href_replacements and attribute is not None:
            raw_tag = _replace_attribute_value(
                raw_tag,
                attribute,
                f"../{href_replacements[asset_href]}",
            )

        style = attrs.get("style")
        if style:
            rewritten_style = _rewrite_background_style(
                style, href_replacements, invalid_hrefs
            )
            if rewritten_style != style:
                raw_tag = _replace_attribute_value(raw_tag, "style", rewritten_style)

        if raw_tag != page.xhtml[element.start : element.start_end]:
            edits.append((element.start, element.start_end, raw_tag))

    if not edits:
        return page
    return replace(page, xhtml=_apply_text_edits(page.xhtml, edits))


def _replace_attribute_value(raw_tag: str, attribute: str, value: str) -> str:
    pattern = re.compile(
        _ATTRIBUTE_VALUE_RE_TEMPLATE.format(attribute=re.escape(attribute)),
        re.IGNORECASE | re.DOTALL,
    )

    def replacement(match: re.Match[str]) -> str:
        quote = match.group("quote") or '"'
        return f"{match.group('prefix')}{quote}{value}{quote}"

    return pattern.sub(replacement, raw_tag, count=1)


def _rewrite_background_style(
    style: str,
    href_replacements: dict[str, str],
    invalid_hrefs: set[str],
) -> str:
    parts = style.split(";")
    rewritten: list[str] = []
    for part in parts:
        property_name, separator, _value = part.partition(":")
        if separator and property_name.strip().lower().startswith("background"):
            if any(f"../{href}" in part for href in invalid_hrefs):
                continue
            for old_href, new_href in href_replacements.items():
                part = part.replace(f"../{old_href}", f"../{new_href}")
        rewritten.append(part)
    return ";".join(rewritten)


def _invalid_asset_edits(
    element: _AssetHtmlElement,
    attrs: dict[str, str | None],
    xhtml: str,
) -> list[tuple[int, int, str]]:
    if element.tag == "object" and element.end_start is not None and element.end_end is not None:
        if xhtml[element.start_end : element.end_start].strip():
            return [
                (element.end_start, element.end_end, ""),
                (element.start, element.start_end, ""),
            ]
    label = str(attrs.get("alt") or attrs.get("title") or "").strip()
    if label:
        replacement = (
            '<span class="kindle-missing-image">'
            f"{escape(label)}"
            "</span>"
        )
    else:
        replacement = ""
    end = element.end_end if element.tag == "object" and element.end_end else element.start_end
    return [(element.start, end, replacement)]


def _apply_text_edits(source: str, edits: list[tuple[int, int, str]]) -> str:
    result = source
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result

_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


@dataclass
class _HtmlElement:
    tag: str
    classes: frozenset[str]
    start_tag_end: int
    parent: _HtmlElement | None
    end_start: int | None = None
    text_parts: list[str] = field(default_factory=list)


class _XhtmlStructureParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.elements: list[_HtmlElement] = []
        self._stack: list[_HtmlElement] = []
        self._line_starts = [0]
        self._line_starts.extend(
            index + 1 for index, value in enumerate(source) if value == "\n"
        )

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        element = self._new_element(tag, attrs)
        if tag not in _VOID_ELEMENTS:
            self._stack.append(element)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._new_element(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        end_start = self._offset()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag != tag:
                continue
            self._stack[index].end_start = end_start
            del self._stack[index:]
            return

    def handle_data(self, data: str) -> None:
        self._append_text(data)

    def handle_entityref(self, name: str) -> None:
        self._append_text(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append_text(f"&#{name};")

    def _new_element(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> _HtmlElement:
        raw_start_tag = self.get_starttag_text()
        classes = frozenset(
            class_name
            for name, value in attrs
            if name == "class" and value
            for class_name in value.split()
        )
        element = _HtmlElement(
            tag=tag,
            classes=classes,
            start_tag_end=self._offset() + len(raw_start_tag),
            parent=self._stack[-1] if self._stack else None,
        )
        self.elements.append(element)
        return element

    def _append_text(self, value: str) -> None:
        for element in self._stack:
            element.text_parts.append(value)

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column


def load_kindle_css() -> str:
    return (
        resources.files("scp_epub")
        .joinpath("styles/kindle.css")
        .read_text(encoding="utf-8")
    )


def prepare_kindle_pages(pages: Sequence[ProcessedPage]) -> list[ProcessedPage]:
    return [replace(page, xhtml=_prepare_kindle_xhtml(page.xhtml)) for page in pages]


def _prepare_kindle_xhtml(xhtml: str) -> str:
    parser = _XhtmlStructureParser(xhtml)
    try:
        parser.feed(xhtml)
        parser.close()
    except (AssertionError, ValueError):
        return xhtml

    insertions: list[tuple[int, str]] = []
    for container in (
        element
        for element in parser.elements
        if "anom-bar-container" in element.classes
    ):
        clearance_text = next(
            (
                label
                for class_name, label in CLEARANCE_LABELS.items()
                if class_name in container.classes
            ),
            None,
        )
        clearance = _find_descendant(
            parser.elements,
            container,
            target_class="clearance",
            ancestor_class="top-right-box",
        )
        if (
            clearance_text
            and clearance is not None
            and clearance.end_start is not None
            and not _element_text(clearance)
        ):
            insertions.append(
                (
                    clearance.end_start,
                    '<span class="kindle-clearance-label">'
                    f"{clearance_text}</span>",
                )
            )

        risk = _find_descendant(
            parser.elements,
            container,
            target_class="class-text",
            ancestor_class="risk-class",
        )
        diamond = _find_descendant(
            parser.elements,
            container,
            target_class="danger-diamond",
        )
        if (
            risk is not None
            and diamond is not None
            and not _has_descendant_class(
                parser.elements, diamond, "kindle-danger-label"
            )
        ):
            risk_text = _element_text(risk)
            if risk_text:
                insertions.append(
                    (
                        diamond.start_tag_end,
                        '<span class="kindle-danger-label">'
                        f"{escape(risk_text, quote=False)}</span>",
                    )
                )

    result = xhtml
    for offset, label in sorted(insertions, reverse=True):
        result = result[:offset] + label + result[offset:]
    return result


def _find_descendant(
    elements: Sequence[_HtmlElement],
    container: _HtmlElement,
    *,
    target_class: str,
    ancestor_class: str | None = None,
) -> _HtmlElement | None:
    for element in elements:
        if target_class not in element.classes or not _is_descendant(
            element, container
        ):
            continue
        if ancestor_class and not _has_ancestor_class(
            element, container, ancestor_class
        ):
            continue
        return element
    return None


def _has_descendant_class(
    elements: Sequence[_HtmlElement], container: _HtmlElement, class_name: str
) -> bool:
    return any(
        class_name in element.classes and _is_descendant(element, container)
        for element in elements
    )


def _is_descendant(element: _HtmlElement, container: _HtmlElement) -> bool:
    current = element.parent
    while current is not None:
        if current is container:
            return True
        current = current.parent
    return False


def _has_ancestor_class(
    element: _HtmlElement, container: _HtmlElement, class_name: str
) -> bool:
    current = element.parent
    while current is not None and current is not container:
        if class_name in current.classes:
            return True
        current = current.parent
    return False


def _element_text(element: _HtmlElement) -> str:
    return " ".join(unescape(" ".join(element.text_parts)).split())
