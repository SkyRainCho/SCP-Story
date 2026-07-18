import io
import re
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
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


def _page(xhtml: str) -> ProcessedPage:
    return ProcessedPage(
        entry=PageRef(
            title="SCP-001",
            url="https://scp-wiki-cn.wikidot.com/scp-001",
            slug="scp-001",
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
    "payload",
    [
        b"\xef\xbb\xbf  <!doctype html><title>404</title>",
        b'<?xml version="1.0"?><html><title>404</title></html>',
        b"<!-- proxy error --><html><title>404</title></html>",
    ],
)
def test_html_sniffer_handles_wrappers_before_error_page(payload: bytes):
    assert kindle_module._looks_like_html(payload)


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


def test_prepare_kindle_pages_preserves_ordinary_xhtml_exactly():
    xhtml = (
        '<section><svg viewBox="0 0 10 10" preserveAspectRatio="xMidYMid meet">'
        '<path d="M0 0 L10 10" /></svg></section>\n'
    )

    [prepared] = prepare_kindle_pages([_page(xhtml)])

    assert prepared.xhtml == xhtml


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
