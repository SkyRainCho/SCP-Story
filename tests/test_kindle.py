import re
import subprocess
from pathlib import Path

import pytest

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
