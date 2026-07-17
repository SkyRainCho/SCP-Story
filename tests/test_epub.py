import json
import zipfile
from pathlib import Path

import pytest

from scp_epub.assets import AssetRef
from scp_epub.epub import BOOK_CSS, write_build_report, write_epub
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


def test_write_epub_accepts_custom_css_without_changing_default(tmp_path: Path):
    page = _page("scp-001", "SCP-001", 1)
    default_path = tmp_path / "default.epub"
    custom_path = tmp_path / "custom.epub"

    write_epub(
        [page],
        default_path,
        title="SCP",
        language="zh-CN",
        creator="SCP",
    )
    write_epub(
        [page],
        custom_path,
        title="SCP",
        language="zh-CN",
        creator="SCP",
        book_css="body { color: black; }\n",
    )

    with zipfile.ZipFile(default_path) as archive:
        default_css = archive.read("OEBPS/styles/book.css").decode("utf-8")
    with zipfile.ZipFile(custom_path) as archive:
        custom_css = archive.read("OEBPS/styles/book.css").decode("utf-8")

    assert default_css == BOOK_CSS
    assert custom_css == "body { color: black; }\n"


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


def test_write_epub_includes_book_styles_for_scp_image_blocks(tmp_path: Path):
    page = _page(
        "captain-kirby-s-proposal",
        "Captain Kirby的提案",
        122,
        xhtml=(
            '<div class="scp-image-block block-right">'
            '<img class="image" src="../assets/001pic.png" alt="001pic.png"/>'
            '<div class="scp-image-caption"><p>SCP-001</p></div>'
            "</div><p>项目编号：SCP-001</p>"
        ),
    )
    output_path = tmp_path / "series.epub"

    write_epub([page], output_path, title="SCP", language="zh-CN", creator="SCP")

    with zipfile.ZipFile(output_path) as archive:
        names = archive.namelist()
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        chapter = archive.read("OEBPS/text/0122-captain-kirby-s-proposal.xhtml").decode("utf-8")
        css = archive.read("OEBPS/styles/book.css").decode("utf-8")

    assert "OEBPS/styles/book.css" in names
    assert '<item id="book-css" href="styles/book.css" media-type="text/css"/>' in opf
    assert '<link rel="stylesheet" type="text/css" href="../styles/book.css"/>' in chapter
    assert ".scp-image-block.block-right" in css
    assert "float: right;" in css
    assert "width: 300px;" in css


def test_write_epub_includes_book_styles_for_scp_warning_panels(tmp_path: Path):
    page = _page(
        "scp-001",
        "SCP-001",
        1,
        xhtml=(
            '<div style="text-align: center;">'
            '<h2>在管理员的命令下</h2>'
            '<h1><span style="font-size: 200%;">最高机密</span></h1>'
            "</div>"
            '<div class="content-panel standalone series">'
            "<p><strong>通用说明001-Alpha：</strong>正文</p>"
            "</div>"
        ),
    )
    output_path = tmp_path / "series.epub"

    write_epub([page], output_path, title="SCP", language="zh-CN", creator="SCP")

    with zipfile.ZipFile(output_path) as archive:
        chapter = archive.read("OEBPS/text/0001-scp-001.xhtml").decode("utf-8")
        css = archive.read("OEBPS/styles/book.css").decode("utf-8")

    assert 'style="text-align: center;"' in chapter
    assert 'style="font-size: 200%;"' in chapter
    assert "h1 {" in css
    assert "color: #901;" in css
    assert ".content-panel" in css
    assert "border-radius: 8px;" in css
    assert "box-shadow:" in css


def test_write_epub_includes_book_styles_for_wiki_tables_and_blockquotes(tmp_path: Path):
    page = _page(
        "captain-kirby-s-holistic-proposal",
        "Captain Kirby的提案，或是别的什么",
        4,
        xhtml=(
            '<table class="wiki-content-table">'
            "<tr><th>名称</th><th>描述</th></tr>"
            "<tr><td>卫生水炸弹</td><td>浓缩干燥的拳击粉末</td></tr>"
            "</table>"
            "<blockquote><p><strong>B-2：</strong>你们知道这个玩意没用吧？</p></blockquote>"
        ),
    )
    output_path = tmp_path / "series.epub"

    write_epub([page], output_path, title="SCP", language="zh-CN", creator="SCP")

    with zipfile.ZipFile(output_path) as archive:
        chapter = archive.read("OEBPS/text/0004-captain-kirby-s-holistic-proposal.xhtml").decode("utf-8")
        css = archive.read("OEBPS/styles/book.css").decode("utf-8")

    assert '<table class="wiki-content-table">' in chapter
    assert "<blockquote>" in chapter
    assert "table.wiki-content-table" in css
    assert "border-collapse: collapse;" in css
    assert "table.wiki-content-table th," in css
    assert "border: 1px solid #888;" in css
    assert "blockquote" in css
    assert "border: 1px dashed #999;" in css
    assert "background: #f8f8f8;" in css


