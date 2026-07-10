import json
import zipfile
from pathlib import Path

import pytest

from scp_epub.assets import AssetRef
from scp_epub.epub import write_build_report, write_epub
from scp_epub.models import PageRef, ProcessedPage


def _page(
    slug: str,
    title: str,
    order: int,
    *,
    level: int = 1,
    parent_slug: str | None = None,
    xhtml: str = "<p>Body</p>",
    asset_urls: tuple[str, ...] = (),
    internal_links: tuple[str, ...] = (),
    external_links: tuple[str, ...] = (),
) -> ProcessedPage:
    entry = PageRef(
        title=title,
        url=f"https://scp-wiki-cn.wikidot.com/{slug}",
        slug=slug,
        level=level,
        role="page",
        parent_slug=parent_slug,
        order=order,
    )
    return ProcessedPage(
        entry=entry,
        xhtml=xhtml,
        asset_urls=asset_urls,
        internal_links=internal_links,
        external_links=external_links,
    )


def test_write_epub_creates_epub_zip_with_required_files(tmp_path: Path):
    pages = [
        _page("scp-002", "SCP-002", 2),
        _page("old:kalinins-proposal", "Old: Kalinin's Proposal", 1),
    ]
    output_path = tmp_path / "series.epub"

    result = write_epub(
        pages,
        output_path,
        title="SCP Series I",
        language="zh-CN",
        creator="SCP Wiki",
        identifier="urn:scp:test",
    )

    assert result == output_path
    with zipfile.ZipFile(output_path) as archive:
        names = archive.namelist()
        mimetype_info = archive.getinfo("mimetype")
        assert names[0] == "mimetype"
        assert mimetype_info.compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"
        assert "META-INF/container.xml" in names
        assert "OEBPS/content.opf" in names
        assert "OEBPS/nav.xhtml" in names
        assert "OEBPS/toc.ncx" in names
        assert "OEBPS/text/0001-old_kalinins-proposal.xhtml" in names
        assert "OEBPS/text/0002-scp-002.xhtml" in names


def test_write_epub_opf_manifest_spine_and_metadata_are_ordered(tmp_path: Path):
    pages = [
        _page("scp-002", "SCP-002", 2),
        _page("scp-001", "SCP-001", 1),
    ]
    output_path = tmp_path / "series.epub"

    write_epub(
        pages,
        output_path,
        title="SCP Series I",
        language="zh-CN",
        creator="SCP Wiki",
        identifier="urn:scp:test",
        modified="2026-07-10T12:34:56Z",
    )

    with zipfile.ZipFile(output_path) as archive:
        opf = archive.read("OEBPS/content.opf").decode("utf-8")

    assert "<dc:title>SCP Series I</dc:title>" in opf
    assert "<dc:language>zh-CN</dc:language>" in opf
    assert "<dc:creator>SCP Wiki</dc:creator>" in opf
    assert '<dc:identifier id="book-id">urn:scp:test</dc:identifier>' in opf
    assert 'xmlns:dcterms="http://purl.org/dc/terms/"' in opf
    assert '<meta property="dcterms:modified">2026-07-10T12:34:56Z</meta>' in opf
    assert '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>' in opf
    assert '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>' in opf
    assert '<item id="page-0001" href="text/0001-scp-001.xhtml" media-type="application/xhtml+xml"/>' in opf
    assert '<item id="page-0002" href="text/0002-scp-002.xhtml" media-type="application/xhtml+xml"/>' in opf
    assert "<spine toc=\"ncx\">" in opf
    assert opf.index('<itemref idref="page-0001"/>') < opf.index('<itemref idref="page-0002"/>')


def test_write_epub_xhtml_pages_include_title_body_and_safe_filename(tmp_path: Path):
    page = _page(
        "old:kalinins-proposal",
        "旧案: Kalinin & Friends",
        7,
        xhtml="<section><p>Transformed <strong>body</strong></p></section>",
    )
    output_path = tmp_path / "series.epub"

    write_epub([page], output_path, title="SCP", language="zh-CN", creator="SCP")

    with zipfile.ZipFile(output_path) as archive:
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        chapter = archive.read("OEBPS/text/0007-old_kalinins-proposal.xhtml").decode("utf-8")

    assert '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN" xml:lang="zh-CN">' in nav
    assert '<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN" xml:lang="zh-CN">' in chapter
    assert "<title>旧案: Kalinin &amp; Friends</title>" in chapter
    assert "<h1>旧案: Kalinin &amp; Friends</h1>" in chapter
    assert "<p>Transformed <strong>body</strong></p>" in chapter


