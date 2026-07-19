from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from scp_epub.models import InlineDocumentSpec, PageRef, ProcessedPage
from scp_epub.transform import PageTransformOptions, insert_inline_fragments, transform_page


FIXTURE = Path(__file__).parent / "fixtures" / "page_sample.html"
FEATURED_LAYOUT_FIXTURES = Path(__file__).parent / "fixtures" / "featured-layout"
BASE_URL = "https://scp-wiki-cn.wikidot.com/scp-999"


def page_ref(slug: str = "scp-999") -> PageRef:
    return PageRef(
        title="SCP-999",
        url=BASE_URL,
        slug=slug,
        level=1,
        role="scp",
    )


def transformed(manifest_slugs: set[str] | None = None):
    return transform_page(page_ref(), FIXTURE.read_text(encoding="utf-8"), BASE_URL, manifest_slugs)


def soup_fragment(xhtml: str) -> BeautifulSoup:
    return BeautifulSoup(f"<root>{xhtml}</root>", "xml")


@pytest.mark.parametrize("profile", ("scp-6183", "scp-4612", "scp-6599"))
def test_featured_layout_profiles_leave_unselected_fixture_output_unchanged(profile: str):
    html = (FEATURED_LAYOUT_FIXTURES / f"{profile}.html").read_text(encoding="utf-8")

    default = transform_page(page_ref(profile), html, BASE_URL)
    unselected = transform_page(
        page_ref(profile),
        html,
        BASE_URL,
        page_options=PageTransformOptions(),
    )

    assert unselected.xhtml == default.xhtml
    assert "layout-profile-" not in default.xhtml


