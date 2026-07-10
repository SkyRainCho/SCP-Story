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


def test_strips_event_handlers_and_inline_styles_but_keeps_harmless_attributes():
    result = transformed({"scp-002", "old:kalinins-proposal"})
    soup = soup_fragment(result.xhtml)

    assert not soup.find_all(attrs={"onclick": True})
    assert not soup.find_all(attrs={"style": True})
    image = soup.find("img")
    paragraph = soup.find("p")
    assert image["alt"] == "Specimen photo"
    assert image["title"] == "Photo title"
    assert image["class"] == "image"
    assert paragraph["class"] == "main-text"


def test_missing_page_content_raises_value_error():
    with pytest.raises(ValueError, match="#page-content"):
        transform_page(page_ref(), "<html><body><p>No content</p></body></html>", BASE_URL)
