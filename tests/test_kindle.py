import base64
import io
import re
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
import resvg_py
from PIL import Image

import scp_epub.kindle as kindle_module
from scp_epub.assets import AssetRef
from scp_epub.kindle import (
    KindleConversionError,
    convert_epub_to_azw3,
    load_kindle_css,
    prepare_kindle_pages,
)
from scp_epub.models import PageRef, ProcessedPage


def _page(xhtml: str, *, slug: str = "scp-001") -> ProcessedPage:
    return ProcessedPage(
        entry=PageRef(
            title="SCP-001",
            url=f"https://scp-wiki-cn.wikidot.com/{slug}",
            slug=slug,
            level=1,
            role="scp",
            order=1,
        ),
        xhtml=xhtml,
        asset_urls=(),
        internal_links=(),
        external_links=(),
    )


def _image_bytes(format_name: str, *, animated: bool = False) -> bytes:
    output = io.BytesIO()
    first = Image.new("RGBA", (2, 2), (255, 0, 0, 128))
    if animated:
        second = Image.new("RGBA", (2, 2), (0, 0, 255, 255))
        first.save(
            output,
            format=format_name,
            save_all=True,
            append_images=[second],
            duration=100,
            loop=0,
        )
    else:
        if format_name == "JPEG":
            first = first.convert("RGB")
        first.save(output, format=format_name)
    return output.getvalue()


def _palette_png_bytes() -> bytes:
    output = io.BytesIO()
    image = Image.new("P", (2, 2))
    image.putpalette([255, 0, 0, 0, 0, 255] + [0, 0, 0] * 254)
    image.putdata([0, 1, 0, 1])
    image.save(output, format="PNG", transparency=0)
    return output.getvalue()


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    chunks = []
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        chunks.append((chunk_type, payload))
        offset += length + 12
    return chunks


def _insert_png_chunks(data: bytes, chunks: list[tuple[bytes, bytes]]) -> bytes:
    ihdr_end = 8 + 12 + len(_png_chunks(data)[0][1])
    encoded = []
    for chunk_type, payload in chunks:
        checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        encoded.append(
            struct.pack(">I", len(payload))
            + chunk_type
            + payload
            + struct.pack(">I", checksum)
        )
    return data[:ihdr_end] + b"".join(encoded) + data[ihdr_end:]


def test_prepare_kindle_assets_drops_html_image_and_preserves_alt_text(tmp_path: Path):
    source_url = "https://example.test/missing.png"
    source_path = tmp_path / "missing.png"
    source_path.write_bytes(b"<!doctype html><html><body>404 Not Found</body></html>")
    source = _page(
        '<figure><img src="../assets/missing.png" alt="缺失的设施照片"/></figure>'
    )
    asset = AssetRef(source_url, source_path, "assets/missing.png", "image/png")

    pages, assets, missing = kindle_module.prepare_kindle_assets(
        [source], [asset], tmp_path / "kindle-assets", ["already-missing"]
    )

    assert assets == []
    assert missing == ["already-missing", source_url]
    assert "../assets/missing.png" not in pages[0].xhtml
    assert "缺失的设施照片" in pages[0].xhtml
    assert "kindle-missing-image" in pages[0].xhtml
    assert source.xhtml == (
        '<figure><img src="../assets/missing.png" alt="缺失的设施照片"/></figure>'
    )


def test_prepare_kindle_assets_preserves_inline_svg_bytes_while_editing_images(
    tmp_path: Path,
):
    svg = (
        '<svg viewBox="0 0 10 10" preserveAspectRatio="xMidYMid meet">'
        '<path d="M0 0 L10 10" /></svg>'
    )
    webp_path = tmp_path / "photo.webp"
    webp_path.write_bytes(_image_bytes("WEBP"))
    invalid_path = tmp_path / "missing.png"
    invalid_path.write_bytes(b"<!doctype html><title>404</title>")
    source = _page(
        svg
        + '<img data-src="lazy-preview" src="../assets/photo.webp" alt="有效图" />'
        + '<img src="../assets/missing.png" alt="缺失图" />'
    )

    [prepared_page], prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [source],
        [
            AssetRef(
                "https://example.test/photo.webp",
                webp_path,
                "assets/photo.webp",
                "image/webp",
            ),
            AssetRef(
                "https://example.test/missing.png",
                invalid_path,
                "assets/missing.png",
                "image/png",
            ),
        ],
        tmp_path / "kindle-assets",
        [],
    )

    assert svg in prepared_page.xhtml
    assert 'data-src="lazy-preview"' in prepared_page.xhtml
    assert f'../{prepared_assets[0].href}' in prepared_page.xhtml
    assert "../assets/photo.webp" not in prepared_page.xhtml
    assert "../assets/missing.png" not in prepared_page.xhtml
    assert "缺失图" in prepared_page.xhtml
    assert missing == ["https://example.test/missing.png"]


@pytest.mark.parametrize(
    "xhtml",
    [
        '<img src="../assets/broken.bin" alt="坏图"/>',
        '<picture><source src="../assets/broken.bin"/></picture>',
        '<div style="color: red; background-image: url(\'../assets/broken.bin\')">x</div>',
    ],
)
def test_prepare_kindle_assets_rejects_unsigned_octet_stream_used_as_image(
    tmp_path: Path, xhtml: str
):
    source_url = "https://example.test/broken.bin"
    source_path = tmp_path / "broken.bin"
    source_path.write_bytes(b"not an image")
    asset = AssetRef(
        source_url,
        source_path,
        "assets/broken.bin",
        "application/octet-stream",
    )

    [page], prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [_page(xhtml)], [asset], tmp_path / "kindle-assets", []
    )

    assert prepared_assets == []
    assert missing == [source_url]
    assert "../assets/broken.bin" not in page.xhtml


@pytest.mark.parametrize(
    ("container", "media_type"),
    [("audio", "audio/mpeg"), ("video", "video/mp4")],
)
def test_prepare_kindle_assets_preserves_octet_stream_media_source(
    tmp_path: Path, container: str, media_type: str
):
    source_url = f"https://example.test/{container}.bin"
    source_path = tmp_path / f"{container}.bin"
    source_path.write_bytes(b"opaque media bytes")
    href = f"assets/{container}.bin"
    asset = AssetRef(
        source_url,
        source_path,
        href,
        "application/octet-stream",
    )
    xhtml = (
        f'<{container} controls="controls">'
        f'<source src="../{href}" type="{media_type}" />'
        f'</{container}>'
    )

    [page], prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [_page(xhtml)], [asset], tmp_path / "kindle-assets", []
    )

    assert prepared_assets == [asset]
    assert missing == []
    assert page.xhtml == xhtml