def test_write_epub_includes_book_styles_for_anomaly_classification_bar(tmp_path: Path):
    page = _page(
        "djkaktus-s-proposal-ii",
        "代号：djkaktus II - 赎罪",
        111,
        xhtml=(
            '<div class="anom-bar-container item-001 clear-5 keter none amida 危急 lang-cn">'
            '<div class="anom-bar">'
            '<div class="top-box">'
            '<div class="top-left-box"><span class="item"><span class="lang-cn">项目编号：</span>'
            '<span class="lang-tr">項目編號：</span></span><span class="number">001</span></div>'
            '<div class="top-center-box"><div class="bar-one"></div><div class="bar-two"></div>'
            '<div class="bar-three"></div><div class="bar-four"></div><div class="bar-five"></div>'
            '<div class="bar-six"></div></div>'
            '<div class="top-right-box"><div class="level">等级5</div><div class="clearance"></div></div>'
            "</div>"
            '<div class="bottom-box"><div class="text-part"><div class="main-class">'
            '<div class="contain-class"><div class="class-category">收容等级：</div>'
            '<div class="class-text">keter</div></div>'
            '<div class="second-class"><div class="class-category">次要等级：</div>'
            '<div class="class-text">none</div></div></div>'
            '<div class="disrupt-class"><div class="class-category">扰动等级：</div>'
            '<div class="class-text">amida</div></div>'
            '<div class="risk-class"><div class="class-category">风险等级：</div>'
            '<div class="class-text">危急</div></div></div>'
            '<div class="diamond-part"><div class="danger-diamond"><a href="../text/memo.xhtml">备忘录链接</a>'
            '<div class="quadrants"></div></div></div></div></div></div>'
        ),
    )
    output_path = tmp_path / "series.epub"

    write_epub([page], output_path, title="SCP", language="zh-CN", creator="SCP")

    with zipfile.ZipFile(output_path) as archive:
        chapter = archive.read("OEBPS/text/0111-djkaktus-s-proposal-ii.xhtml").decode("utf-8")
        css = archive.read("OEBPS/styles/book.css").decode("utf-8")

    assert 'class="anom-bar-container item-001 clear-5 keter none amida 危急 lang-cn"' in chapter
    assert ".anom-bar-container" in css
    assert ".anom-bar-container .lang-tr" in css
    assert ".top-center-box > div" in css
    assert ".danger-diamond" in css


def test_write_epub_includes_book_styles_for_wikidot_tabbed_series_lists(tmp_path: Path):
    page = _page(
        "scp-001",
        "SCP-001",
        1,
        xhtml=(
            '<div class="content-panel standalone series">'
            '<div class="yui-navset" id="wiki-tabview-test">'
            '<ul class="yui-nav">'
            '<li class="selected"><a><em>随机排序</em></a></li>'
            '<li><a><em>按时间顺序展示</em></a></li>'
            "</ul>"
            '<div class="yui-content">'
            '<div id="wiki-tab-0-0"><p></p></div>'
            '<div id="wiki-tab-0-1">'
            '<div class="divider">系列 1</div>'
            '<p><a href="https://scp-wiki-cn.wikidot.com/jonathan-ball-s-proposal">代号：Jonathan Ball</a> - 资料卷</p>'
            '<p><span style="text-decoration: line-through"><a href="https://scp-wiki-cn.wikidot.com/scp-001-o5">代号：Bright</a> - 工厂</span></p>'
            "</div></div></div></div>"
        ),
    )
    output_path = tmp_path / "series.epub"

    write_epub([page], output_path, title="SCP", language="zh-CN", creator="SCP")

    with zipfile.ZipFile(output_path) as archive:
        chapter = archive.read("OEBPS/text/0001-scp-001.xhtml").decode("utf-8")
        css = archive.read("OEBPS/styles/book.css").decode("utf-8")

    assert '<ul class="yui-nav">' in chapter
    assert '<div class="divider">系列 1</div>' in chapter
    assert ".yui-navset .yui-nav" in css
    assert "list-style: none;" in css
    assert ".yui-navset .yui-content" in css
    assert ".yui-navset .divider::before" in css
    assert ".yui-navset .yui-content p" in css
    assert ".tabview-epub" in css
    assert ".tabview-panel-epub" in css
    assert ".tabview-panel-title" in css


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


