from __future__ import annotations

import base64
import binascii
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
import tinycss2

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
_WIKIDOT_TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{\$[A-Za-z0-9_-]+\}")

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
_SCP_6183_SYMBOL_CLASS = "layout-profile-scp-6183-symbol"
_SCP_6183_SYMBOL_MAX_PIXELS = 2048 * 2048
_SCP_6183_SYMBOL_VARIANT = "scp6183-symbol"
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
    scp6183_symbol_replacements: dict[str, str] = {}
    invalid_hrefs: set[str] = set()
    invalid_scp6183_symbol_hrefs: set[str] = set()
    merged_missing = list(missing_assets)
    seen_missing = set(merged_missing)
    expected_image_hrefs = _expected_image_hrefs(pages)
    opaque_rotated_hrefs = _scp6183_symbol_hrefs(pages)

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

        if asset.href not in opaque_rotated_hrefs:
            continue
        symbol_variant = _prepare_kindle_asset(
            asset,
            output_dir,
            expects_image=True,
            opaque_black_rotation=True,
        )
        if symbol_variant is None:
            invalid_scp6183_symbol_hrefs.add(asset.href)
            if asset.source_url not in seen_missing:
                seen_missing.add(asset.source_url)
                merged_missing.append(asset.source_url)
            continue
        prepared_assets.append(symbol_variant)
        scp6183_symbol_replacements[asset.href] = symbol_variant.href

    prepared_pages = [
        _rewrite_kindle_asset_references(
            page,
            href_replacements,
            invalid_hrefs,
            scp6183_symbol_replacements=scp6183_symbol_replacements,
            invalid_scp6183_symbol_hrefs=invalid_scp6183_symbol_hrefs,
        )
        for page in pages
    ]
    return prepared_pages, prepared_assets, merged_missing