def test_scp6183_layout_profile_stabilizes_image_block_inside_table():
    html = (FEATURED_LAYOUT_FIXTURES / "scp-6183.html").read_text(encoding="utf-8")

    result = transform_page(
        page_ref("scp-6183"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(layout_profile="scp-6183"),
    )
    soup = soup_fragment(result.xhtml)
    image_block = soup.find(id="table-image")

    assert image_block is not None
    assert "layout-profile-scp-6183-table-image" in image_block["class"]
    assert "float: none" in image_block["style"]
    assert "max-width: 100%" in image_block["style"]
    assert soup.find(id="table-image").find("img")["style"] == "max-width: 100%; height: auto"
    assert soup.find("iframe") is None
    assert "图像后的表格内容。" in soup.get_text(" ", strip=True)


def test_scp4612_layout_profile_stabilizes_right_floated_image_blocks():
    html = (FEATURED_LAYOUT_FIXTURES / "scp-4612.html").read_text(encoding="utf-8")

    result = transform_page(
        page_ref("scp-4612"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(layout_profile="scp-4612"),
    )
    soup = soup_fragment(result.xhtml)
    image_block = soup.find(id="estate-image")

    assert image_block is not None
    assert "layout-profile-scp-4612-image" in image_block["class"]
    assert "float: none" in image_block["style"]
    assert "clear: both" in image_block["style"]
    assert "max-width: 100%" in image_block.find("img")["style"]
    assert "宅邸的调查仍在继续。" in soup.get_text(" ", strip=True)


def test_scp6599_layout_profile_normalizes_reddit_posts_and_nested_media():
    html = (FEATURED_LAYOUT_FIXTURES / "scp-6599.html").read_text(encoding="utf-8")

    result = transform_page(
        page_ref("scp-6599"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(layout_profile="scp-6599"),
    )
    soup = soup_fragment(result.xhtml)
    reddit_body = soup.find(id="reddit-body")
    image_block = soup.find(id="meme-image")
    wide_image = soup.find(id="wide-image")
    portrait_image = soup.find(id="portrait-image")

    assert reddit_body is not None
    assert "layout-profile-scp-6599-reddit-body" in reddit_body["class"]
    assert "float: none" in reddit_body["style"]
    assert "width: auto" in reddit_body["style"]
    assert image_block is not None
    assert "layout-profile-scp-6599-inline-media" in image_block["class"]
    assert "width: 100%" in image_block["style"]
    assert "max-width: 100%" in image_block.find("img")["style"]
    assert wide_image is not None
    assert wide_image["class"].split() == ["scp-image-block", "block-right"]
    assert wide_image["style"] == "width: 45%"
    assert portrait_image is not None
    assert portrait_image["class"].split() == ["scp-image-block", "block-right"]
    assert portrait_image["style"] == "width: 35%"
    assert "附录继续。" in soup.get_text(" ", strip=True)


def test_transforms_only_page_content_and_removes_wikidot_chrome():
    result = transformed({"scp-002", "old:kalinins-proposal"})
    soup = soup_fragment(result.xhtml)

    assert "Outside chrome" not in result.xhtml
    assert "Outside footer" not in result.xhtml
    assert soup.find("h1").get_text(strip=True) == "SCP-999"
    page_text = soup.get_text(" ", strip=True)
    assert "Main article text" in page_text
    assert "Threat rating: green." in page_text
    assert "Rating note is article content." in page_text
    assert "SCP-002 | SCP-003 | SCP-004" not in page_text
    assert "授权 / 引用" not in page_text
    assert "请按如下方式引用此页" not in page_text
    assert "授权指南" not in page_text
    assert "著作信息" not in page_text
    assert "Captain Kirby的提案" not in page_text
    assert "我们只是人类而已" not in page_text
    assert "该作者的更多作品" not in page_text
    assert "其他语言" not in page_text
    assert "常见问题" not in page_text
    assert "VARIABLES" not in page_text
    assert "BLANKSTYLE CSS" not in page_text
    assert "+\xa0CODE" not in page_text
    assert "-\xa0CODE" not in page_text
    assert "article code should stay" in page_text

    assert soup.find("script") is None
    assert soup.find("style") is None
    assert soup.find(id="toc") is None
    assert soup.find(class_="toc") is None
    assert soup.find(class_="page-options-bottom") is None
    assert soup.find(class_="rate-box-with-credit-button") is None
    assert soup.find(id="page-info") is None
    assert soup.find("nav") is None
    assert soup.find(class_="footer-wikiwalk-nav") is None
    assert soup.find(class_="licensebox") is None
    assert soup.find(id="u-credit-view") is None
    assert soup.find(class_="modalcontainer") is None
    assert soup.find(class_="creditRate") is None
    assert soup.find(class_="info-container") is None
    assert soup.find(id="u-author_block") is None
    assert soup.find(class_="translation_block") is None
    assert soup.find(class_="u-faq") is None


def test_normalizes_and_deduplicates_assets_in_encounter_order():
    result = transformed({"scp-002", "old:kalinins-proposal"})
    soup = soup_fragment(result.xhtml)

    assert result.asset_urls == (
        "https://scp-wiki-cn.wikidot.com/images/photo.png",
        "https://scp-wiki-cn.wikidot.com/media/interview.ogg",
        "https://scp-wiki-cn.wikidot.com/files/report.pdf",
        "https://scp-wiki-cn.wikidot.com/css/page.css",
    )
    assert [img["src"] for img in soup.find_all("img")] == [
        "https://scp-wiki-cn.wikidot.com/images/photo.png",
        "https://scp-wiki-cn.wikidot.com/images/photo.png",
        "data:image/png;base64,AAAA",
    ]
    assert soup.find("source")["src"] == "https://scp-wiki-cn.wikidot.com/media/interview.ogg"
    assert soup.find("object")["data"] == "https://scp-wiki-cn.wikidot.com/files/report.pdf"
    assert soup.find("object", title="Inline object")["data"] == "data:application/pdf;base64,BBBB"
    assert soup.find("link")["href"] == "https://scp-wiki-cn.wikidot.com/css/page.css"
    canonical = soup.find("link", rel="canonical")
    assert canonical["href"] == "/canonical-page#frag"
    assert "https://scp-wiki-cn.wikidot.com/canonical-page" not in result.asset_urls
    assert "data:image/png;base64,AAAA" not in result.asset_urls
    assert "data:application/pdf;base64,BBBB" not in result.asset_urls


def test_classifies_internal_and_external_links_and_ignores_fragment_and_javascript():
    result = transformed({"scp-002", "old:kalinins-proposal"})
    soup = soup_fragment(result.xhtml)

    assert result.internal_links == (
        "https://scp-wiki-cn.wikidot.com/scp-002",
        "https://scp-wiki-cn.wikidot.com/old:kalinins-proposal",
    )
    assert result.external_links == (
        "https://example.test/out",
        "https://scp-wiki-cn.wikidot.com/not-in-manifest",
        "mailto:researcher@example.test",
    )

    hrefs = [anchor.get("href") for anchor in soup.find_all("a")]
    assert "https://scp-wiki-cn.wikidot.com/scp-002" in hrefs
    assert "https://example.test/out" in hrefs
    assert "https://scp-wiki-cn.wikidot.com/old:kalinins-proposal" in hrefs
    assert "https://scp-wiki-cn.wikidot.com/not-in-manifest" in hrefs
    assert "mailto:researcher@example.test" in hrefs
    assert "#local-anchor" not in hrefs
    assert "javascript:void(0)" not in hrefs


def test_strips_event_handlers_and_sanitizes_inline_styles_but_keeps_harmless_attributes():
    result = transformed({"scp-002", "old:kalinins-proposal"})
    soup = soup_fragment(result.xhtml)

    assert not soup.find_all(attrs={"onclick": True})
    image = soup.find("img")
    paragraph = soup.find("p")
    heading = soup.find("h1")
    struck = soup.find("span", string="Struck proposal")
    notice = soup.find(class_="notice")
    assert image["alt"] == "Specimen photo"
    assert image["title"] == "Photo title"
    assert image["class"] == "image"
    assert image["style"] == "width: 100px"
    assert paragraph["class"] == "main-text"
    assert paragraph["style"] == "font-size: 24px"
    assert heading["style"] == "color: red"
    assert struck["style"] == "text-decoration: line-through"
    assert notice["style"] == "border: solid 1px #999999; background: #f2f2c2; padding: 5px"
    assert "behavior" not in result.xhtml
    assert "javascript:alert" not in result.xhtml


def test_removes_hidden_css_code_with_split_highlight_tokens():
    html = """
    <html><body><div id="page-content">
      <div style="display: none;">
        <div class="code"><pre><span>:root</span> {
          <span>--</span><span>accent:</span> var(--acc-spc);
          <span>--</span><span>header-title:</span> "SPC 数据库";
        }</pre></div>
      </div>
      <p>正文内容</p>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)

    assert ":root" not in result.xhtml
    assert "--" not in result.xhtml
    assert "SPC 数据库" not in result.xhtml
    assert "正文内容" in result.xhtml


def test_removes_unfolded_collapsible_links_but_keeps_single_folded_label_and_content():
    html = """
    <html><body><div id="page-content">
      <div class="collapsible-block">
        <div class="collapsible-block-folded"><a class="collapsible-block-link" href="javascript:;">1</a></div>
        <div class="collapsible-block-unfolded" style="display:none">
          <div class="collapsible-block-unfolded-link"><a class="collapsible-block-link" href="javascript:;">1</a></div>
          <div class="collapsible-block-content"><p>第一段正文</p></div>
          <div class="collapsible-block-unfolded-link"><a class="collapsible-block-link" href="javascript:;">1</a></div>
        </div>
      </div>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    assert soup.find(class_="collapsible-block-unfolded-link") is None
    links = soup.find_all(class_="collapsible-block-link")
    assert [link.get_text(strip=True) for link in links] == ["1"]
    assert "第一段正文" in soup.get_text(" ", strip=True)


def test_removes_hidden_scp_image_blocks_that_would_become_visible_after_style_sanitization():
    html = """
    <html><body><div id="page-content">
      <div style="display: none;">
        <div class="scp-image-block block-right" style="width:300px;">
          <img src="/local--files/numerus/numerus_background_header_image.png" alt="hidden header"/>
          <div class="scp-image-caption"><p>.</p></div>
        </div>
      </div>
      <p>正文内容</p>
      <img src="/images/visible.png" alt="visible"/>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    assert "hidden header" not in result.xhtml
    assert "numerus_background_header_image.png" not in result.xhtml
    assert "正文内容" in soup.get_text(" ", strip=True)
    assert [img["src"] for img in soup.find_all("img")] == ["https://scp-wiki-cn.wikidot.com/images/visible.png"]
    assert result.asset_urls == ("https://scp-wiki-cn.wikidot.com/images/visible.png",)


def test_removes_authorbox_list_pages_metadata_without_removing_article_body():
    html = """
    <html><body><div id="page-content">
      <div class="limit">
        <div class="anchor">
          <div class="authorbox">
            <div class="list-pages-box">
              <div class="list-pages-item">
                <table class="wiki-content-table">
                  <tr><th>Illac</th></tr>
                  <tr>
                    <td>
                      <strong>By:</strong>
                      <span class="printuser avatarhover">
                        <a href="/user:leebr"><img class="small" src="/avatar.png" alt="LeeBr"/></a>
                        <a href="/user:leebr">LeeBr</a>
                      </span>
                    </td>
                  </tr>
                  <tr><th>Published on 09 Mar 2023 09:11</th></tr>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
      <h1>Illac</h1>
      <p>四千年之前，当我们搭上人类最后一艘幸存的星际飞船。</p>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    assert soup.find(class_="authorbox") is None
    assert soup.find("img", alt="LeeBr") is None
    page_text = soup.get_text(" ", strip=True)
    assert "Published on" not in page_text
    assert "LeeBr" not in page_text
    assert soup.find("h1").get_text(strip=True) == "Illac"
    assert "四千年之前" in page_text
    assert result.asset_urls == ()


def test_keeps_scene_break_scp_logo_small_and_centered():
    html = """
    <html><body><div id="page-content">
      <p>其后，我们决定进入低温休眠。</p>
      <div class="image-container aligncenter">
        <img class="scene-break" src="/local--files/theme:classic/scp_foundation_logo.png" alt="scp_foundation_logo.png"/>
      </div>
      <p>当我们在十六亿光年外的目的地醒来时。</p>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    image = soup.find("img", class_="scene-break")
    assert image is not None
    assert image["src"] == "https://scp-wiki-cn.wikidot.com/local--files/theme:classic/scp_foundation_logo.png"
    assert "width: 96px" in image["style"]
    assert "max-width: 40%" in image["style"]
    assert "text-align: center" in image.parent["style"]
    assert result.asset_urls == ("https://scp-wiki-cn.wikidot.com/local--files/theme:classic/scp_foundation_logo.png",)


def test_preserves_document_styles_that_target_page_content():
    html = """
    <html>
      <head>
        <style>
          .blankframe { border: double 3px #555; padding: 1em; }
          div.console::before { content: "43NET"; display: block; }
          .unused-site-chrome { color: red; }
        </style>
      </head>
      <body>
        <div id="page-content">
          <div class="blankframe">
            <div class="console">移动设备报告</div>
          </div>
        </div>
      </body>
    </html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    style = soup.find("style")
    assert style is not None
    style_text = style.get_text()
    assert ".blankframe" in style_text
    assert "div.console::before" not in style_text
    assert ".unused-site-chrome" not in style_text
    assert soup.find(class_="blankframe") is not None
    assert soup.find(class_="console").find(class_="generated-before").get_text(strip=True) == "43NET"


def test_skips_unsupported_anomaly_bar_document_styles():
    html = """
    <html>
      <head>
        <style>
          .blankframe { border: double 3px #555; padding: 1em; }
          .anom-bar-container { display: flex; width: 100%; }
          .danger-diamond > .arrows { position: absolute; mask-image: url("data:image/svg+xml,AAAA"); }
          .text-part .risk-class::before { position: absolute; background-color: #222; }
        </style>
      </head>
      <body>
        <div id="page-content">
          <div class="blankframe">移动设备报告</div>
          <div class="anom-bar-container">
            <div class="danger-diamond"><div class="arrows"></div></div>
            <div class="text-part"><div class="risk-class">危急</div></div>
          </div>
        </div>
      </body>
    </html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    style = soup.find("style")
    assert style is not None
    style_text = style.get_text()
    assert ".blankframe" in style_text
    assert ".anom-bar-container" not in style_text
    assert ".danger-diamond" not in style_text
    assert ".risk-class" not in style_text


def test_skips_page_style_rules_with_unexpanded_wikidot_template_placeholders():
    html = r"""
    <html>
      <head>
        <style>
          .earthworm { color: #6c4b32; }
          .earthworm__previous\{\$previous-title\} { color: #8f0000; }
          .article-frame { border: 1px solid #555; }
        </style>
      </head>
      <body>
        <div id="page-content">
          <div class="earthworm">Earthworm content</div>
          <div class="earthworm__previous">Previous title content</div>
          <div class="article-frame">Article content</div>
        </div>
      </body>
    </html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)
    style_text = soup.find("style").get_text()

    assert ".earthworm {color: #6c4b32;}" in style_text
    assert ".article-frame {border: 1px solid #555;}" in style_text
    assert ".earthworm__previous" not in style_text
    assert "previous-title" not in style_text


def test_materializes_page_style_before_content_labels():
    html = """
    <html>
      <head>
        <style>
          #page-content .clioframe::before {
            content: "𓏢 CLIOMETRIA.AIC";
            display: block;
            font-weight: bold;
          }
          #page-content .blankframe::before {
            content: "📱 Blank，Harold R.博士";
            display: block;
            font-weight: bold;
          }
        </style>
      </head>
      <body>
        <div id="page-content">
          <div class="clioframe"><div class="cliomain">时刻都在。</div></div>
          <div class="blankframe"><div class="blank">你在吗？</div></div>
        </div>
      </body>
    </html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    clio_label = soup.find(class_="generated-before")
    assert clio_label is not None
    assert clio_label.get_text(strip=True) == "𓏢 CLIOMETRIA.AIC"
    assert soup.find(class_="clioframe").find(class_="generated-before") is clio_label

    blank_label = soup.find(class_="blankframe").find(class_="generated-before")
    assert blank_label is not None
    assert blank_label.get_text(strip=True) == "📱 Blank，Harold R.博士"


def test_materializes_child_before_labels_without_overlaying_source_pseudo_rules():
    html = """
    <html>
      <head>
        <style>
          .blbf-main > div {
            border: 0.25rem solid #990000;
            margin: 1.5rem 0.5rem 0.5rem 0.5rem;
          }
          .blbf-main > div::before {
            content: " ";
            position: absolute;
            top: -1.25rem;
            left: -0.5rem;
            padding: 0.5em;
            font-size: calc(12px + (14 - 12) * ((100vw - 300px) / (800 - 300)));
            font-weight: 600;
            background-color: #990000;
            color: #ffffff;
          }
          .blbf-main > div.blbf-1::before {
            content: "秘密行动通知";
          }
          .blbf-main > div.blbf-2::before {
            content: "对象概览";
          }
        </style>
      </head>
      <body>
        <div id="page-content">
          <div class="blbf-main">
            <div class="blbf-1"><p>第一段正文。</p></div>
            <div class="blbf-2"><p>第二段正文。</p></div>
          </div>
        </div>
      </body>
    </html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    style_text = soup.find("style").get_text()
    assert ".blbf-main > div {" in style_text
    assert ".blbf-main > div::before" not in style_text
    assert ".blbf-main > div.blbf-1::before" not in style_text

    first_label = soup.find(class_="blbf-1").find(class_="generated-before", recursive=False)
    assert first_label is not None
    assert first_label.name == "div"
    assert first_label.get_text(strip=True) == "秘密行动通知"
    assert "margin-top: -1.75em" in first_label["style"]
    assert "margin-bottom: 0.75em" in first_label["style"]

    first_label_badge = first_label.find(class_="generated-before-label")
    assert first_label_badge is not None
    assert first_label_badge.name == "span"
    assert "background-color: #990000" in first_label_badge["style"]
    assert "font-size: 0.875em" in first_label_badge["style"]
    assert "calc(" not in first_label_badge["style"]
    assert "position:" not in first_label_badge["style"]

    second_label = soup.find(class_="blbf-2").find(class_="generated-before", recursive=False)
    assert second_label is not None
    assert second_label.name == "div"
    assert second_label.get_text(strip=True) == "对象概览"


def test_does_not_materialize_complex_generated_before_selectors():
    html = """
    <html>
      <head>
        <style>
          .speaker::before { content: "发言人"; font-weight: bold; }
          .grid-table > *:nth-child(3n-2)::before { content: "SCP"; display: block; }
        </style>
      </head>
      <body>
        <div id="page-content">
          <div class="speaker">正文</div>
          <div class="grid-table">
            <div>A</div><div>B</div><div>C</div>
          </div>
        </div>
      </body>
    </html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    assert soup.find(class_="speaker").find(class_="generated-before").get_text(strip=True) == "发言人"
    assert soup.find(class_="grid-table").find(class_="generated-before") is None


def test_ignores_invalid_generated_before_selectors_without_dropping_valid_labels():
    html = """
    <html>
      <head>
        <style>
          :is(div.notation, div.darkdocument)::before { content: "坏规则"; display: block; }
          .speaker::before { content: "发言人"; font-weight: bold; }
        </style>
      </head>
      <body>
        <div id="page-content">
          <div class="speaker">正文</div>
          <div class="darkdocument">暗色文档</div>
        </div>
      </body>
    </html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    assert soup.find(class_="speaker").find(class_="generated-before").get_text(strip=True) == "发言人"
    assert soup.find(class_="darkdocument").find(class_="generated-before") is None


def test_converts_css_grid_tables_to_epub_tables():
    html = """
    <html><body><div id="page-content">
      <div class="grid-table">
        <div class="title"><p>SCP描述</p></div>
        <div class="title"><p>001-K描述</p></div>
        <div class="title"><p>收容方式</p></div>
        <div><p><a href="/scp-1048">SCP-1048</a> - 泰迪熊。</p></div>
        <div><p><a href="/scp-1054-ru">K-1054-RU</a> - 飞机引擎。</p></div>
        <div><p>互相制衡。</p></div>
      </div>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL, {"scp-1048", "scp-1054-ru"})
    soup = soup_fragment(result.xhtml)

    assert soup.find("div", class_="grid-table") is None
    table = soup.find("table", class_="grid-table-epub")
    assert table is not None
    assert [cell.get_text(" ", strip=True) for cell in table.find_all("th")] == [
        "SCP描述",
        "001-K描述",
        "收容方式",
    ]
    rows = table.find_all("tr")
    assert len(rows) == 2
    assert [cell.name for cell in rows[1].find_all(["td", "th"])] == ["td", "td", "td"]
    assert "background-color: #ff1d45" in table.find("th")["style"]
    assert "background-color: #21252E" in table.find("td")["style"]
    assert table.find("a", href="https://scp-wiki-cn.wikidot.com/scp-1048") is not None


def test_expands_wikidot_tabs_into_labeled_epub_sections():
    html = """
    <html><body><div id="page-content">
      <div class="yui-navset" id="wiki-tabview-series">
        <ul class="yui-nav">
          <li class="selected"><a><em>斯洛斯皮特，威斯康星州</em></a></li>
          <li><a><em>Site-87</em></a></li>
          <li><a><em>林中之物</em></a></li>
        </ul>
        <div class="yui-content">
          <div><p>斯洛斯皮特的介绍。</p></div>
          <div style="display: none;">
            <div class="scp-image-block block-right">
              <img src="/local--files/site-87/photo.png" alt="Site-87"/>
            </div>
            <p>Site-87 的介绍。</p>
          </div>
          <div><p>林中之物的介绍。</p></div>
        </div>
      </div>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    assert soup.find(class_="yui-navset") is None
    assert soup.find(class_="yui-nav") is None
    assert soup.find(class_="yui-content") is None

    tabview = soup.find("div", class_="tabview-epub")
    assert tabview is not None
    sections = tabview.find_all("section", class_="tabview-panel-epub", recursive=False)
    assert [section.find("h3").get_text(strip=True) for section in sections] == [
        "标签：斯洛斯皮特，威斯康星州",
        "标签：Site-87",
        "标签：林中之物",
    ]
    assert [section.find("p").get_text(strip=True) for section in sections] == [
        "斯洛斯皮特的介绍。",
        "Site-87 的介绍。",
        "林中之物的介绍。",
    ]
    assert sections[1].find("img", alt="Site-87") is not None


def test_keeps_scp001_wikidot_tabs_unchanged():
    html = """
    <html><body><div id="page-content">
      <div class="content-panel">
        <div class="yui-navset" id="wiki-tabview-scp001">
          <ul class="yui-nav">
            <li class="selected"><a><em>随机排序</em></a></li>
            <li><a><em>按时间顺序展示</em></a></li>
          </ul>
          <div class="yui-content">
            <div><p>随机列表。</p></div>
            <div><p>时间顺序列表。</p></div>
          </div>
        </div>
      </div>
    </div></body></html>
    """
    entry = PageRef(title="SCP-001", url="https://scp-wiki-cn.wikidot.com/scp-001", slug="scp-001", level=1, role="scp")

    result = transform_page(entry, html, entry.url)
    soup = soup_fragment(result.xhtml)

    assert soup.find(class_="tabview-epub") is None
    assert soup.find("div", class_="yui-navset") is not None
    assert soup.find("ul", class_="yui-nav") is not None
    assert soup.find("div", class_="yui-content") is not None


def test_clears_floats_before_framed_blocks_without_clearing_plain_paragraphs():
    html = """
    <html><body><div id="page-content">
      <div class="scp-image-block block-right" style="width:300px;">
        <img src="/images/right.png" alt="right"/>
      </div>
      <p>这段文字仍然可以绕排图片。</p>
      <div style="border: 1px dashed #999; padding: 1em;">记录框不能被图片覆盖。</div>
      <blockquote><p>引用框也不能被图片覆盖。</p></blockquote>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    assert soup.find("p", string="这段文字仍然可以绕排图片。").get("style") is None
    framed = soup.find("div", string="记录框不能被图片覆盖。")
    assert "clear: both" in framed["style"]
    blockquote = soup.find("blockquote")
    assert "clear: both" in blockquote["style"]


def test_contains_floated_images_inside_collapsible_content():
    html = """
    <html><body><div id="page-content">
      <div class="collapsible-block">
        <div class="collapsible-block-folded"><a class="collapsible-block-link">记录1</a></div>
        <div class="collapsible-block-unfolded">
          <div class="collapsible-block-content">
            <div class="scp-image-block block-right" style="width:300px;">
              <img src="/images/cover.png" alt="cover"/>
            </div>
            <p>项目编号：SCP-001</p>
          </div>
        </div>
      </div>
      <div class="collapsible-block">
        <div class="collapsible-block-folded"><a class="collapsible-block-link">记录2</a></div>
        <div class="collapsible-block-unfolded">
          <div class="collapsible-block-content"><blockquote><p>下一段记录。</p></blockquote></div>
        </div>
      </div>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    first_content = soup.find(class_="collapsible-block-content")
    clearers = first_content.find_all("div", style="clear: both")
    assert len(clearers) == 1
    assert first_content.contents[-1] is clearers[0]
    assert "clear: both" in soup.find(class_="collapsible-block")["style"]


def test_linearizes_terminal_interactive_article_layout_for_epub():
    html = """
    <html>
      <head>
        <style>
          .terminal { border: 10px solid gray; background: #1a1a1a; color: #ededed; }
          .t-real {
            height: 80%;
            overflow-y: scroll;
            position: absolute;
            top: 0;
          }
          .foldable-list-container a:nth-child(2) {
            position: fixed;
            bottom: 1rem;
            animation: 1.5s coll-in ease-out;
          }
          .glitch-stack { display: grid; grid-template-columns: 1fr; }
          .glitch-stack span { grid-row-start: 1; grid-column-start: 1; }
        </style>
      </head>
      <body>
        <div id="page-content">
          <div class="terminal">
            <div class="colmod-block">
              <ul><li class="folded"><ul><li>_</li></ul></li></ul>
              <div class="colmod-link-top">
                <div class="foldable-list-container">
                  <a href="javascript:;">评进</a><a href="javascript:;">退却</a>
                </div>
              </div>
                  <div class="colmod-content">
                    <div class="terminal t-real">
                      <div class="declaration green">
                        <ul><li>声明条目。</li></ul>
                      </div>
                      <div class="blockquote element">
                        <p><strong>VL.001/5</strong></p>
                        <p>日志正文。</p>
                      </div>
                      <p>终端正文。</p>
                      <div class="glitch-body">
                        <div class="glitch-stack" style="--stacks: 3;">
                          <span style="--index: 0;">化身？</span>
                          <span style="--index: 1;">化身？</span>
                          <span style="--index: 2;">化身？</span>
                        </div>
                      </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </body>
    </html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    style_text = soup.find("style").get_text()
    assert ".terminal" in style_text
    assert ".terminal .blockquote" in style_text
    assert "list-style-type: square" in style_text
    assert ".glitch-body" in style_text
    assert ".glitch-stack span" in style_text
    assert ".t-real" not in style_text
    assert ".foldable-list-container" not in style_text
    assert "position: absolute" not in style_text
    assert "position: fixed" not in style_text
    assert "overflow-y: scroll" not in style_text
    assert "clip-path" not in style_text

    terminal = soup.find(class_="terminal")
    assert terminal is not None
    assert soup.find(class_="t-real") is None
    assert soup.find(class_="foldable-list-container") is None
    assert "_" not in soup.get_text(" ", strip=True)
    assert "评进" not in soup.get_text(" ", strip=True)
    assert "退却" not in soup.get_text(" ", strip=True)
    assert "终端正文。" in soup.find(class_="colmod-content").get_text(" ", strip=True)
    assert soup.select_one(".blockquote") is not None

    glitch_stack = soup.find(class_="glitch-stack")
    assert glitch_stack is not None
    assert [span.get_text(strip=True) for span in glitch_stack.find_all("span")] == ["化身？"]


def test_does_not_linearize_ordinary_collapsible_layouts():
    html = """
    <html>
      <head>
        <style>
          .ordinary-note { position: absolute; color: red; }
          .collapsible-block-content { border: 1px solid #999; }
        </style>
      </head>
      <body>
        <div id="page-content">
          <div class="ordinary-note">普通说明。</div>
          <div class="collapsible-block">
            <div class="collapsible-block-folded"><a class="collapsible-block-link">记录</a></div>
            <div class="collapsible-block-unfolded">
              <div class="collapsible-block-content"><p>普通折叠内容。</p></div>
            </div>
          </div>
        </div>
      </body>
    </html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    style_text = soup.find("style").get_text()
    assert ".ordinary-note {position: absolute; color: red;}" in style_text
    assert ".collapsible-block-content" in style_text
    assert soup.find(class_="ordinary-note") is not None
    assert soup.find(class_="collapsible-block-content").get_text(strip=True) == "普通折叠内容。"


def test_expands_only_included_wikidot_tab_labels():
    html = """
    <html><body><div id="page-content">
      <div class="yui-navset">
        <ul class="yui-nav">
          <li><a><em>简介</em></a></li>
          <li><a><em>写作指南</em></a></li>
        </ul>
        <div class="yui-content">
          <div><p>基金会简介正文。</p></div>
          <div><p>写作指南正文。</p></div>
        </div>
      </div>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL, include_tab_titles={"简介"})
    soup = soup_fragment(result.xhtml)
    text = soup.get_text(" ", strip=True)

    assert "标签：简介" in text
    assert "基金会简介正文" in text
    assert "写作指南" not in text
    assert "写作指南正文" not in text


def test_unwraps_explicitly_configured_single_wikidot_tab_and_registers_its_background_asset():
    marble_url = "https://scp-wiki.wdfiles.com/local--files/about-the-scp-foundation/bg-marble.png"
    html = """
    <html><body><div id="page-content">
      <div class="yui-navset">
        <ul class="yui-nav">
          <li><a><em>简介</em></a></li>
          <li><a><em>写作指南</em></a></li>
        </ul>
        <div class="yui-content">
          <div><div class="content-panel standalone">基金会简介正文。</div><h1>使命宣言</h1></div>
          <div><p>写作指南正文。</p></div>
        </div>
      </div>
    </div></body></html>
    """

    result = transform_page(
        page_ref(),
        html,
        BASE_URL,
        include_tab_titles={"简介"},
        unwrap_single_included_tab=True,
        background_asset_url=marble_url,
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(class_="tabview-epub") is None
    assert soup.find(class_="tabview-panel-title") is None
    assert "标签：简介" not in soup.get_text(" ", strip=True)
    assert "基金会简介正文" in soup.get_text(" ", strip=True)
    assert "写作指南正文" not in soup.get_text(" ", strip=True)
    assert soup.find("h1").get_text(strip=True) == "使命宣言"
    panel = soup.find("div", attrs={"class": "content-panel standalone"})
    assert panel is not None
    assert panel["data-epub-background-url"] == marble_url
    assert result.asset_urls == (marble_url,)


def test_unwraps_selected_appendix_tab_child_without_the_tabview_heading_or_wrapper():
    entry = PageRef(
        title="研究人员",
        url=f"{BASE_URL}/personnel-and-character-dossier",
        slug="personnel-and-character-dossier--tab-2",
        level=3,
        role="appendix-tab",
        parent_slug="personnel-and-character-dossier",
        tab_title="研究人员",
    )
    html = """
    <html><body><div id="page-content">
      <div class="yui-navset">
        <ul class="yui-nav"><li>人事档案</li><li>研究人员</li></ul>
        <div class="yui-content"><div><p>档案正文。</p></div><div><p>研究正文。</p></div></div>
      </div>
    </div></body></html>
    """

    result = transform_page(
        entry,
        html,
        BASE_URL,
        include_tab_titles={entry.tab_title},
        unwrap_single_included_tab=True,
    )
    soup = soup_fragment(result.xhtml)
    text = soup.get_text(" ", strip=True)

    assert "研究正文。" in text
    assert "档案正文。" not in text
    assert soup.find(class_="tabview-epub") is None
    assert soup.find(class_="tabview-panel-title") is None
    assert "标签：研究人员" not in text


def test_removes_generic_hidden_css_code_styles_from_page_styles():
    html = """
    <html>
      <head>
        <style>
          #page-content .collapsible-block { position: relative; }
          .collapsible-block-unfolded { color: black; }
          .collapsible-block-link { font-weight: bold; }
          .wiki-content-table { width: 100%; }
          #page-content { max-width: 45rem; }
          #page-content .court-seal { text-align: center; }
        </style>
      </head>
      <body>
        <div id="page-content">
          <div class="court-seal">法院正文。</div>
          <div style="display: none">
            <div class="code"><pre>#page-content .collapsible-block { position: relative; }</pre></div>
          </div>
        </div>
      </body>
    </html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)
    style_text = soup.find("style").get_text()

    assert "#page-content .collapsible-block" not in style_text
    assert ".collapsible-block-unfolded" not in style_text
    assert ".collapsible-block-link" not in style_text
    assert ".wiki-content-table" not in style_text
    assert "#page-content {" not in style_text
    assert ".court-seal" in style_text
    assert "#page-content .collapsible-block" not in soup.get_text(" ", strip=True)


def test_removes_scp173_creator_information_block():
    html = """
    <html><body><div id="page-content">
      <p><strong>项目编号：</strong>SCP-173</p>
      <p><strong>描述：</strong>正文保留。</p>
      <hr />
      <p><strong><span style="text-decoration: underline;">创作者信息</span></strong></p>
      <p><sup>SCP-173中所使用的图像为加藤泉所创作的艺术作品。</sup></p>
      <p><sup><strong>不得使用《无题 2004》开展任何商业活动。</strong></sup></p>
      <div class="footer-wikiwalk-nav"><p>上一页 | 下一页</p></div>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)
    text = soup.get_text(" ", strip=True)

    assert "正文保留" in text
    assert "创作者信息" not in text
    assert "加藤泉" not in text
    assert "无题 2004" not in text


def test_removes_only_terminal_guillemet_navigation_when_enabled():
    html = """
    <html><body><div id="page-content">
      <div id="earlier-nav">« <a href="/one">One</a> | <a href="/two">Two</a> | <a href="/three">Three</a> »</div>
      <p>正文中的 « <a href="/one">One</a> | <a href="/two">Two</a> » 应保留。</p>
      <div id="terminal-nav">« <a href="/one">One</a> | <a href="/two">Two</a> | <a href="/three">Three</a> »</div>
    </div></body></html>
    """

    result = transform_page(
        page_ref(),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="terminal-nav") is None
    assert soup.find(id="earlier-nav") is not None
    assert "正文中的" in soup.get_text(" ", strip=True)


@pytest.mark.parametrize("slug", ("scp-7261", "scp-3662"))
def test_removes_terminal_two_link_guillemet_navigation_when_enabled(slug: str):
    html = """
    <html><body><div id="page-content">
      <p id="article">正文。</p>
      <div id="terminal-nav">« <a href="/one">One</a> | <a href="/two">Two</a> »</div>
    </div></body></html>
    """

    result = transform_page(
        page_ref(slug),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="terminal-nav") is None
    assert soup.find(id="article") is not None


def test_removes_nested_scp7261_terminal_navigation_before_insignificant_wrappers():
    html = """
    <html><body><div id="page-content">
      <p id="article">正文。</p>
      <div class="terminal-layout">
        <div class="earthworm" id="terminal-nav">« <a href="/one">One</a> | <a href="/two">Two</a> »</div>
        <div class="list-pages-box"></div>
        <div><div class="code"><pre>:root { --accent: red; --header-title: "Site-120"; }</pre></div></div>
      </div>
      <p></p>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-7261"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="terminal-nav") is None
    assert soup.find(id="article") is not None


def test_preserves_non_target_terminal_two_link_guillemet_content_when_enabled():
    html = """
    <html><body><div id="page-content">
      <p id="article">正文。</p>
      <div id="terminal-content">« <a href="/one">One</a> | <a href="/two">Two</a> »</div>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-9928"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )

    assert soup_fragment(result.xhtml).find(id="terminal-content") is not None


def test_preserves_nested_navigation_when_its_ancestor_has_following_article_content():
    html = """
    <html><body><div id="page-content">
      <div class="terminal-layout">
        <div id="terminal-nav">« <a href="/one">One</a> | <a href="/two">Two</a> »</div>
        <p id="after">后续正文。</p>
      </div>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-7261"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="terminal-nav") is not None
    assert soup.find(id="after") is not None


def test_preserves_configured_navigation_followed_by_textless_figure_svg():
    html = """
    <html><body><div id="page-content">
      <p id="article">正文。</p>
      <div id="terminal-nav">« <a href="/one">One</a> | <a href="/two">Two</a> | <a href="/three">Three</a> »</div>
      <figure id="diagram"><svg viewBox="0 0 10 10"><path d="M0 0 L10 10" /></svg></figure>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-9928"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="terminal-nav") is not None
    assert soup.find(id="diagram") is not None


def test_removes_scp7261_navigation_before_earthworm_decoration():
    html = """
    <html><body><div id="page-content">
      <div class="anom-bar-esoteric" id="classification">项目编号：7261</div>
      <div id="terminal-nav">« <a href="/previous">Previous</a> | <a href="/next">Next</a> »</div>
      <div class="earthworm" id="earthworm"><img src="/images/earthworm.png" alt="earthworm" />SCP-7990 九异书 SCP-5938</div>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-7261"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="terminal-nav") is None
    assert soup.find(id="classification") is not None
    assert soup.find(id="earthworm") is not None


def test_preserves_other_pages_navigation_before_earthworm_decoration():
    html = """
    <html><body><div id="page-content">
      <p id="article">正文。</p>
      <div id="terminal-nav">« <a href="/one">One</a> | <a href="/two">Two</a> »</div>
      <div class="earthworm">非目标页面的装饰内容。</div>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-3662"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )

    assert soup_fragment(result.xhtml).find(id="terminal-nav") is not None


def test_does_not_apply_scp7261_earthworm_navigation_exception_to_author_work_lists():
    html = """
    <html><body><div id="page-content">
      <div id="work-list">More From This Author <a href="/author">作品</a></div>
      <div class="earthworm">SCP-7990 九异书 SCP-5938</div>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-7261"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_author_work_list=True),
    )

    assert soup_fragment(result.xhtml).find(id="work-list") is not None


@pytest.mark.parametrize(
    ("slug", "trailing_wrappers"),
    (
        (
            "scp-9928",
            '<div class="list-pages-box"></div><p></p>',
        ),
        (
            "scp-5109",
            '<div><div class="code"><pre>:root { --accent: red; --header-title: "Site-120"; }</pre></div></div>',
        ),
        (
            "scp-5494",
            '<div class="list-pages-box"></div><div><div class="code"><pre>:root { --accent: red; --header-title: "Site-120"; }</pre></div></div>',
        ),
    ),
)
def test_removes_effectively_terminal_navigation_before_live_like_trailing_wrappers(
    slug: str,
    trailing_wrappers: str,
):
    html = f"""
    <html><body><div id="page-content">
      <p id="article">正文。</p>
      <div id="terminal-nav">« <a href="/one">One</a> | <a href="/two">Two</a> | <a href="/three">Three</a> »</div>
      {trailing_wrappers}
    </div></body></html>
    """

    result = transform_page(
        page_ref(slug),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="terminal-nav") is None
    assert soup.find(id="article") is not None


def test_removes_terminal_navigation_before_footnotes_footer_and_preserves_footnotes():
    html = """
    <html><body><div id="page-content">
      <p id="article">正文。</p>
      <div style="text-align: center;" id="terminal-nav">
        <p><strong>« <a href="/previous">Previous</a> | <a href="/hub">Hub</a> | <a href="/next">Next</a> »</strong></p>
      </div>
      <div class="footnotes-footer" id="footnotes">
        <div class="title">Footnotes</div><div>1. 应保留的注释。</div>
      </div>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-5550"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="terminal-nav") is None
    assert soup.find(id="footnotes").get_text(" ", strip=True) == "Footnotes 1. 应保留的注释。"
    assert soup.find(id="article") is not None


def test_preserves_terminal_navigation_when_cleanup_is_disabled():
    html = """
    <html><body><div id="page-content">
      <p>正文。</p>
      <div id="terminal-nav">« <a href="/one">One</a> | <a href="/two">Two</a> »</div>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)

    assert soup_fragment(result.xhtml).find(id="terminal-nav") is not None


def test_removes_scp6781_terminal_previous_and_next_navigation_when_enabled():
    html = """
    <html><body><div id="page-content">
      <p id="article">正文。</p>
      <div class="rnb-navbar">
        <a href="/previous"><span class="rnb-supertitle">前情</span><br />« 档案 »</a>
        <a href="/current">当前文档</a>
        <a href="/next"><span class="rnb-supertitle">后事</span><br />« 后续 »</a>
      </div>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-6781"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )

    soup = soup_fragment(result.xhtml)
    assert soup.find(class_="rnb-navbar") is None
    assert soup.find(id="article") is not None


def test_preserves_scp6781_navigation_when_disabled_or_labels_do_not_link():
    navigation = """
      <div class="rnb-navbar">
        <a href="/previous"><span class="rnb-supertitle">前情</span><br />« 档案 »</a>
        <a href="/next"><span class="rnb-supertitle">后事</span><br />« 后续 »</a>
      </div>
    """
    disabled_html = f"""
    <html><body><div id="page-content">
      <p id="before">相邻正文。</p>{navigation}
    </div></body></html>
    """
    nonmatching_html = """
    <html><body><div id="page-content">
      <p id="before">相邻正文。</p>
      <div class="rnb-navbar">
        <a href="/previous"><span class="rnb-supertitle">前情</span><span class="rnb-supertitle">后事</span></a>
        <a href="/next">« 后续 »</a>
      </div>
    </div></body></html>
    """

    disabled = transform_page(page_ref("scp-6781"), disabled_html, BASE_URL)
    nonmatching = transform_page(
        page_ref("scp-6781"),
        nonmatching_html,
        BASE_URL,
        page_options=PageTransformOptions(remove_terminal_navigation=True),
    )

    for result in (disabled, nonmatching):
        soup = soup_fragment(result.xhtml)
        assert soup.find(class_="rnb-navbar") is not None
        assert soup.find(id="before") is not None


def test_removes_scp5464_leading_hub_breadcrumb_and_author_block_when_enabled():
    html = """
    <html><body><div id="page-content">
      <p id="breadcrumb"><a href="/setting-hub">设定中心</a> &gt; 波兰设定</p>
      <div id="author-block">作者：Example Author</div>
      <p id="article">第一段正文。</p>
      <p>后续内容提及作者：应保留。</p>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-5464"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_leading_metadata=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="breadcrumb") is None
    assert soup.find(id="author-block") is None
    assert soup.find(id="article").get_text(strip=True) == "第一段正文。"
    assert "后续内容提及作者" in soup.get_text(" ", strip=True)


def test_removes_scp5464_metadata_after_live_dom_template_and_empty_nodes():
    html = """
    <html><body><div id="page-content">
      <div class="list-pages-box"></div>
      <p></p>
      <div><div class="code"><pre>:root { --accent: red; --header-title: "Site-120"; }</pre></div></div>
      <p></p>
      <div class="pseudocrumbs"><a href="/canon-hub">设定中心</a> » <a href="/from-120-s-archives-hub">120站档案馆中心页</a> » SCP-5464</div>
      <div></div>
      <div style="text-align: center;"><p><span style="font-size:80%;">作者：<strong>Ralliston</strong></span></p></div>
      <div class="anom-bar-container">项目编号：SCP-5464</div>
      <p id="first-body"><strong>特殊收容措施：</strong>第一段正文必须保留。</p>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-5464"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_leading_metadata=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(class_="pseudocrumbs") is None
    assert "作者：" not in soup.get_text(" ", strip=True)
    assert soup.find(id="first-body").get_text(" ", strip=True).endswith("第一段正文必须保留。")


def test_preserves_leading_metadata_for_other_pages_and_when_disabled():
    html = """
    <html><body><div id="page-content">
      <p id="breadcrumb"><a href="/setting-hub">设定中心</a> &gt; 波兰设定</p>
      <div id="author-block">作者：Example Author</div>
      <p id="article">第一段正文。</p>
    </div></body></html>
    """

    disabled = transform_page(page_ref("scp-5464"), html, BASE_URL)
    other_page = transform_page(
        page_ref("scp-999"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_leading_metadata=True),
    )

    assert soup_fragment(disabled.xhtml).find(id="author-block") is not None
    assert soup_fragment(other_page.xhtml).find(id="author-block") is not None


def test_removes_scp7069_adult_warning_only_when_enabled():
    html = """
    <html><body><div id="page-content">
      <div id="u-adult-warning"><p>成人内容警告。</p></div>
      <p id="article">正文。</p>
    </div></body></html>
    """

    enabled = transform_page(
        page_ref("scp-7069"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_adult_content_warning=True),
    )
    disabled = transform_page(page_ref("scp-7069"), html, BASE_URL)
    other_page = transform_page(
        page_ref("scp-999"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_adult_content_warning=True),
    )

    assert soup_fragment(enabled.xhtml).find(id="u-adult-warning") is None
    assert soup_fragment(enabled.xhtml).find(id="article") is not None
    assert soup_fragment(disabled.xhtml).find(id="u-adult-warning") is not None
    assert soup_fragment(other_page.xhtml).find(id="u-adult-warning") is not None


def test_removes_only_terminal_author_work_list_when_enabled():
    html = """
    <html><body><div id="page-content">
      <p id="ordinary">More by this author appears in the article.</p>
      <p>正文。</p>
      <div id="work-list">该作者的更多作品<a href="/author-page">作品一</a></div>
    </div></body></html>
    """

    result = transform_page(
        page_ref(),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_author_work_list=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="work-list") is None
    assert soup.find(id="ordinary") is not None


def test_removes_folded_collapsible_author_work_list_when_enabled():
    html = """
    <html><body><div id="page-content">
      <p id="article">正文。</p>
      <div class="collection" id="work-list">
        <div class="collapsible-block" id="author-work-list">
          <div class="collapsible-block-folded"><a href="javascript:;">More&nbsp;From&nbsp;This&nbsp;Author</a></div>
          <div class="collapsible-block-unfolded"><p>作者的作品列表。</p></div>
        </div>
      </div>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-6698"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_author_work_list=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="author-work-list") is None
    assert soup.find(id="work-list") is not None
    assert soup.find(id="article") is not None


def test_removes_nested_author_work_link_from_centered_wrapper_when_enabled():
    html = """
    <html><body><div id="page-content">
      <p id="ordinary">More by this author appears in the article body.</p>
      <p id="article">正文。</p>
      <div class="footnotes-footer" id="footnotes"><div>1. 应保留的注释。</div></div>
      <div style="text-align: center;" id="author-work-wrapper">
        <p><strong><span class="logical-link-wrap"><span class="logical-link-custom"><a href="/author">此作者的更多作品</a></span><span class="logical-link-original"><span class="logical-link-custom"><a href="https://example.test/author">More by this author</a></span></span></span></strong></p>
      </div>
      <div class="footer-wikiwalk-nav" id="wikiwalk">« <a href="/previous">Previous</a> | <a href="/next">Next</a> »</div>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-4233"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_author_work_list=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="author-work-wrapper") is None
    assert soup.find(id="footnotes").get_text(" ", strip=True) == "1. 应保留的注释。"
    assert soup.find(id="ordinary") is not None


def test_preserves_non_terminal_article_body_author_label_links_when_enabled():
    html = """
    <html><body><div id="page-content">
      <div id="article-body">
        <p><a id="english-body-link" href="/reference">More by this author</a> is cited in this paragraph.</p>
        <p><a id="chinese-body-link" href="/reference">该作者的更多作品</a>是本段引用的一部分。</p>
        <p id="after-links">后续正文。</p>
      </div>
      <div class="footnotes-footer"><div>1. 注释。</div></div>
      <div style="text-align: center;" id="author-work-wrapper">
        <p><strong><span class="logical-link-wrap"><span class="logical-link-custom"><a href="/author">此作者的更多作品</a></span><span class="logical-link-original"><span class="logical-link-custom"><a href="https://example.test/author">More by this author</a></span></span></span></strong></p>
      </div>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-4233"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_author_work_list=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="article-body") is not None
    assert soup.find(id="english-body-link") is not None
    assert soup.find(id="chinese-body-link") is not None
    assert soup.find(id="after-links") is not None
    assert soup.find(id="author-work-wrapper") is None


def test_preserves_terminal_article_body_when_removing_logical_author_link():
    html = """
    <html><body><div id="page-content">
      <div id="article-body">
        <p id="before-link">正文。</p>
        <p><strong><span class="logical-link-wrap"><span class="logical-link-custom"><a id="author-work-link" href="/author">More by this author</a></span></span></strong></p>
      </div>
    </div></body></html>
    """

    result = transform_page(
        page_ref("scp-4233"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_author_work_list=True),
    )
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="article-body") is not None
    assert soup.find(id="author-work-link") is None
    assert soup.find(id="before-link") is not None


def test_preserves_author_work_list_when_cleanup_is_disabled_or_not_terminal():
    terminal_html = """
    <html><body><div id="page-content">
      <p>正文。</p><div id="work-list">More From This Author<a href="/author">作品</a></div>
    </div></body></html>
    """
    non_terminal_html = """
    <html><body><div id="page-content">
      <div id="work-list">More by this author<a href="/author">作品</a></div><p>后续正文。</p>
    </div></body></html>
    """

    disabled = transform_page(page_ref(), terminal_html, BASE_URL)
    non_terminal = transform_page(
        page_ref(),
        non_terminal_html,
        BASE_URL,
        page_options=PageTransformOptions(remove_author_work_list=True),
    )

    assert soup_fragment(disabled.xhtml).find(id="work-list") is not None
    assert soup_fragment(non_terminal.xhtml).find(id="work-list") is not None


def test_preserves_terminal_content_that_only_starts_with_an_author_work_list_label():
    html = """
    <html><body><div id="page-content">
      <p>正文。</p>
      <div id="ordinary-terminal">More by this authoring team is archived here.</div>
    </div></body></html>
    """

    result = transform_page(
        page_ref(),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_author_work_list=True),
    )

    assert soup_fragment(result.xhtml).find(id="ordinary-terminal") is not None


def test_converts_ruby_annotation_spans_to_semantic_ruby():
    html = """
    <html><body><div id="page-content">
      <p><span class="ruby">本质性复合体<span class="rt">ESSOPLEX</span></span>已被破坏。</p>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    ruby = soup.find("ruby")
    assert ruby is not None
    assert ruby.find("rt").get_text(strip=True) == "ESSOPLEX"
    assert ruby.get_text(" ", strip=True) == "本质性复合体 ESSOPLEX"
    assert soup.find("span", class_="ruby") is None
    assert soup.find("span", class_="rt") is None


def test_missing_page_content_raises_value_error():
    with pytest.raises(ValueError, match="#page-content"):
        transform_page(page_ref(), "<html><body><p>No content</p></body></html>", BASE_URL)


def inline_spec(
    title: str,
    position: str,
    *,
    anchor_text: str | None = None,
) -> InlineDocumentSpec:
    return InlineDocumentSpec(
        title=title,
        url=f"{BASE_URL}/{title.lower()}",
        slug=title.lower(),
        position=position,
        anchor_text=anchor_text,
    )


def inline_page(title: str, xhtml: str, *, assets: tuple[str, ...] = (), internal: tuple[str, ...] = (), external: tuple[str, ...] = ()) -> ProcessedPage:
    return ProcessedPage(
        entry=PageRef(title, f"{BASE_URL}/{title.lower()}", title.lower(), 1, "scp"),
        xhtml=xhtml,
        asset_urls=assets,
        internal_links=internal,
        external_links=external,
    )


def test_inserts_inline_document_after_normalized_exact_visible_text():
    owner = inline_page(
        "Owner",
        "<p>前文。</p><p>附录-1898-1：相关 <strong>SCP-1898</strong>图片</p><p>后文。</p>",
    )
    fragment = inline_page("After", "<p>内联正文。</p>")

    result = insert_inline_fragments(
        owner,
        fragments=((inline_spec("After", "after_text", anchor_text="附录-1898-1：相关 SCP-1898图片"), fragment),),
    )

    soup = soup_fragment(result.xhtml)
    assert [node.get_text(" ", strip=True) for node in soup.root.find_all(recursive=False)] == [
        "前文。",
        "附录-1898-1：相关 SCP-1898 图片",
        "After 内联正文。",
        "后文。",
    ]
    section = soup.find("section", class_="inline-document-epub")
    assert section is not None
    assert section.find("div", style="clear: both") is None


def test_inline_document_contains_its_floated_images_before_following_owner_content():
    owner = inline_page(
        "Owner",
        "<p>附录-1898-1：相关SCP-1898图片</p>"
        "<p>附录-1898-2：后续正文。</p>",
    )
    fragment = inline_page(
        "SCP-1898 相关图片",
        '<h2>SCP-1898 相关图片</h2>'
        '<div class="scp-image-block block-left"><img src="one.jpg"/></div>'
        '<div class="scp-image-block block-left"><img src="two.jpg"/></div>',
    )

    result = insert_inline_fragments(
        owner,
        fragments=(
            (
                inline_spec(
                    "SCP-1898 相关图片",
                    "after_text",
                    anchor_text="附录-1898-1：相关SCP-1898图片",
                ),
                fragment,
            ),
        ),
    )

    soup = soup_fragment(result.xhtml)
    section = soup.find("section", class_="inline-document-epub")
    appendix_2 = soup.find("p", string="附录-1898-2：后续正文。")
    assert section is not None
    assert appendix_2 is not None
    assert section.find_next_sibling() is appendix_2
    assert appendix_2.get("style") is None
    clearer = section.find_all(recursive=False)[-1]
    assert clearer.name == "div"
    assert clearer.get("style") == "clear: both"


def test_inline_document_does_not_treat_floated_image_clear_as_container_clear():
    owner = inline_page("Owner", "<p>Owner content.</p>")
    fragment = inline_page(
        "Floating fragment",
        '<div class="scp-image-block block-left" style="clear: both">'
        '<img src="image.jpg"/>'
        "</div>",
    )

    result = insert_inline_fragments(
        owner,
        fragments=((inline_spec("Floating fragment", "append"), fragment),),
    )

    soup = soup_fragment(result.xhtml)
    section = soup.find("section", class_="inline-document-epub")
    assert section is not None
    clearer = section.find_all(recursive=False)[-1]
    assert clearer.name == "div"
    assert clearer.get("class") is None
    assert clearer.get("style") == "clear: both"


def test_inline_document_preserves_single_existing_terminal_clearer():
    owner = inline_page("Owner", "<p>Owner content.</p>")
    fragment = inline_page(
        "Floating fragment",
        '<div class="scp-image-block block-left"><img src="image.jpg"/></div>'
        '<div style="clear: both"></div>',
    )

    result = insert_inline_fragments(
        owner,
        fragments=((inline_spec("Floating fragment", "append"), fragment),),
    )

    soup = soup_fragment(result.xhtml)
    section = soup.find("section", class_="inline-document-epub")
    assert section is not None
    clearers = [
        child
        for child in section.find_all("div", recursive=False)
        if child.get("class") is None and child.get("style") == "clear: both"
    ]
    assert len(clearers) == 1
    assert section.find_all(recursive=False)[-1] is clearers[0]


def test_inserts_inline_document_before_exact_visible_text():
    owner = inline_page("Owner", "<p>正文。</p><h2>Footnotes</h2><p>注释。</p>")
    fragment = inline_page("Before", "<p>内联正文。</p>")

    result = insert_inline_fragments(
        owner,
        fragments=((inline_spec("Before", "before_text", anchor_text="Footnotes"), fragment),),
    )

    soup = soup_fragment(result.xhtml)
    assert [node.get_text(" ", strip=True) for node in soup.root.find_all(recursive=False)] == [
        "正文。",
        "Before 内联正文。",
        "Footnotes",
        "注释。",
    ]


def test_inserts_inline_document_before_footnotes_footer_instead_of_nested_title():
    owner = inline_page(
        "Owner",
        "<p>正文。</p><div class=\"footnotes-footer\"><div class=\"title\">Footnotes</div><ol><li>注释。</li></ol></div>",
    )
    fragment = inline_page("Before", "<p>内联正文。</p>")

    result = insert_inline_fragments(
        owner,
        fragments=((inline_spec("Before", "before_text", anchor_text="Footnotes"), fragment),),
    )

    soup = soup_fragment(result.xhtml)
    root_children = soup.root.find_all(recursive=False)
    footer = soup.find("div", class_="footnotes-footer")
    assert [node.name for node in root_children] == ["p", "section", "div"]
    assert footer is not None
    assert footer.find("section", class_="inline-document-epub") is None


def test_removes_inline_fragment_page_styles_but_preserves_inline_markup_and_styles():
    owner = inline_page("Owner", "<p>正文。</p>")
    fragment = inline_page(
        "Inline",
        "<style>p { color: red; } h2 { display: none; }</style><p style=\"font-weight: bold\"><em>内联正文。</em></p>",
    )

    result = insert_inline_fragments(
        owner,
        fragments=((inline_spec("Inline", "append"), fragment),),
    )

    soup = soup_fragment(result.xhtml)
    section = soup.find("section", class_="inline-document-epub")
    assert section is not None
    assert section.find("style") is None
    assert "p { color: red; }" not in result.xhtml
    assert "h2 { display: none; }" not in result.xhtml
    assert section.find("p")["style"] == "font-weight: bold"
    assert section.find("em").get_text(strip=True) == "内联正文。"


def test_appends_inline_documents_in_configured_order():
    owner = inline_page("Owner", "<p>正文。</p>")
    first = inline_page("Offset One", "<h2>第一份</h2><p>一。</p>")
    second = inline_page("Offset Two", "<p>二。</p>")

    result = insert_inline_fragments(
        owner,
        fragments=(
            (inline_spec("Offset One", "append"), first),
            (inline_spec("Offset Two", "append"), second),
        ),
    )

    soup = soup_fragment(result.xhtml)
    sections = soup.find_all("section", class_="inline-document-epub")
    assert [section.get_text(" ", strip=True) for section in sections] == [
        "第一份 一。",
        "Offset Two 二。",
    ]
    assert sections[0].find("h2").get_text(strip=True) == "第一份"
    assert sections[1].find("h2").get_text(strip=True) == "Offset Two"


def test_unions_inline_document_assets_and_links_without_duplicates():
    owner = inline_page(
        "Owner",
        "<p>正文。</p>",
        assets=("asset-owner",),
        internal=("internal-owner",),
        external=("external-owner",),
    )
    fragment = inline_page(
        "Inline",
        "<p>内联正文。</p>",
        assets=("asset-owner", "asset-inline"),
        internal=("internal-owner", "internal-inline"),
        external=("external-owner", "external-inline"),
    )

    result = insert_inline_fragments(
        owner,
        fragments=((inline_spec("Inline", "append"), fragment),),
    )

    assert result.asset_urls == ("asset-owner", "asset-inline")
    assert result.internal_links == ("internal-owner", "internal-inline")
    assert result.external_links == ("external-owner", "external-inline")