def test_write_epub_nav_places_appendix_after_scp_roots_and_nests_facility(tmp_path: Path):
    pages = [
        _page("scp-173", "SCP-173", 1, level=1),
        _page("appendix", "附录", 2, level=1),
        _page("secure-facilities-locations", "基金会设施", 3, level=2, parent_slug="appendix"),
        _page(
            "site-19",
            "安保设施档案：Site-19",
            4,
            level=3,
            parent_slug="secure-facilities-locations",
        ),
    ]
    output_path = tmp_path / "featured.epub"

    write_epub(pages, output_path, title="精选", language="zh-CN", creator="SCP")

    with zipfile.ZipFile(output_path) as archive:
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")

    scp_root = '<li class="level-1"><a href="text/0001-scp-173.xhtml">SCP-173</a></li>'
    appendix = '<li class="level-1"><a href="text/0002-appendix.xhtml">附录</a>'
    facilities = '<li class="level-2"><a href="text/0003-secure-facilities-locations.xhtml">基金会设施</a>'
    facility = '<li class="level-3"><a href="text/0004-site-19.xhtml">安保设施档案：Site-19</a></li>'

    assert nav.index(scp_root) < nav.index(appendix)
    assert f"{appendix}\n          <ol>\n            {facilities}\n              <ol>\n                {facility}\n" in nav


def test_write_epub_keeps_featured_inline_documents_out_of_manifest_and_navigation(
    tmp_path: Path,
):
    inline_titles = (
        "SCP-1898 相关图片",
        "SCP-7503 Offset 1",
        "SCP-7503 Offset 2",
        "SCP-7503 Offset 3",
        "SCP-7503 Offset 4",
        "SCP-6445 Offset 1",
        "Document 2814-Gamma",
    )
    pages = [
        _page(
            "scp-1898",
            "SCP-1898",
            1,
            xhtml=(
                "<p>附录-1898-1：相关SCP-1898图片</p>"
                '<section class="inline-document-epub"><h2>SCP-1898 相关图片</h2></section>'
            ),
        ),
        _page(
            "scp-7503",
            "SCP-7503",
            2,
            xhtml="".join(
                f'<section class="inline-document-epub"><h2>SCP-7503 Offset {index}</h2></section>'
                for index in range(1, 5)
            ),
        ),
        _page(
            "scp-6445",
            "SCP-6445",
            3,
            xhtml='<section class="inline-document-epub"><h2>SCP-6445 Offset 1</h2></section>',
        ),
        _page(
            "scp-2814",
            "SCP-2814",
            4,
            xhtml=(
                '<section class="inline-document-epub"><h2>Document 2814-Gamma</h2></section>'
                "<h2>Footnotes</h2>"
            ),
        ),
    ]
    output_path = tmp_path / "featured.epub"

    write_epub(pages, output_path, title="精选", language="zh-CN", creator="SCP")

    with zipfile.ZipFile(output_path) as archive:
        names = archive.namelist()
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        ncx = archive.read("OEBPS/toc.ncx").decode("utf-8")

    assert [name for name in names if name.startswith("OEBPS/text/")] == [
        "OEBPS/text/0001-scp-1898.xhtml",
        "OEBPS/text/0002-scp-7503.xhtml",
        "OEBPS/text/0003-scp-6445.xhtml",
        "OEBPS/text/0004-scp-2814.xhtml",
    ]
    assert opf.count('<item id="page-') == 4
    assert opf.count('<itemref idref="page-') == 4
    assert nav.count('<li class="level-1">') == 4
    assert '<li class="level-2">' not in nav
    assert "原文附属文档" not in nav
    assert "原文附属文档" not in ncx
    for title in inline_titles:
        assert title not in opf
        assert title not in nav
        assert title not in ncx


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


def test_write_epub_includes_cover_page_and_cover_image_metadata(tmp_path: Path):
    cover_path = tmp_path / "cover.png"
    cover_path.write_bytes(b"cover png")
    page = _page("scp-001", "SCP-001", 1)
    output_path = tmp_path / "series.epub"

    write_epub(
        [page],
        output_path,
        title="SCP",
        language="zh-CN",
        creator="SCP",
        cover_image_path=cover_path,
    )

    with zipfile.ZipFile(output_path) as archive:
        names = archive.namelist()
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        cover = archive.read("OEBPS/cover.xhtml").decode("utf-8")
        cover_image = archive.read("OEBPS/images/cover.png")

    assert "OEBPS/cover.xhtml" in names
    assert cover_image == b"cover png"
    assert '<meta name="cover" content="cover-image"/>' in opf
    assert (
        '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>'
        in opf
    )
    assert (
        '<item id="cover-image" href="images/cover.png" '
        'media-type="image/png" properties="cover-image"/>'
        in opf
    )
    assert opf.index('<itemref idref="cover"/>') < opf.index('<itemref idref="page-0001"/>')
    assert '<img src="images/cover.png" alt="封面"/>' in cover


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