def test_write_epub_nav_preserves_hierarchical_manifest_structure(tmp_path: Path):
    pages = [
        _page("scp-001", "SCP-001", 1, level=1),
        _page("spc-001", "SPC-001", 2, level=2, parent_slug="scp-001"),
        _page("ouroborealis", "衔尾鲨", 3, level=3, parent_slug="spc-001"),
        _page("scp-002", "SCP-002", 4, level=1),
    ]
    output_path = tmp_path / "series.epub"

    write_epub(pages, output_path, title="SCP", language="zh-CN", creator="SCP")

    with zipfile.ZipFile(output_path) as archive:
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        ncx = archive.read("OEBPS/toc.ncx").decode("utf-8")

    scp001 = '<li class="level-1"><a href="text/0001-scp-001.xhtml">SCP-001</a>'
    spc001 = '<li class="level-2"><a href="text/0002-spc-001.xhtml">SPC-001</a>'
    ouroborealis = '<li class="level-3"><a href="text/0003-ouroborealis.xhtml">衔尾鲨</a></li>'
    scp002 = '<li class="level-1"><a href="text/0004-scp-002.xhtml">SCP-002</a></li>'

    assert nav.index(scp001) < nav.index(spc001) < nav.index(ouroborealis) < nav.index(scp002)
    assert (
        f"{scp001}\n          <ol>\n            {spc001}\n              <ol>\n                {ouroborealis}\n"
        in nav
    )
    assert (
        '<navPoint id="navPoint-0001" playOrder="1">\n'
        "      <navLabel><text>SCP-001</text></navLabel>\n"
        '      <content src="text/0001-scp-001.xhtml"/>\n'
        '      <navPoint id="navPoint-0002" playOrder="2">\n'
        "        <navLabel><text>SPC-001</text></navLabel>\n"
        '        <content src="text/0002-spc-001.xhtml"/>\n'
        '        <navPoint id="navPoint-0003" playOrder="3">\n'
        "          <navLabel><text>衔尾鲨</text></navLabel>\n"
        '          <content src="text/0003-ouroborealis.xhtml"/>\n'
        in ncx
    )


def test_write_epub_includes_localized_assets_in_archive_and_manifest(tmp_path: Path):
    asset_path = tmp_path / "cache" / "photo.png"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"png data")
    page = _page(
        "scp-001",
        "SCP-001",
        1,
        xhtml='<p><img src="../assets/photo.png" alt="Specimen"/></p>',
    )
    output_path = tmp_path / "series.epub"

    write_epub(
        [page],
        output_path,
        title="SCP",
        language="zh-CN",
        creator="SCP",
        assets=[
            AssetRef(
                source_url="https://scp-wiki-cn.wikidot.com/images/photo.png",
                path=asset_path,
                href="assets/photo.png",
                content_type="image/png",
            )
        ],
    )

    with zipfile.ZipFile(output_path) as archive:
        assert archive.read("OEBPS/assets/photo.png") == b"png data"
        opf = archive.read("OEBPS/content.opf").decode("utf-8")

    assert '<item id="asset-0001" href="assets/photo.png" media-type="image/png"/>' in opf


def test_write_epub_marks_only_pages_with_remote_resources(tmp_path: Path):
    pages = [
        _page(
            "scp-001",
            "SCP-001",
            1,
            xhtml='<p><img src="https://example.test/missing.png"/></p>',
        ),
        _page(
            "scp-002",
            "SCP-002",
            2,
            xhtml='<p><img src="../assets/photo.png"/></p>',
        ),
    ]
    output_path = tmp_path / "series.epub"

    write_epub(
        pages,
        output_path,
        title="SCP",
        language="zh-CN",
        creator="SCP",
        remote_resource_page_slugs={"scp-001"},
    )

    with zipfile.ZipFile(output_path) as archive:
        opf = archive.read("OEBPS/content.opf").decode("utf-8")

    assert (
        '<item id="page-0001" href="text/0001-scp-001.xhtml" '
        'media-type="application/xhtml+xml" properties="remote-resources"/>'
    ) in opf
    assert '<item id="page-0002" href="text/0002-scp-002.xhtml" media-type="application/xhtml+xml"/>' in opf


def test_write_epub_rejects_empty_pages(tmp_path: Path):
    with pytest.raises(ValueError, match="at least one page"):
        write_epub([], tmp_path / "empty.epub", title="Empty", language="en", creator="Nobody")


def test_write_build_report_writes_utf8_json_with_page_assets_and_links(tmp_path: Path):
    pages = [
        _page(
            "scp-002",
            "SCP-002",
            2,
            asset_urls=("https://example.test/a.png",),
            internal_links=("https://scp-wiki-cn.wikidot.com/scp-003",),
            external_links=("https://example.test/out",),
        ),
        _page(
            "scp-001",
            "第一章",
            1,
            asset_urls=("https://example.test/b.png", "https://example.test/a.png"),
            internal_links=("https://scp-wiki-cn.wikidot.com/scp-004",),
        ),
    ]
    report_path = tmp_path / "reports" / "build.json"
    output_path = tmp_path / "series.epub"

    result = write_build_report(
        report_path,
        pages=pages,
        output_path=output_path,
        external_links=("https://manual.example/external",),
        missing_assets=("https://example.test/missing.png",),
    )

    assert result == report_path
    raw_text = report_path.read_text(encoding="utf-8")
    assert "第一章" in raw_text
    report = json.loads(raw_text)
    assert report["page_count"] == 2
    assert report["output_path"] == str(output_path)
    assert report["pages"] == [
        {"slug": "scp-001", "title": "第一章"},
        {"slug": "scp-002", "title": "SCP-002"},
    ]
    assert report["asset_urls"] == [
        "https://example.test/b.png",
        "https://example.test/a.png",
    ]
    assert report["internal_links"] == [
        "https://scp-wiki-cn.wikidot.com/scp-004",
        "https://scp-wiki-cn.wikidot.com/scp-003",
    ]
    assert report["external_links"] == [
        "https://example.test/out",
        "https://manual.example/external",
    ]
    assert report["missing_assets"] == ["https://example.test/missing.png"]