@pytest.mark.parametrize(
    "payload",
    [
        b"\xef\xbb\xbf  <!doctype html><title>404</title>",
        b'<?xml version="1.0"?><html><title>404</title></html>',
        b"<!-- proxy error --><html><title>404</title></html>",
    ],
)
def test_html_sniffer_handles_wrappers_before_error_page(payload: bytes):
    assert kindle_module._looks_like_html(payload)


@pytest.mark.parametrize(
    ("xhtml", "payload"),
    [
        (
            '<img src="../assets/mark.svg" alt="标志"/>',
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">'
            b'<path d="M0 0h1v1z"/></svg>',
        ),
        (
            '<picture><source src="../assets/mark.svg" type="image/svg+xml"/>'
            '<img src="fallback.png" alt="标志"/></picture>',
            b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<!-- generated mark -->\n'
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>',
        ),
    ],
    ids=("img", "picture-source-with-xml-wrappers"),
)
def test_prepare_kindle_assets_renders_valid_svg_images_as_png(
    tmp_path: Path, xhtml: str, payload: bytes
):
    source_path = tmp_path / "mark.svg"
    source_path.write_bytes(payload)
    asset = AssetRef(
        "https://example.test/mark.svg",
        source_path,
        "assets/mark.svg",
        "application/octet-stream",
    )

    [page], [prepared], missing = kindle_module.prepare_kindle_assets(
        [_page(xhtml)], [asset], tmp_path / "kindle-assets", []
    )

    assert missing == []
    assert prepared.path != asset.path
    assert prepared.href != asset.href
    assert prepared.href.endswith(".png")
    assert prepared.content_type == "image/png"
    assert prepared.path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert source_path.read_bytes() == payload
    assert f'../{prepared.href}' in page.xhtml
    assert "../assets/mark.svg" not in page.xhtml
    with Image.open(prepared.path) as image:
        assert image.size == (1400, 1400)


