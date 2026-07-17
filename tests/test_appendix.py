from bs4 import BeautifulSoup

from scp_epub.appendix import (
    appendix_group_html,
    extract_facility_children,
    extract_tab_children,
)
from scp_epub.models import PageRef


BASE_URL = "https://scp-wiki-cn.wikidot.com"


def page_ref(slug: str, *, title: str | None = None, level: int = 2) -> PageRef:
    return PageRef(
        title=title or slug,
        url=f"{BASE_URL}/{slug}",
        slug=slug,
        level=level,
        role="appendix-section",
        parent_slug="appendix",
    )


def test_extract_facility_children_selects_labelled_same_site_links_in_source_order():
    parent = page_ref("secure-facilities-locations", title="基金会设施")
    html = """
    <div id="page-content">
      <a href="/site-19">安保设施档案：Site-19</a>
      <a href="https://scp-wiki-cn.wikidot.com/site-06#details">安保设施档案：Site-06</a>
      <a href="/site-19#duplicate">安保设施档案：重复的 Site-19</a>
      <a href="/site-77"><span>安保设施档案：</span>Site-77</a>
      <a href="/other">设施档案：不匹配前缀</a>
      <a href="https://example.test/site-99">安保设施档案：站外设施</a>
      <a href="mailto:test@example.test">安保设施档案：邮件</a>
    </div>
    """

    children = extract_facility_children(parent, html, BASE_URL)

    assert [(entry.title, entry.url, entry.slug) for entry in children] == [
        ("安保设施档案：Site-19", f"{BASE_URL}/site-19", "site-19"),
        ("安保设施档案：Site-06", f"{BASE_URL}/site-06", "site-06"),
        ("安保设施档案：Site-77", f"{BASE_URL}/site-77", "site-77"),
    ]
    assert [(entry.level, entry.parent_slug, entry.role) for entry in children] == [
        (3, parent.slug, "appendix-facility"),
        (3, parent.slug, "appendix-facility"),
        (3, parent.slug, "appendix-facility"),
    ]


def test_extract_facility_children_deduplicates_host_case_and_query_variants():
    parent = page_ref("secure-facilities-locations", title="基金会设施")
    html = """
    <div id="page-content">
      <a href="https://SCP-WIKI-CN.WIKIDOT.COM/Site-19?source=directory">安保设施档案：Site-19</a>
      <a href="/site-19?view=full">安保设施档案：重复的 Site-19</a>
    </div>
    """

    children = extract_facility_children(parent, html, BASE_URL)

    assert [(entry.title, entry.url, entry.slug) for entry in children] == [
        ("安保设施档案：Site-19", f"{BASE_URL}/site-19", "site-19"),
    ]


def test_extract_facility_children_accepts_the_same_https_authority_with_default_port():
    parent = page_ref("secure-facilities-locations", title="基金会设施")
    html = """
    <div id="page-content">
      <a href="https://scp-wiki-cn.wikidot.com:443/site-19">安保设施档案：Site-19</a>
      <a href="https://example.test:443/site-99">安保设施档案：站外设施</a>
    </div>
    """

    children = extract_facility_children(parent, html, BASE_URL)

    assert [(entry.title, entry.url, entry.slug) for entry in children] == [
        ("安保设施档案：Site-19", f"{BASE_URL}/site-19", "site-19"),
    ]


def test_extract_tab_children_uses_only_direct_tabviews_and_panels():
    parent = page_ref("personnel-and-character-dossier", title="人事档案")
    html = """
    <div id="page-content">
      <div class="yui-navset" id="direct-tabs">
        <ul class="yui-nav">
          <li><a href="#first"><em> 人事档案 </em></a></li>
          <li><a href="#second"><em>研究人员</em></a></li>
        </ul>
        <div class="yui-content">
          <div id="first"><p>第一个标签页</p><a href="/ignored-link">不要跟随</a></div>
          <div id="second"><p>第二个标签页</p></div>
          <span>不是面板</span>
        </div>
      </div>
      <section>
        <div class="yui-navset">
          <ul class="yui-nav"><li>嵌套标签</li></ul>
          <div class="yui-content"><div>嵌套内容</div></div>
        </div>
      </section>
    </div>
    """

    children = extract_tab_children(parent, html)

    assert [(entry.title, entry.slug, entry.url, entry.tab_title) for entry in children] == [
        ("人事档案", "personnel-and-character-dossier--tab-1", parent.url, "人事档案"),
        ("研究人员", "personnel-and-character-dossier--tab-2", parent.url, "研究人员"),
    ]
    assert [(entry.level, entry.parent_slug, entry.role) for entry in children] == [
        (3, parent.slug, "appendix-tab"),
        (3, parent.slug, "appendix-tab"),
    ]


def test_extract_tab_children_rejects_a_tabview_without_direct_navigation():
    parent = page_ref("personnel-and-character-dossier", title="人事档案")
    html = """
    <div id="page-content">
      <div class="yui-navset">
        <div class="yui-content"><div>孤立面板内容</div></div>
      </div>
    </div>
    """

    assert extract_tab_children(parent, html) == []


def test_extract_tab_children_uses_a_stable_fallback_title_when_label_is_missing():
    parent = page_ref("o5-command-dossier", title="O5指挥部档案")
    html = """
    <div id="page-content">
      <div class="yui-navset">
        <ul class="yui-nav"><li><a href="#first">O5成员</a></li></ul>
        <div class="yui-content"><div>成员内容</div><div>未标记内容</div></div>
      </div>
    </div>
    """

    children = extract_tab_children(parent, html)

    assert [(entry.title, entry.slug, entry.tab_title) for entry in children] == [
        ("O5成员", "o5-command-dossier--tab-1", "O5成员"),
        ("标签 2", "o5-command-dossier--tab-2", "标签 2"),
    ]


def test_appendix_group_html_is_a_minimal_non_content_xhtml_page():
    entry = PageRef(
        title="附录",
        url=f"{BASE_URL}/appendix",
        slug="appendix",
        level=1,
        role="appendix-group",
    )

    html = appendix_group_html(entry)
    soup = BeautifulSoup(html, "xml")

    assert soup.html is not None
    assert soup.html.get("xmlns") == "http://www.w3.org/1999/xhtml"
    assert soup.title is not None and soup.title.get_text(strip=True) == "附录"
    assert soup.body is not None
    assert soup.body.get_text(" ", strip=True) == "附录"
    assert soup.body.find("h1") is not None
    assert soup.body.find("p") is None
