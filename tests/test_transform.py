from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from scp_epub.models import PageRef
from scp_epub.transform import transform_page


FIXTURE = Path(__file__).parent / "fixtures" / "page_sample.html"
BASE_URL = "https://scp-wiki-cn.wikidot.com/scp-999"


def page_ref() -> PageRef:
    return PageRef(
        title="SCP-999",
        url=BASE_URL,
        slug="scp-999",
        level=1,
        role="scp",
    )


def transformed(manifest_slugs: set[str] | None = None):
    return transform_page(page_ref(), FIXTURE.read_text(encoding="utf-8"), BASE_URL, manifest_slugs)


def soup_fragment(xhtml: str) -> BeautifulSoup:
    return BeautifulSoup(f"<root>{xhtml}</root>", "xml")


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
    assert "div.console::before" in style_text
    assert ".unused-site-chrome" not in style_text
    assert soup.find(class_="blankframe") is not None


def test_missing_page_content_raises_value_error():
    with pytest.raises(ValueError, match="#page-content"):
        transform_page(page_ref(), "<html><body><p>No content</p></body></html>", BASE_URL)