def test_prepare_kindle_assets_renders_svg_with_embedded_png(tmp_path: Path):
    embedded_png = base64.b64encode(_image_bytes("PNG")).decode("ascii")
    payload = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 1">'
        f'<image width="2" height="1" href="data:image/png;base64,{embedded_png}"/>'
        "</svg>"
    ).encode("utf-8")
    source_path = tmp_path / "embedded.svg"
    source_path.write_bytes(payload)
    asset = AssetRef(
        "https://example.test/embedded.svg",
        source_path,
        "assets/embedded.svg",
        "image/svg+xml",
    )

    [page], [prepared], missing = kindle_module.prepare_kindle_assets(
        [_page('<img src="../assets/embedded.svg" alt="内嵌图片"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert missing == []
    assert prepared.content_type == "image/png"
    assert prepared.href.endswith(".png")
    assert f'../{prepared.href}' in page.xhtml
    with Image.open(prepared.path) as image:
        assert image.size == (1400, 700)
        image.verify()


@pytest.mark.parametrize(
    ("attribute", "reference"),
    [
        ("href", r"C:\secret\red.png"),
        ("href", "/etc/passwd"),
        ("href", "../red.png"),
        ("href", "red.png"),
        ("href", "file:///etc/passwd"),
        ("href", "http://example.test/red.png"),
        ("href", "https://example.test/red.png"),
        ("href", "//example.test/red.png"),
        ("xlink:href", "file:///etc/passwd"),
        ("href", "data:image/svg+xml;base64,PHN2Zy8+"),
        ("href", "data:text/plain;base64,cmVk"),
    ],
    ids=(
        "windows-absolute",
        "unix-absolute",
        "parent-relative",
        "plain-relative",
        "file-uri",
        "http-uri",
        "https-uri",
        "protocol-relative",
        "xlink-file-uri",
        "nested-svg-data",
        "non-image-data",
    ),
)
def test_prepare_kindle_assets_rejects_external_svg_href_before_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    reference: str,
):
    namespace = ' xmlns:xlink="http://www.w3.org/1999/xlink"' if attribute == "xlink:href" else ""
    payload = (
        f'<svg xmlns="http://www.w3.org/2000/svg"{namespace} viewBox="0 0 1 1">'
        f'<image {attribute}="{reference}" width="1" height="1"/></svg>'
    ).encode("utf-8")
    source_url = "https://example.test/external.svg"
    source_path = tmp_path / "external.svg"
    source_path.write_bytes(payload)
    asset = AssetRef(
        source_url,
        source_path,
        "assets/external.svg",
        "image/svg+xml",
    )
    renderer_calls = []

    def record_render(**kwargs):
        renderer_calls.append(kwargs)
        return _image_bytes("PNG")

    monkeypatch.setattr(resvg_py, "svg_to_bytes", record_render)

    [page], prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [_page('<img src="../assets/external.svg" alt="外部引用"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert renderer_calls == []
    assert prepared_assets == []
    assert missing == [source_url]
    assert "../assets/external.svg" not in page.xhtml
    assert "外部引用" in page.xhtml


@pytest.mark.parametrize(
    "xml_base",
    ["file:///etc/", "../images/"],
    ids=("absolute", "relative"),
)
def test_prepare_kindle_assets_rejects_svg_xml_base_before_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xml_base: str
):
    payload = (
        f'<svg xmlns="http://www.w3.org/2000/svg" xml:base="{xml_base}" '
        'viewBox="0 0 1 1"><rect width="1" height="1"/></svg>'
    ).encode("utf-8")
    source_url = "https://example.test/xml-base.svg"
    source_path = tmp_path / "xml-base.svg"
    source_path.write_bytes(payload)
    asset = AssetRef(
        source_url,
        source_path,
        "assets/xml-base.svg",
        "image/svg+xml",
    )
    renderer_calls = []
    monkeypatch.setattr(
        resvg_py,
        "svg_to_bytes",
        lambda **kwargs: renderer_calls.append(kwargs) or _image_bytes("PNG"),
    )

    _pages, prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [_page('<img src="../assets/xml-base.svg"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert renderer_calls == []
    assert prepared_assets == []
    assert missing == [source_url]


@pytest.mark.parametrize(
    "svg_content",
    [
        '<rect style="fill: url(file:///etc/passwd)"/>',
        '<style>.x { fill: url(https://example.test/red.png) }</style>',
        '<style>@import url("https://example.test/evil.css");</style>',
        r'<style>@im\70ort "https://example.test/evil.css";</style>',
        r'<rect style="fill: u\72l(&quot;file:///etc/passwd&quot;)"/>',
        '<rect style="fill: image-set(url(&quot;../red.png&quot;) 1x)"/>',
    ],
    ids=(
        "style-attribute-url",
        "style-element-url",
        "style-import",
        "escaped-import",
        "escaped-url",
        "nested-function-url",
    ),
)
def test_prepare_kindle_assets_rejects_external_svg_css_before_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, svg_content: str
):
    payload = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">'
        f"{svg_content}</svg>"
    ).encode("utf-8")
    source_url = "https://example.test/external-css.svg"
    source_path = tmp_path / "external-css.svg"
    source_path.write_bytes(payload)
    asset = AssetRef(
        source_url,
        source_path,
        "assets/external-css.svg",
        "image/svg+xml",
    )
    renderer_calls = []
    monkeypatch.setattr(
        resvg_py,
        "svg_to_bytes",
        lambda **kwargs: renderer_calls.append(kwargs) or _image_bytes("PNG"),
    )

    _pages, prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [_page('<img src="../assets/external-css.svg"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert renderer_calls == []
    assert prepared_assets == []
    assert missing == [source_url]


def test_prepare_kindle_assets_allows_internal_and_data_raster_svg_references(
    tmp_path: Path,
):
    embedded_png = base64.b64encode(_image_bytes("PNG")).decode("ascii")
    data_uri = f"data:image/png;base64,{embedded_png}"
    payload = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 2 1">'
        '<defs><linearGradient id="paint"><stop stop-color="red"/></linearGradient></defs>'
        f'<style>.fragment {{ fill: url(#paint) }} .data {{ background: url("{data_uri}") }}</style>'
        f'<image href="{data_uri}" width="1" height="1"/>'
        '<use xlink:href="#fragment"/><rect class="fragment" width="2" height="1"/>'
        '</svg>'
    ).encode("utf-8")
    source_path = tmp_path / "allowed-references.svg"
    source_path.write_bytes(payload)
    asset = AssetRef(
        "https://example.test/allowed-references.svg",
        source_path,
        "assets/allowed-references.svg",
        "image/svg+xml",
    )

    [page], [prepared], missing = kindle_module.prepare_kindle_assets(
        [_page('<img src="../assets/allowed-references.svg"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert missing == []
    assert prepared.content_type == "image/png"
    assert f'../{prepared.href}' in page.xhtml


@pytest.mark.parametrize(
    ("size_attributes", "expected_size"),
    [
        ('viewBox="0 0 4000 2000"', (1400, 700)),
        ('viewBox="0 0 3 2"', (1400, 934)),
        ('width="2000" height="4000"', (800, 1600)),
    ],
    ids=("landscape-viewbox", "landscape-rounded", "portrait-dimensions"),
)
def test_prepare_kindle_assets_bounds_svg_output_while_preserving_aspect_ratio(
    tmp_path: Path, size_attributes: str, expected_size: tuple[int, int]
):
    payload = (
        f'<svg xmlns="http://www.w3.org/2000/svg" {size_attributes}>'
        '<rect width="100%" height="100%" fill="black"/></svg>'
    ).encode("utf-8")
    source_path = tmp_path / "large.svg"
    source_path.write_bytes(payload)
    asset = AssetRef(
        "https://example.test/large.svg",
        source_path,
        "assets/large.svg",
        "image/svg+xml",
    )

    _pages, [prepared], missing = kindle_module.prepare_kindle_assets(
        [_page('<img src="../assets/large.svg"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert missing == []
    assert prepared.content_type == "image/png"
    with Image.open(prepared.path) as image:
        assert image.size == expected_size


def test_prepare_kindle_assets_drops_svg_when_renderer_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    payload = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 1"/>'
    source_url = "https://example.test/render-failure.svg"
    source_path = tmp_path / "render-failure.svg"
    source_path.write_bytes(payload)
    asset = AssetRef(
        source_url,
        source_path,
        "assets/render-failure.svg",
        "image/svg+xml",
    )
    calls = []

    def fail_render(**kwargs):
        calls.append(kwargs)
        raise ValueError("renderer rejected SVG")

    monkeypatch.setattr(resvg_py, "svg_to_bytes", fail_render)

    [page], prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [_page('<img src="../assets/render-failure.svg" alt="无法渲染"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert prepared_assets == []
    assert missing == [source_url]
    assert "../assets/render-failure.svg" not in page.xhtml
    assert "无法渲染" in page.xhtml
    assert len(calls) == 1
    assert calls[0]["svg_string"].startswith("<svg")
    assert calls[0]["dpi"] == 96
    assert calls[0]["width"] == 1400
    assert "height" not in calls[0]
    assert "svg_path" not in calls[0]
    assert "resources_dir" not in calls[0]


def test_prepare_kindle_assets_accepts_svg_with_external_public_doctype(
    tmp_path: Path,
):
    payload = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.0//EN" '
        b'"http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd">\n'
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 2">'
        b'<rect width="2" height="2" fill="#000000"/></svg>'
    )
    source_path = tmp_path / "legacy.svg"
    source_path.write_bytes(payload)
    asset = AssetRef(
        "https://example.test/legacy.svg",
        source_path,
        "assets/legacy.svg",
        "image/svg+xml",
    )

    [page], [prepared], missing = kindle_module.prepare_kindle_assets(
        [_page('<img src="../assets/legacy.svg" alt="旧版 SVG"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert missing == []
    assert prepared.content_type == "image/png"
    assert prepared.path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert f'../{prepared.href}' in page.xhtml
    assert source_path.read_bytes() == payload


def test_prepare_kindle_assets_rejects_decompression_bomb_from_svg_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    payload = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'
    source_url = "https://example.test/rendered-bomb.svg"
    source_path = tmp_path / "rendered-bomb.svg"
    source_path.write_bytes(payload)
    asset = AssetRef(
        source_url,
        source_path,
        "assets/rendered-bomb.svg",
        "image/svg+xml",
    )
    rendered_png = _image_bytes("PNG")
    monkeypatch.setattr(
        resvg_py, "svg_to_bytes", lambda **_kwargs: rendered_png
    )
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)

    [page], prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [_page('<img src="../assets/rendered-bomb.svg" alt="超限渲染"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert prepared_assets == []
    assert missing == [source_url]
    assert "../assets/rendered-bomb.svg" not in page.xhtml
    assert "超限渲染" in page.xhtml


@pytest.mark.parametrize(
    "payload",
    [
        b"<!doctype html><html><body><svg></svg></body></html>",
        b'<svg xmlns="http://www.w3.org/2000/svg"><path></svg>',
        b'<?xml version="1.0"?><document/>',
        (
            b'<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg"><text>&xxe;</text></svg>'
        ),
    ],
    ids=("html", "broken-svg", "non-svg-xml", "external-entity"),
)
def test_prepare_kindle_assets_rejects_unsafe_or_invalid_svg_images(
    tmp_path: Path, payload: bytes
):
    source_url = "https://example.test/broken.svg"
    source_path = tmp_path / "broken.svg"
    source_path.write_bytes(payload)
    asset = AssetRef(
        source_url,
        source_path,
        "assets/broken.svg",
        "image/svg+xml",
    )
    xhtml = '<img src="../assets/broken.svg" alt="损坏的图标"/>'

    [page], prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [_page(xhtml)], [asset], tmp_path / "kindle-assets", []
    )

    assert prepared_assets == []
    assert missing == [source_url]
    assert "../assets/broken.svg" not in page.xhtml
    assert "损坏的图标" in page.xhtml


def test_prepare_kindle_assets_preserves_non_image_xml_resource(tmp_path: Path):
    payload = b'<?xml version="1.0"?><document><title>Metadata</title></document>'
    source_path = tmp_path / "metadata.xml"
    source_path.write_bytes(payload)
    asset = AssetRef(
        "https://example.test/metadata.xml",
        source_path,
        "assets/metadata.xml",
        "application/xml",
    )
    xhtml = '<object data="../assets/metadata.xml">Metadata</object>'

    [page], prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [_page(xhtml)], [asset], tmp_path / "kindle-assets", []
    )

    assert prepared_assets == [asset]
    assert missing == []
    assert page.xhtml == xhtml
    assert source_path.read_bytes() == payload


@pytest.mark.parametrize(("format_name", "suffix"), [("WEBP", ".webp"), ("BMP", ".bin")])
def test_prepare_kindle_assets_transcodes_unsafe_rasters_and_rewrites_page(
    tmp_path: Path, format_name: str, suffix: str
):
    source_path = tmp_path / f"source{suffix}"
    source_path.write_bytes(_image_bytes(format_name))
    asset = AssetRef(
        f"https://example.test/source{suffix}",
        source_path,
        f"assets/source{suffix}",
        "application/octet-stream",
    )
    source = _page(f'<img src="../assets/source{suffix}" alt="图"/>')

    pages, assets, missing = kindle_module.prepare_kindle_assets(
        [source], [asset], tmp_path / "kindle-assets", []
    )

    assert missing == []
    assert len(assets) == 1
    prepared = assets[0]
    assert prepared.href.endswith(".png")
    assert prepared.content_type == "image/png"
    assert prepared.path.parent == tmp_path / "kindle-assets"
    assert prepared.path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert f'../{prepared.href}' in pages[0].xhtml
    assert f'../assets/source{suffix}' not in pages[0].xhtml


@pytest.mark.parametrize(
    "max_image_pixels",
    [1, 3],
    ids=("decompression-bomb-error", "decompression-bomb-warning"),
)
def test_prepare_kindle_assets_rejects_decompression_bomb_during_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_image_pixels: int,
):
    payload = _image_bytes("PNG")
    source_url = "https://example.test/oversized.png"
    source_path = tmp_path / "oversized.png"
    source_path.write_bytes(payload)
    asset = AssetRef(
        source_url,
        source_path,
        "assets/oversized.png",
        "image/png",
    )
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", max_image_pixels)

    [page], prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [_page('<img src="../assets/oversized.png" alt="超限图片"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert prepared_assets == []
    assert missing == [source_url]
    assert "../assets/oversized.png" not in page.xhtml
    assert "超限图片" in page.xhtml


@pytest.mark.parametrize("format_name", ["WEBP", "BMP"])
def test_prepare_kindle_assets_rejects_decompression_bomb_during_transcode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    format_name: str,
):
    payload = _image_bytes(format_name)
    suffix = format_name.lower()
    source_url = f"https://example.test/oversized.{suffix}"
    source_path = tmp_path / f"oversized.{suffix}"
    source_path.write_bytes(payload)
    asset = AssetRef(
        source_url,
        source_path,
        f"assets/oversized.{suffix}",
        f"image/{suffix}",
    )
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)

    [page], prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [_page(f'<img src="../assets/oversized.{suffix}" alt="超限图片"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert prepared_assets == []
    assert missing == [source_url]
    assert f"../assets/oversized.{suffix}" not in page.xhtml
    assert "超限图片" in page.xhtml


def test_prepare_kindle_assets_strips_problem_png_metadata_without_reencoding_pixels(
    tmp_path: Path,
):
    original = _palette_png_bytes()
    problem = _insert_png_chunks(
        original,
        [
            (b"zTXt", b"Comment\x00\x00not-zlib-data"),
            (b"iCCP", b"Broken profile\x00\x00not-zlib-data"),
        ],
    )
    source_path = tmp_path / "problem.png"
    source_path.write_bytes(problem)
    asset = AssetRef(
        "https://example.test/problem.png",
        source_path,
        "assets/problem.png",
        "image/png",
    )

    _pages, [prepared], missing = kindle_module.prepare_kindle_assets(
        [_page('<img src="../assets/problem.png"/>')],
        [asset],
        tmp_path / "kindle-assets",
        [],
    )

    assert missing == []
    chunks = _png_chunks(prepared.path.read_bytes())
    chunk_types = [chunk_type for chunk_type, _payload in chunks]
    assert b"zTXt" not in chunk_types
    assert b"iCCP" not in chunk_types
    for required in (b"IHDR", b"IDAT", b"IEND"):
        assert required in chunk_types
    assert [payload for kind, payload in chunks if kind == b"IDAT"] == [
        payload for kind, payload in _png_chunks(original) if kind == b"IDAT"
    ]
    for preserved in (b"PLTE", b"tRNS"):
        assert [payload for kind, payload in chunks if kind == preserved] == [
            payload for kind, payload in _png_chunks(original) if kind == preserved
        ]
    with Image.open(prepared.path) as image:
        image.verify()


def test_prepare_kindle_assets_flattens_and_rotates_scp6183_symbol(tmp_path: Path):
    source_image = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    source_image.putpixel((0, 0), (255, 0, 0, 255))
    source_image.putpixel((1, 1), (0, 255, 0, 128))
    source_bytes = io.BytesIO()
    source_image.save(source_bytes, format="PNG")
    source_path = tmp_path / "rsm.png"
    source_path.write_bytes(source_bytes.getvalue())
    asset = AssetRef(
        "https://example.test/scp-6183/rsm.png",
        source_path,
        "assets/rsm.png",
        "image/png",
    )
    page = _page(
        '<img id="symbol" class="layout-profile-scp-6183-symbol" '
        'src="../assets/rsm.png" alt="rsm.png"/>'
        '<img id="ordinary" src="../assets/rsm.png" alt="ordinary.png"/>',
        slug="scp-6183",
    )
    other_page = _page(
        '<img id="cross-page" src="../assets/rsm.png" alt="cross-page.png"/>',
        slug="scp-9999",
    )

    [prepared_page, prepared_other_page], prepared_assets, missing = (
        kindle_module.prepare_kindle_assets(
            [page, other_page], [asset], tmp_path / "kindle-assets", []
        )
    )

    assert missing == []
    assert len(prepared_assets) == 2
    prepared = next(item for item in prepared_assets if item.href != asset.href)
    assert asset in prepared_assets
    assert prepared.path != source_path
    assert prepared.href != asset.href
    assert (
        f'id="symbol" class="layout-profile-scp-6183-symbol" '
        f'src="../{prepared.href}"' in prepared_page.xhtml
    )
    assert 'id="ordinary" src="../assets/rsm.png"' in prepared_page.xhtml
    assert prepared_other_page == other_page
    with Image.open(prepared.path) as image:
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (0, 128, 0)
        assert image.getpixel((1, 1)) == (255, 0, 0)
        assert image.getpixel((1, 0)) == (0, 0, 0)
    with Image.open(source_path) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0)) == (255, 0, 0, 255)


def test_prepare_kindle_assets_applies_scp6183_variant_to_disguised_svg(
    tmp_path: Path,
):
    payload = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 2">'
        b'<rect x="0" y="0" width="1" height="1" fill="#ff0000"/>'
        b"</svg>"
    )
    source_path = tmp_path / "disguised.png"
    source_path.write_bytes(payload)
    asset = AssetRef(
        "https://example.test/scp-6183/disguised.png",
        source_path,
        "assets/disguised.png",
        "image/png",
    )
    page = _page(
        '<img id="symbol" class="layout-profile-scp-6183-symbol" '
        'src="../assets/disguised.png" alt="rsm.png"/>'
        '<img id="ordinary" src="../assets/disguised.png" alt="ordinary.png"/>',
        slug="scp-6183",
    )
    other_page = _page(
        '<img id="cross-page" src="../assets/disguised.png" alt="cross-page.png"/>',
        slug="scp-9999",
    )

    [prepared_page, prepared_other_page], prepared_assets, missing = (
        kindle_module.prepare_kindle_assets(
            [page, other_page], [asset], tmp_path / "kindle-assets", []
        )
    )

    assert missing == []
    assert len({item.href for item in prepared_assets}) == 2
    variant = next(
        item for item in prepared_assets if "scp6183-symbol" in item.href
    )
    ordinary = next(item for item in prepared_assets if item is not variant)
    assert f'id="symbol" class="layout-profile-scp-6183-symbol" src="../{variant.href}"' in prepared_page.xhtml
    assert f'id="ordinary" src="../{ordinary.href}"' in prepared_page.xhtml
    assert f'src="../{ordinary.href}"' in prepared_other_page.xhtml
    with Image.open(variant.path) as image:
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (0, 0, 0)
        assert image.getpixel((image.width - 1, image.height - 1))[0] > 200
    assert source_path.read_bytes() == payload


def test_prepare_kindle_assets_does_not_transform_scp6183_class_on_other_page(
    tmp_path: Path,
):
    source_path = tmp_path / "ordinary.png"
    source_path.write_bytes(_image_bytes("PNG"))
    asset = AssetRef(
        "https://example.test/ordinary.png",
        source_path,
        "assets/ordinary.png",
        "image/png",
    )
    page = _page(
        '<img class="layout-profile-scp-6183-symbol" '
        'src="../assets/ordinary.png" alt="ordinary.png"/>',
        slug="scp-9999",
    )

    [prepared_page], [prepared], missing = kindle_module.prepare_kindle_assets(
        [page], [asset], tmp_path / "kindle-assets", []
    )

    assert missing == []
    assert prepared == asset
    assert prepared_page == page
    assert prepared.path.read_bytes() == source_path.read_bytes()


def test_prepare_kindle_assets_rejects_oversized_scp6183_symbol_variant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source_url = "https://example.test/scp-6183/oversized-rsm.png"
    source_path = tmp_path / "oversized-rsm.png"
    source_path.write_bytes(_image_bytes("PNG"))
    asset = AssetRef(
        source_url,
        source_path,
        "assets/oversized-rsm.png",
        "image/png",
    )
    page = _page(
        '<img class="layout-profile-scp-6183-symbol" '
        'src="../assets/oversized-rsm.png" alt="删除标记"/>',
        slug="scp-6183",
    )
    monkeypatch.setattr(
        kindle_module,
        "_SCP_6183_SYMBOL_MAX_PIXELS",
        3,
        raising=False,
    )

    [prepared_page], prepared_assets, missing = kindle_module.prepare_kindle_assets(
        [page], [asset], tmp_path / "kindle-assets", []
    )

    assert prepared_assets == [asset]
    assert missing == [source_url]
    assert "layout-profile-scp-6183-symbol" not in prepared_page.xhtml
    assert "删除标记" in prepared_page.xhtml


def test_prepare_kindle_assets_preserves_jpeg_and_animated_gif_bytes(tmp_path: Path):
    assets = []
    original_bytes = {}
    for format_name, filename in (
        ("JPEG", "photo.jpg"),
        ("GIF", "animation.gif"),
    ):
        data = _image_bytes(format_name, animated=format_name == "GIF")
        path = tmp_path / filename
        path.write_bytes(data)
        original_bytes[filename] = data
        assets.append(
            AssetRef(
                f"https://example.test/{filename}",
                path,
                f"assets/{filename}",
                "application/octet-stream",
            )
        )

    _pages, prepared, missing = kindle_module.prepare_kindle_assets(
        [_page("<p>text only</p>")], assets, tmp_path / "kindle-assets", []
    )

    assert missing == []
    assert [asset.content_type for asset in prepared] == ["image/jpeg", "image/gif"]
    for source, asset in zip(assets, prepared, strict=True):
        assert asset.path == source.path
        assert asset.href == source.href
        assert asset.path.read_bytes() == original_bytes[asset.path.name]
    with Image.open(prepared[1].path) as animation:
        assert animation.n_frames == 2


def test_prepare_kindle_pages_materializes_anomaly_labels_without_mutating_source():
    source = _page(
        '<div class="anom-bar-container clear-4">'
        '<div class="top-right-box"><div class="clearance"></div></div>'
        '<div class="risk-class"><div class="class-text">危急</div></div>'
        '<div class="danger-diamond"><a href="memo.xhtml">备忘录</a></div>'
        "</div>"
    )

    [prepared] = prepare_kindle_pages([source])

    assert prepared is not source
    assert '<span class="kindle-clearance-label">SECRET</span>' in prepared.xhtml
    assert '<span class="kindle-danger-label">危急</span>' in prepared.xhtml
    assert 'href="memo.xhtml"' in prepared.xhtml
    assert "SECRET" not in source.xhtml
    assert "kindle-danger-label" not in source.xhtml


def test_prepare_kindle_pages_replaces_standard_clearance_label_with_kindle_label():
    source = _page(
        '<div class="anom-bar-container clear-4">'
        '<div class="top-right-box"><div class="clearance">'
        '<span class="anomaly-clearance-label">机密</span>'
        "</div></div></div>"
    )

    [prepared] = prepare_kindle_pages([source])

    assert '<span class="kindle-clearance-label">SECRET</span>' in prepared.xhtml
    assert "anomaly-clearance-label" not in prepared.xhtml
    assert ">机密<" not in prepared.xhtml
    assert "anomaly-clearance-label" in source.xhtml


def test_prepare_kindle_pages_does_not_materialize_unexpanded_anomaly_risk():
    source = _page(
        '<div class="anom-bar-container clear-3">'
        '<div class="risk-class"><div class="class-text">{$risk-class}</div></div>'
        '<div class="danger-diamond"></div>'
        "</div>"
    )

    [prepared] = prepare_kindle_pages([source])

    assert "kindle-danger-label" not in prepared.xhtml


def test_prepare_kindle_pages_prefers_real_anomaly_icon_over_fallback_risk_label():
    source = _page(
        '<div class="anom-bar-container clear-4">'
        '<div class="risk-class"><div class="class-text">critical</div></div>'
        '<div class="danger-diamond">'
        '<div class="right-icon"><img class="anomaly-diamond-icon" '
        'src="../assets/critical.svg" alt="critical 等级图标"/></div>'
        "</div></div>"
    )

    [prepared] = prepare_kindle_pages([source])

    assert "kindle-danger-label" not in prepared.xhtml
    assert "anomaly-diamond-icon" in prepared.xhtml


def test_prepare_kindle_pages_preserves_ordinary_xhtml_exactly():
    xhtml = (
        '<section><svg viewBox="0 0 10 10" preserveAspectRatio="xMidYMid meet">'
        '<path d="M0 0 L10 10" /></svg></section>\n'
    )

    [prepared] = prepare_kindle_pages([_page(xhtml)])

    assert prepared.xhtml == xhtml


def test_prepare_kindle_pages_normalizes_fixed_front_matter_panel_width():
    source = _page(
        '<div class="content-panel standalone" '
        'style="width: 575px; padding: 10px 30px; margin: 20px auto; '
        'background-image: url(../assets/marble.png)">'
        "<p>人类到如今已经繁衍了250000年。</p>"
        "</div>"
    )

    [prepared] = prepare_kindle_pages([source])

    assert "width:" not in prepared.xhtml
    assert "575px" not in prepared.xhtml
    assert "padding: 10px 30px" in prepared.xhtml
    assert "margin: 20px auto" in prepared.xhtml
    assert "background-image: url(../assets/marble.png)" in prepared.xhtml
    assert "width: 575px" in source.xhtml


@pytest.mark.parametrize(
    ("classes", "source_width", "expected_width"),
    [
        ("scp-image-block block-right", "200px", "28%"),
        ("scp-image-block block-left", "300px", "42%"),
        ("scp-image-block block-center", "500px", "70%"),
    ],
)
def test_prepare_kindle_pages_normalizes_fixed_image_block_width(
    classes: str, source_width: str, expected_width: str
):
    xhtml = (
        f'<div class="{classes}" style="width: {source_width}">'
        '<img src="../assets/gears.jpg" alt="gears.jpg"/>'
        '<div class="scp-image-caption"><p>图片说明</p></div>'
        "</div>"
    )

    [prepared] = prepare_kindle_pages([_page(xhtml)])

    assert f"width:{expected_width}" in prepared.xhtml.replace(" ", "")
    assert source_width not in prepared.xhtml


def test_prepare_kindle_pages_preserves_special_layout_profile_widths():
    xhtml = (
        '<div class="scp-image-block block-right layout-profile-scp-6183-table-image" '
        'style="float: none; width: 200px">图片</div>'
    )

    [prepared] = prepare_kindle_pages([_page(xhtml)])

    assert prepared.xhtml == xhtml


def test_prepare_kindle_pages_disables_runtime_rotation_for_scp6183_symbol():
    xhtml = (
        '<img class="image layout-profile-scp-6183-symbol" '
        'src="../assets/rsm.png" style="width: 20%; opacity: 70%" alt="rsm.png"/>'
    )

    [prepared] = prepare_kindle_pages([_page(xhtml, slug="scp-6183")])

    assert "transform:none" in prepared.xhtml.replace(" ", "")
    assert "width: 20%" in prepared.xhtml
    assert "opacity: 70%" in prepared.xhtml


def test_prepare_kindle_pages_leaves_scp6183_class_on_other_page_unchanged():
    xhtml = (
        '<img class="image layout-profile-scp-6183-symbol" '
        'src="../assets/rsm.png" style="width: 20%; opacity: 70%" alt="rsm.png"/>'
    )

    [prepared] = prepare_kindle_pages([_page(xhtml, slug="scp-9999")])

    assert prepared.xhtml == xhtml


def test_prepare_kindle_pages_preserves_responsive_component_widths():
    xhtml = (
        '<div class="content-panel standalone" style="width: 85%">前言</div>'
        '<div class="scp-image-block block-right" style="width: 45%">图片</div>'
    )

    [prepared] = prepare_kindle_pages([_page(xhtml)])

    assert prepared.xhtml == xhtml


def test_prepare_kindle_pages_only_edits_the_real_style_attribute():
    xhtml = (
        '<div class="scp-image-block block-right" '
        'data-note=" style=\'width: 999px\'" '
        'style="width: 200px /* source width */; border: 1px solid">图片</div>'
    )

    [prepared] = prepare_kindle_pages([_page(xhtml)])

    assert 'data-note=" style=\'width: 999px\'"' in prepared.xhtml
    assert "width:28%" in prepared.xhtml.replace(" ", "")
    assert "width: 200px" not in prepared.xhtml
    assert "border: 1px solid" in prepared.xhtml


def test_prepare_kindle_pages_preserves_inline_svg_when_materializing_labels():
    svg = (
        '<svg viewBox="0 0 10 10" preserveAspectRatio="xMidYMid meet">'
        '<path d="M0 0 L10 10" /></svg>'
    )
    source = _page(
        svg
        + '<div class="anom-bar-container clear-4">'
        '<div class="top-right-box"><div class="clearance"></div></div>'
        "</div>"
    )

    [prepared] = prepare_kindle_pages([source])

    assert svg in prepared.xhtml
    assert '<span class="kindle-clearance-label">SECRET</span>' in prepared.xhtml


def test_prepare_kindle_pages_maps_all_clearance_levels():
    expected = {
        1: "PUBLIC",
        2: "RESTRICTED",
        3: "CONFIDENTIAL",
        4: "SECRET",
        5: "TOP SECRET",
        6: "COSMIC TOP SECRET",
    }
    pages = [
        _page(
            f'<div class="anom-bar-container clear-{level}">'
            '<div class="top-right-box"><div class="clearance"></div></div>'
            "</div>"
        )
        for level in expected
    ]

    prepared = prepare_kindle_pages(pages)

    for page, label in zip(prepared, expected.values(), strict=True):
        assert f">{label}</span>" in page.xhtml

    [level_zero] = prepare_kindle_pages(
        [
            _page(
                '<div class="anom-bar-container clear-0">'
                '<div class="top-right-box"><div class="clearance"></div></div>'
                "</div>"
            )
        ]
    )
    assert "kindle-clearance-label" not in level_zero.xhtml


def test_prepare_kindle_pages_preserves_canonical_classification_markup():
    xhtml = (
        '<div class="anom-bar-container clear-2" '
        'data-epub-classification-family="acs" '
        'data-epub-classification-status="normalized">'
        '<div class="top-right-box"><div class="clearance">'
        '<span class="anomaly-clearance-label">受限</span></div></div>'
        '<div class="anomaly-lower-row"><div class="disrupt-class">Dark</div>'
        '<div class="risk-class">待观察</div></div>'
        '<table class="anomaly-diamond-layout"><tbody><tr>'
        '<td class="anomaly-diamond-top"></td></tr></tbody></table></div>'
        '<div class="scale woed-level-2 woed-class-keter" '
        'data-epub-classification-family="woed" '
        'data-epub-classification-status="normalized">'
        '<div class="woed-level-segments">'
        '<span class="woed-level-segment woed-level-segment-1"></span>'
        '<span class="woed-level-segment woed-level-segment-2"></span></div></div>'
    )

    [prepared] = prepare_kindle_pages([_page(xhtml)])

    assert '<span class="kindle-clearance-label">RESTRICTED</span>' in prepared.xhtml
    assert 'class="anomaly-lower-row"' in prepared.xhtml
    assert 'class="anomaly-diamond-layout"' in prepared.xhtml
    assert 'class="woed-level-segment woed-level-segment-2"' in prepared.xhtml


def test_kindle_css_uses_kf8_fallbacks_and_preserves_scp_components():
    css = load_kindle_css()
    lowered = css.lower()

    for unsupported in (
        "display: grid",
        "display:grid",
        "display: flex",
        "display:flex",
        "::before",
        "::after",
        ":first-child",
        ":last-child",
        "linear-gradient",
        "box-shadow",
    ):
        assert unsupported not in lowered

    assert re.search(r"(?:^|[;{])\s*transform\s*:", lowered) is None
    assert "text-transform: uppercase" in lowered

    assert ".content-panel" in css
    assert ".scp-image-block.block-right" in css
    assert "table.wiki-content-table" in css
    assert ".tabview-panel-epub" in css
    assert ".anom-bar-container" in css
    assert ".kindle-clearance-label" in css
    assert ".kindle-danger-label" in css
    assert ".anomaly-field-icon" in css
    assert ".anomaly-diamond-icon" in css
    assert ".danger-diamond .anomaly-icon-slot" in css
    assert ".anom-bar-container.keter .contain-class .anomaly-field-icon" in css
    assert ".anomaly-lower-row" in css
    assert ".anomaly-diamond-layout" in css
    assert ".anomaly-diamond-frame" in css
    assert '.scale[data-epub-classification-family="woed"]' in css
    assert ".woed-level-segment-6" in css
    assert ".woed-class-keter .obj" in css
    assert ".woed-class-safe .obj" in css
    assert ".woed-class-euclid .obj" in css
    assert ".woed-class-thaumiel .obj" in css
    assert ".woed-class-neutralized .obj" in css
    container_rule = re.search(r"\.anom-bar-container\s*\{(?P<body>[^}]*)\}", css)
    assert container_rule is not None
    assert "padding: 0;" in container_rule.group("body")
    assert "border: 0;" in container_rule.group("body")
    assert "background: transparent;" in container_rule.group("body")
    diamond_rule = re.search(
        r"\.anom-bar-container \.danger-diamond\s*\{(?P<body>[^}]*)\}",
        css,
    )
    assert diamond_rule is not None
    assert "border: 0;" in diamond_rule.group("body")
    assert "background: transparent;" in diamond_rule.group("body")
    assert "position: absolute;" in css
    assert ".anom-bar-container.clear-2 .top-center-box .bar-two" in css
    assert "border-left: 0.45em solid #777;" in css
    assert "background: #ececec;" in css


def test_convert_epub_to_azw3_uses_scribe_profile_and_atomically_replaces_output(
    tmp_path: Path,
):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub")
    azw3_path = tmp_path / "azw3" / "book.azw3"
    azw3_path.parent.mkdir()
    azw3_path.write_bytes(b"old valid azw3")
    commands = []

    def fake_runner(command, **kwargs):
        commands.append((command, kwargs))
        Path(command[2]).write_bytes(b"new valid azw3")
        return subprocess.CompletedProcess(command, 0, stdout="converted", stderr="")

    result = convert_epub_to_azw3(
        epub_path,
        azw3_path,
        executable="ebook-convert-test",
        runner=fake_runner,
    )

    assert result == azw3_path
    assert azw3_path.read_bytes() == b"new valid azw3"
    command, kwargs = commands[0]
    assert command == [
        "ebook-convert-test",
        str(epub_path),
        str(tmp_path / "azw3" / "book.tmp.azw3"),
        "--output-profile=kindle_scribe",
        "--no-inline-toc",
    ]
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert not (tmp_path / "azw3" / "book.tmp.azw3").exists()


def test_convert_epub_to_azw3_reports_missing_calibre(tmp_path: Path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub")
    output_directory = tmp_path / "azw3"
    monkeypatch.setattr("scp_epub.kindle.shutil.which", lambda _name: None)

    with pytest.raises(KindleConversionError, match="ebook-convert"):
        convert_epub_to_azw3(epub_path, output_directory / "book.azw3")

    assert not output_directory.exists()


def test_convert_epub_to_azw3_cleans_stale_temp_when_calibre_is_missing(
    tmp_path: Path, monkeypatch
):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub remains")
    azw3_path = tmp_path / "book.azw3"
    azw3_path.write_bytes(b"previous valid azw3")
    temporary_path = tmp_path / "book.tmp.azw3"
    temporary_path.write_bytes(b"stale partial azw3")
    monkeypatch.setattr("scp_epub.kindle.shutil.which", lambda _name: None)

    with pytest.raises(KindleConversionError, match="ebook-convert"):
        convert_epub_to_azw3(epub_path, azw3_path)

    assert epub_path.read_bytes() == b"epub remains"
    assert azw3_path.read_bytes() == b"previous valid azw3"
    assert not temporary_path.exists()


def test_convert_epub_to_azw3_cleans_temp_and_preserves_previous_output_on_failure(
    tmp_path: Path,
):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub remains")
    azw3_path = tmp_path / "book.azw3"
    azw3_path.write_bytes(b"previous valid azw3")

    def fake_runner(command, **_kwargs):
        Path(command[2]).write_bytes(b"partial")
        return subprocess.CompletedProcess(
            command, 9, stdout="", stderr="conversion failed"
        )

    with pytest.raises(KindleConversionError, match="conversion failed"):
        convert_epub_to_azw3(
            epub_path,
            azw3_path,
            executable="ebook-convert-test",
            runner=fake_runner,
        )

    assert epub_path.read_bytes() == b"epub remains"
    assert azw3_path.read_bytes() == b"previous valid azw3"
    assert not (tmp_path / "book.tmp.azw3").exists()


def test_convert_epub_to_azw3_rejects_bad_image_log_even_with_zero_exit(tmp_path: Path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub")
    azw3_path = tmp_path / "book.azw3"
    azw3_path.write_bytes(b"previous valid azw3")

    def fake_runner(command, **_kwargs):
        Path(command[2]).write_bytes(b"otherwise nonempty azw3")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Bad image file 'OEBPS/assets/problem.png'",
            stderr="",
        )

    with pytest.raises(KindleConversionError, match="Bad image file"):
        convert_epub_to_azw3(
            epub_path,
            azw3_path,
            executable="ebook-convert-test",
            runner=fake_runner,
        )

    assert azw3_path.read_bytes() == b"previous valid azw3"
    assert not (tmp_path / "book.tmp.azw3").exists()


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        ("Bad image file problem.png" + "x" * 5000, ""),
        ("", "Bad image file problem.png" + "x" * 5000),
        ("Bad image", "file problem.png"),
    ],
    ids=("long-stdout", "long-stderr", "cross-stream"),
)
def test_convert_epub_to_azw3_searches_full_calibre_log_for_bad_image(
    tmp_path: Path, stdout: str, stderr: str
):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub")
    azw3_path = tmp_path / "book.azw3"
    azw3_path.write_bytes(b"previous valid azw3")

    def fake_runner(command, **_kwargs):
        Path(command[2]).write_bytes(b"otherwise nonempty azw3")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=stderr)

    with pytest.raises(KindleConversionError, match="invalid image"):
        convert_epub_to_azw3(
            epub_path,
            azw3_path,
            executable="ebook-convert-test",
            runner=fake_runner,
        )

    assert azw3_path.read_bytes() == b"previous valid azw3"
    assert not (tmp_path / "book.tmp.azw3").exists()


@pytest.mark.parametrize("write_temp", [False, True])
def test_convert_epub_to_azw3_rejects_missing_or_empty_temp_output(
    tmp_path: Path, write_temp: bool
):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub")
    azw3_path = tmp_path / "book.azw3"
    azw3_path.write_bytes(b"previous valid azw3")

    def fake_runner(command, **_kwargs):
        if write_temp:
            Path(command[2]).write_bytes(b"")
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    with pytest.raises(KindleConversionError, match="nonempty AZW3"):
        convert_epub_to_azw3(
            epub_path,
            azw3_path,
            executable="ebook-convert-test",
            runner=fake_runner,
        )

    assert azw3_path.read_bytes() == b"previous valid azw3"
    assert not (tmp_path / "book.tmp.azw3").exists()


def test_convert_epub_to_azw3_wraps_runner_oserror_and_preserves_output(tmp_path: Path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub")
    azw3_path = tmp_path / "book.azw3"
    azw3_path.write_bytes(b"previous valid azw3")

    def fake_runner(_command, **_kwargs):
        raise OSError("cannot execute")

    with pytest.raises(KindleConversionError, match="cannot execute"):
        convert_epub_to_azw3(
            epub_path,
            azw3_path,
            executable="ebook-convert-test",
            runner=fake_runner,
        )

    assert azw3_path.read_bytes() == b"previous valid azw3"
    assert not (tmp_path / "book.tmp.azw3").exists()


def test_convert_epub_to_azw3_wraps_replace_oserror_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub")
    azw3_path = tmp_path / "book.azw3"
    azw3_path.write_bytes(b"previous valid azw3")
    original_replace = Path.replace

    def fake_replace(path: Path, target: Path):
        if path.name == "book.tmp.azw3":
            raise OSError("replace denied")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fake_replace)

    def fake_runner(command, **_kwargs):
        Path(command[2]).write_bytes(b"new valid azw3")
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    with pytest.raises(KindleConversionError, match="replace denied"):
        convert_epub_to_azw3(
            epub_path,
            azw3_path,
            executable="ebook-convert-test",
            runner=fake_runner,
        )

    assert azw3_path.read_bytes() == b"previous valid azw3"
    assert not (tmp_path / "book.tmp.azw3").exists()
