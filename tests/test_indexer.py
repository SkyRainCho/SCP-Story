from pathlib import Path

from bs4 import BeautifulSoup

from scp_epub.indexer import _is_newpage_anchor, parse_series_index, parse_tales_index


FIXTURE = Path("tests/fixtures/index_sample.html")
BASE_URL = "https://scp-wiki-cn.wikidot.com"


def test_parse_tales_index_keeps_target_sections_only_in_wrapped_content_panel():
    html = FIXTURE.read_text(encoding="utf-8")

    entries = parse_tales_index(html, BASE_URL, start=1, end=99)

    slugs = [entry.slug for entry in entries]
    assert slugs == [
        "scp-001",
        "spc-001",
        "scp-002",
        "story-002",
        "jonathan-ball-proposal",
        "pila",
        "scp-099",
        "supplement-099",
    ]
    assert "scp-100" not in slugs
    assert "not-content" not in slugs
    assert "missing-parent" not in slugs
    assert "orphan-story" not in slugs
    assert {entry.source for entry in entries} == {"tales-index"}
    assert [entry.order for entry in entries] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert entries[0].url == "https://scp-wiki-cn.wikidot.com/scp-001"


def test_parse_tales_index_preserves_nested_levels_and_parents():
    html = FIXTURE.read_text(encoding="utf-8")

    entries = parse_tales_index(html, BASE_URL, start=1, end=99)
    by_slug = {entry.slug: entry for entry in entries}

    assert by_slug["scp-002"].level == 1
    assert by_slug["scp-002"].title == "SCP-002 - Living Room"
    assert by_slug["story-002"].level == 2
    assert by_slug["story-002"].parent_slug == "scp-002"
    assert by_slug["jonathan-ball-proposal"].title == "代号：Jonathan Ball - 资料卷"
    assert by_slug["pila"].parent_slug == "jonathan-ball-proposal"
    assert by_slug["scp-099"].level == 1
    assert by_slug["supplement-099"].level == 2
    assert by_slug["supplement-099"].parent_slug == "scp-099"


def test_parse_tales_index_partial_range_excludes_001_proposal_section():
    html = FIXTURE.read_text(encoding="utf-8")

    entries = parse_tales_index(html, BASE_URL, start=2, end=99)

    assert [entry.slug for entry in entries] == [
        "scp-002",
        "story-002",
        "jonathan-ball-proposal",
        "pila",
        "scp-099",
        "supplement-099",
    ]


def test_parse_tales_index_skips_children_of_newpage_parent_entries():
    html = FIXTURE.read_text(encoding="utf-8")

    entries = parse_tales_index(html, BASE_URL, start=2, end=99)

    assert "missing-parent" not in [entry.slug for entry in entries]
    assert "orphan-story" not in [entry.slug for entry in entries]


def test_parse_tales_index_matches_repeated_scp_prefix_range_heading():
    html = """
<div id="page-content">
  <div class="content-panel">
    <h1>SCP-002到SCP-099</h1>
    <ul><li><a href="/scp-002">SCP-002</a></li></ul>
  </div>
</div>
"""

    entries = parse_tales_index(html, BASE_URL, start=2, end=99)

    assert [entry.slug for entry in entries] == ["scp-002"]


def test_parse_tales_index_matches_four_digit_range_heading():
    html = """
<div id="page-content">
  <div class="content-panel">
    <h1>SCP-1000到SCP-1099</h1>
    <ul>
      <li><a href="/scp-1000">SCP-1000</a>
        <ul><li><a href="/story-1000">Story 1000</a></li></ul>
      </li>
    </ul>
    <h1>SCP-1100到SCP-1199</h1>
    <ul><li><a href="/scp-1100">SCP-1100</a></li></ul>
  </div>
</div>
"""

    entries = parse_tales_index(html, BASE_URL, start=1000, end=1099)

    assert [entry.slug for entry in entries] == ["scp-1000", "story-1000"]
    assert entries[1].parent_slug == "scp-1000"


def test_parse_tales_index_includes_lower_heading_content_until_same_level_boundary():
    html = """
<div id="page-content">
  <div class="content-panel">
    <h1>002到099</h1>
    <ul><li><a href="/scp-002">SCP-002</a></li></ul>
    <h2>相关故事</h2>
    <ul><li><a href="/story-lower">Lower Story</a></li></ul>
    <h1>100到199</h1>
    <ul><li><a href="/scp-100">SCP-100</a></li></ul>
  </div>
</div>
"""

    entries = parse_tales_index(html, BASE_URL, start=2, end=99)

    assert [entry.slug for entry in entries] == ["scp-002", "story-lower"]


def test_parse_tales_index_partial_range_for_001_only_excludes_later_range():
    html = FIXTURE.read_text(encoding="utf-8")

    entries = parse_tales_index(html, BASE_URL, start=1, end=1)

    assert [entry.slug for entry in entries] == ["scp-001", "spc-001"]


def test_newpage_detection_splits_string_class_attributes():
    soup = BeautifulSoup('<a href="/missing">Missing</a>', "html.parser")
    anchor = soup.find("a")
    assert anchor is not None
    anchor["class"] = "external-link newpage"

    assert _is_newpage_anchor(anchor)


def test_parse_series_index_extracts_scp_items_in_range_with_titles():
    html = Path("tests/fixtures/series_index_sample.html").read_text(encoding="utf-8")

    entries = parse_series_index(html, BASE_URL, start=18, end=21)

    assert [entry.slug for entry in entries] == ["scp-018", "scp-019", "scp-020", "scp-021"]
    assert [entry.title for entry in entries] == [
        "SCP-018 - 弹力球",
        "SCP-019 - 怪物罐",
        "SCP-020 - 隐形霉菌",
        "SCP-021 - 寄生纹身",
    ]
    assert {entry.level for entry in entries} == {1}
    assert {entry.role for entry in entries} == {"scp"}
    assert {entry.source for entry in entries} == {"series-index"}
    assert [entry.order for entry in entries] == [1, 2, 3, 4]


def test_parse_series_index_extracts_four_digit_scp_items():
    html = """
<div id="page-content">
  <ul>
    <li><a href="/scp-0999">SCP-999</a> - Outside</li>
    <li><a href="/scp-1000">SCP-1000</a> - Bigfoot</li>
    <li><a href="/scp-1001">SCP-1001</a> - Ya-Te-Veo</li>
    <li><a href="/scp-1100">SCP-1100</a> - Outside</li>
  </ul>
</div>
"""

    entries = parse_series_index(html, BASE_URL, start=1000, end=1099)

    assert [entry.slug for entry in entries] == ["scp-1000", "scp-1001"]
    assert [entry.title for entry in entries] == [
        "SCP-1000 - Bigfoot",
        "SCP-1001 - Ya-Te-Veo",
    ]