def _prepare_kindle_asset(
    asset: AssetRef,
    output_dir: Path,
    *,
    expects_image: bool = False,
    opaque_black_rotation: bool = False,
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
        svg_data = _sanitize_svg_data(data) if expects_image else None
        svg_root = _parse_safe_svg(svg_data) if svg_data is not None else None
        if svg_root is not None:
            if not _svg_references_are_safe(svg_root):
                return None
            rendered = _render_svg_png(svg_data, svg_root)
            if rendered is None:
                return None
            if opaque_black_rotation:
                rendered = _render_opaque_black_rotated_png(rendered)
                if rendered is None:
                    return None
                return _write_prepared_png(
                    asset,
                    output_dir,
                    rendered,
                    variant=_SCP_6183_SYMBOL_VARIANT,
                )
            return _write_prepared_png(asset, output_dir, rendered)
        return None if expects_raster else asset

    if opaque_black_rotation:
        rendered = _render_opaque_black_rotated_png(data)
        if rendered is None:
            return None
        return _write_prepared_png(
            asset,
            output_dir,
            rendered,
            variant=_SCP_6183_SYMBOL_VARIANT,
        )

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


def _write_prepared_png(
    asset: AssetRef,
    output_dir: Path,
    data: bytes,
    *,
    variant: str | None = None,
) -> AssetRef:
    digest = hashlib.sha256(asset.source_url.encode("utf-8")).hexdigest()[:12]
    stem = Path(asset.href).stem or "image"
    variant_suffix = f"-{variant}" if variant else ""
    filename = f"{stem}-{digest}{variant_suffix}.png"
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


_SVG_EXTERNAL_DOCTYPE_RE = re.compile(
    r"""<!DOCTYPE\s+svg\s+(?:PUBLIC\s+(?:"[^"]*"|'[^']*')\s+(?:"[^"]*"|'[^']*')|SYSTEM\s+(?:"[^"]*"|'[^']*'))\s*>""",
    re.IGNORECASE,
)
_XML_DECLARATION_PREFIX_RE = re.compile(
    r"""\A\s*(?:<\?xml\b[^?]*\?>\s*)?\Z""",
    re.IGNORECASE | re.DOTALL,
)


def _sanitize_svg_data(data: bytes) -> bytes | None:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if "<!doctype" not in text.casefold():
        return data

    match = _SVG_EXTERNAL_DOCTYPE_RE.search(text)
    if (
        match is None
        or _XML_DECLARATION_PREFIX_RE.fullmatch(text[: match.start()]) is None
        or "<!doctype" in text[match.end() :].casefold()
    ):
        return None
    return (text[: match.start()] + text[match.end() :]).encode("utf-8")


_XML_BASE_ATTRIBUTE = "{http://www.w3.org/XML/1998/namespace}base"
_DATA_IMAGE_RE = re.compile(
    r"\Adata:image/(?P<format>png|jpeg|gif|webp);base64,(?P<payload>.*)\Z",
    re.IGNORECASE | re.DOTALL,
)


def _svg_references_are_safe(root: etree._Element) -> bool:
    for element in root.iter():
        for name, value in element.attrib.items():
            if name == _XML_BASE_ATTRIBUTE:
                return False
            local_name = etree.QName(name).localname
            if local_name == "href" and not _svg_reference_is_safe(value):
                return False
            if local_name == "style" and not _svg_css_is_safe(value, declarations=True):
                return False
        if etree.QName(element).localname == "style":
            css = "".join(element.itertext())
            if not _svg_css_is_safe(css, declarations=False):
                return False
    return True


def _svg_reference_is_safe(value: str) -> bool:
    if value.startswith("#"):
        return len(value) > 1 and not any(character.isspace() for character in value)

    match = _DATA_IMAGE_RE.fullmatch(value)
    if match is None:
        return False
    payload = re.sub(r"[\t\n\r\f ]+", "", match.group("payload"))
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return False
    expected_format = match.group("format").lower()
    if _raster_format(decoded) != expected_format:
        return False
    return _pillow_verifies(decoded)


def _svg_css_is_safe(css: str, *, declarations: bool) -> bool:
    if declarations:
        nodes = tinycss2.parse_declaration_list(
            css,
            skip_comments=True,
            skip_whitespace=True,
        )
    else:
        nodes = tinycss2.parse_stylesheet(
            css,
            skip_comments=True,
            skip_whitespace=True,
        )
    return _css_nodes_are_safe(nodes)


def _css_nodes_are_safe(nodes: Sequence[object]) -> bool:
    for node in nodes:
        node_type = getattr(node, "type", "")
        if node_type in {"error", "bad-string", "bad-url"}:
            return False
        if node_type == "url":
            if not _svg_reference_is_safe(str(node.value)):
                return False
            continue
        if node_type == "function" and getattr(node, "lower_name", "") == "url":
            reference = _css_url_function_reference(node.arguments)
            if reference is None or not _svg_reference_is_safe(reference):
                return False
            continue
        if node_type == "at-rule" and getattr(node, "lower_at_keyword", "") == "import":
            return False
        if node_type == "at-keyword" and str(getattr(node, "value", "")).lower() == "import":
            return False
        for attribute in ("value", "prelude", "content", "arguments"):
            children = getattr(node, attribute, None)
            if isinstance(children, list) and not _css_nodes_are_safe(children):
                return False
    return True


def _css_url_function_reference(arguments: Sequence[object]) -> str | None:
    values = [
        token
        for token in arguments
        if getattr(token, "type", "") not in {"comment", "whitespace"}
    ]
    if len(values) != 1:
        return None
    token = values[0]
    if getattr(token, "type", "") not in {"string", "url"}:
        return None
    return str(token.value)


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


def _scp6183_symbol_hrefs(pages: Sequence[ProcessedPage]) -> set[str]:
    hrefs: set[str] = set()
    for page in pages:
        if page.entry.slug != "scp-6183":
            continue
        parser = _parse_asset_references(page.xhtml)
        if parser is None:
            continue
        for element in parser.elements:
            if element.tag != "img":
                continue
            attrs = dict(element.attrs)
            classes = set(str(attrs.get("class") or "").split())
            if _SCP_6183_SYMBOL_CLASS not in classes:
                continue
            href = _local_asset_href(attrs.get("src"))
            if href is not None:
                hrefs.add(href)
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
    *,
    scp6183_symbol_replacements: dict[str, str] | None = None,
    invalid_scp6183_symbol_hrefs: set[str] | None = None,
) -> ProcessedPage:
    symbol_replacements = scp6183_symbol_replacements or {}
    invalid_symbol_hrefs = invalid_scp6183_symbol_hrefs or set()
    if (
        not href_replacements
        and not invalid_hrefs
        and not symbol_replacements
        and not invalid_symbol_hrefs
    ):
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
        classes = set(str(attrs.get("class") or "").split())
        is_scp6183_symbol = (
            page.entry.slug == "scp-6183"
            and element.tag == "img"
            and _SCP_6183_SYMBOL_CLASS in classes
        )
        if asset_href in invalid_hrefs or (
            is_scp6183_symbol and asset_href in invalid_symbol_hrefs
        ):
            edits.extend(_invalid_asset_edits(element, attrs, page.xhtml))
            continue
        replacement = (
            symbol_replacements.get(asset_href)
            if is_scp6183_symbol
            else href_replacements.get(asset_href)
        )
        if replacement is not None and attribute is not None:
            raw_tag = _replace_attribute_value(
                raw_tag,
                attribute,
                f"../{replacement}",
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
# Preserve the standard EPUB's intended scale: its 300px image default maps to
# the Kindle stylesheet's 42% reflowable default.
_STANDARD_IMAGE_WIDTH_PX = 300.0
_KINDLE_IMAGE_WIDTH_PERCENT = 42.0


@dataclass
class _HtmlElement:
    tag: str
    classes: frozenset[str]
    start_tag_start: int
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
        start_tag_start = self._offset()
        classes = frozenset(
            class_name
            for name, value in attrs
            if name == "class" and value
            for class_name in value.split()
        )
        element = _HtmlElement(
            tag=tag,
            classes=classes,
            start_tag_start=start_tag_start,
            start_tag_end=start_tag_start + len(raw_start_tag),
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
    return [
        replace(
            page,
            xhtml=_prepare_kindle_xhtml(
                page.xhtml,
                page_slug=page.entry.slug,
            ),
        )
        for page in pages
    ]


def _prepare_kindle_xhtml(xhtml: str, *, page_slug: str) -> str:
    parser = _XhtmlStructureParser(xhtml)
    try:
        parser.feed(xhtml)
        parser.close()
    except (AssertionError, ValueError):
        return xhtml

    edits: list[tuple[int, int, str]] = []
    for element in parser.elements:
        raw_start_tag = xhtml[element.start_tag_start : element.start_tag_end]
        prepared_start_tag = raw_start_tag
        if (
            page_slug == "scp-6183"
            and element.tag == "img"
            and _SCP_6183_SYMBOL_CLASS in element.classes
        ):
            prepared_start_tag = _set_inline_style_declaration(
                prepared_start_tag,
                "transform",
                "none",
            )
        width_mode = _kindle_component_width_mode(element)
        if width_mode is not None:
            prepared_start_tag = _normalize_fixed_pixel_width(
                prepared_start_tag,
                convert_to_percentage=width_mode == "percentage",
            )
        if prepared_start_tag != raw_start_tag:
            edits.append(
                (
                    element.start_tag_start,
                    element.start_tag_end,
                    prepared_start_tag,
                )
            )

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
        standard_clearance_label = _find_descendant(
            parser.elements,
            container,
            target_class="anomaly-clearance-label",
            ancestor_class="clearance",
        )
        if (
            clearance_text
            and clearance is not None
            and clearance.end_start is not None
        ):
            if (
                standard_clearance_label is not None
                and standard_clearance_label.end_start is not None
            ):
                edits.extend(
                    (
                        (
                            standard_clearance_label.start_tag_start,
                            standard_clearance_label.start_tag_end,
                            '<span class="kindle-clearance-label">',
                        ),
                        (
                            standard_clearance_label.start_tag_end,
                            standard_clearance_label.end_start,
                            clearance_text,
                        ),
                    )
                )
            elif not _element_text(clearance):
                edits.append(
                    (
                        clearance.end_start,
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
            and not _has_descendant_class(
                parser.elements, diamond, "anomaly-diamond-icon"
            )
        ):
            risk_text = _element_text(risk)
            if (
                risk_text
                and _WIKIDOT_TEMPLATE_PLACEHOLDER_RE.fullmatch(risk_text) is None
            ):
                edits.append(
                    (
                        diamond.start_tag_end,
                        diamond.start_tag_end,
                        '<span class="kindle-danger-label">'
                        f"{escape(risk_text, quote=False)}</span>",
                    )
                )

    result = xhtml
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def _kindle_component_width_mode(element: _HtmlElement) -> str | None:
    if any(name.startswith("layout-profile-") for name in element.classes):
        return None
    if "scp-image-block" in element.classes:
        return "percentage"
    if {"content-panel", "standalone"}.issubset(element.classes):
        return "remove"
    return None


def _render_opaque_black_rotated_png(data: bytes) -> bytes | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                image.seek(0)
                if image.width * image.height > _SCP_6183_SYMBOL_MAX_PIXELS:
                    return None
                image.load()
                rotated = image.convert("RGBA").transpose(Image.Transpose.ROTATE_180)
                opaque = Image.new("RGB", rotated.size, (0, 0, 0))
                opaque.paste(rotated.convert("RGB"), mask=rotated.getchannel("A"))
                output = io.BytesIO()
                opaque.save(output, format="PNG")
    except (
        OSError,
        UnidentifiedImageError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        return None
    return output.getvalue()


def _normalize_fixed_pixel_width(
    raw_start_tag: str,
    *,
    convert_to_percentage: bool,
) -> str:
    style_spans = _find_attribute_value_spans(raw_start_tag, "style")
    if style_spans is None:
        return raw_start_tag
    attribute_start, attribute_end, css_start, css_end = style_spans

    declarations = tinycss2.parse_declaration_list(
        raw_start_tag[css_start:css_end],
        skip_comments=False,
        skip_whitespace=False,
    )
    kept = []
    changed = False
    for declaration in declarations:
        if declaration.type == "declaration" and declaration.lower_name == "width":
            fixed_width = _fixed_pixel_width(declaration.value)
            if fixed_width is not None:
                changed = True
                if not convert_to_percentage:
                    continue
                width_px, width_token = fixed_width
                width_percent = min(
                    width_px / _STANDARD_IMAGE_WIDTH_PX
                    * _KINDLE_IMAGE_WIDTH_PERCENT,
                    100.0,
                )
                serialized_percent = f"{width_percent:.1f}".rstrip("0").rstrip(".")
                [percentage_token] = tinycss2.parse_component_value_list(
                    f"{serialized_percent}%"
                )
                declaration.value = [
                    percentage_token if token is width_token else token
                    for token in declaration.value
                ]
        kept.append(declaration)

    if not changed:
        return raw_start_tag

    prepared_css = tinycss2.serialize(kept).strip()
    if not prepared_css:
        return raw_start_tag[:attribute_start] + raw_start_tag[attribute_end:]

    return raw_start_tag[:css_start] + prepared_css + raw_start_tag[css_end:]


def _set_inline_style_declaration(
    raw_start_tag: str,
    property_name: str,
    value: str,
) -> str:
    style_spans = _find_attribute_value_spans(raw_start_tag, "style")
    if style_spans is None:
        closing_start = raw_start_tag.rfind("/>")
        if closing_start < 0:
            closing_start = raw_start_tag.rfind(">")
        if closing_start < 0:
            return raw_start_tag
        return (
            raw_start_tag[:closing_start]
            + f' style="{property_name}: {value}"'
            + raw_start_tag[closing_start:]
        )

    _attribute_start, _attribute_end, css_start, css_end = style_spans
    declarations = tinycss2.parse_declaration_list(
        raw_start_tag[css_start:css_end],
        skip_comments=False,
        skip_whitespace=False,
    )
    kept = [
        declaration
        for declaration in declarations
        if not (
            declaration.type == "declaration"
            and declaration.lower_name == property_name.casefold()
        )
    ]
    prepared_css = tinycss2.serialize(kept).strip()
    if prepared_css and not prepared_css.endswith(";"):
        prepared_css += ";"
    prepared_css += f" {property_name}: {value}"
    return raw_start_tag[:css_start] + prepared_css.strip() + raw_start_tag[css_end:]


def _find_attribute_value_spans(
    raw_start_tag: str,
    attribute_name: str,
) -> tuple[int, int, int, int] | None:
    length = len(raw_start_tag)
    index = 1
    while index < length and raw_start_tag[index].isspace():
        index += 1
    if index < length and raw_start_tag[index] == "/":
        index += 1
    while index < length and not raw_start_tag[index].isspace():
        if raw_start_tag[index] in "/>":
            return None
        index += 1

    target = attribute_name.casefold()
    while index < length:
        whitespace_start = index
        while index < length and raw_start_tag[index].isspace():
            index += 1
        if index >= length or raw_start_tag[index] in "/>":
            return None

        attribute_start = whitespace_start
        name_start = index
        while index < length and not raw_start_tag[index].isspace():
            if raw_start_tag[index] in "=/>":
                break
            index += 1
        name = raw_start_tag[name_start:index].casefold()

        while index < length and raw_start_tag[index].isspace():
            index += 1
        if index >= length or raw_start_tag[index] != "=":
            continue
        index += 1
        while index < length and raw_start_tag[index].isspace():
            index += 1
        if index >= length:
            return None

        quote = raw_start_tag[index]
        if quote in "'\"":
            index += 1
            value_start = index
            value_end = raw_start_tag.find(quote, index)
            if value_end < 0:
                return None
            index = value_end + 1
        else:
            value_start = index
            while index < length and not raw_start_tag[index].isspace():
                if raw_start_tag[index] == ">":
                    break
                index += 1
            value_end = index

        if name == target:
            return attribute_start, index, value_start, value_end

    return None


def _fixed_pixel_width(tokens: Sequence[object]) -> tuple[float, object] | None:
    meaningful = [
        token
        for token in tokens
        if getattr(token, "type", None) not in {"comment", "whitespace"}
    ]
    if len(meaningful) != 1:
        return None
    token = meaningful[0]
    if (
        getattr(token, "type", None) != "dimension"
        or getattr(token, "lower_unit", None) != "px"
    ):
        return None
    width = float(getattr(token, "value"))
    if width < 0 or not math.isfinite(width):
        return None
    return width, token


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
