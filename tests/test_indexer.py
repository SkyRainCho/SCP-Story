from pathlib import Path

from bs4 import BeautifulSoup

from scp_epub.indexer import _is_newpage_anchor, parse_tales_index


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
        "scp-099",
        "supplement-099",
    ]
    assert "scp-100" not in slugs
    assert "not-content" not in slugs
    assert {entry.source for entry in entries} == {"tales-index"}
    assert [entry.order for entry in entries] == [1, 2, 3, 4, 5, 6]
    assert entries[0].url == "https://scp-wiki-cn.wikidot.com/scp-001"


def test_parse_tales_index_preserves_nested_levels_and_parents():
    html = FIXTURE.read_text(encoding="utf-8")

    entries = parse_tales_index(html, BASE_URL, start=1, end=99)
    by_slug = {entry.slug: entry for entry in entries}

    assert by_slug["scp-002"].level == 1
    assert by_slug["story-002"].level == 2
    assert by_slug["story-002"].parent_slug == "scp-002"
    assert by_slug["scp-099"].level == 1
    assert by_slug["supplement-099"].level == 2
    assert by_slug["supplement-099"].parent_slug == "scp-099"


def test_parse_tales_index_partial_range_excludes_001_proposal_section():
    html = FIXTURE.read_text(encoding="utf-8")

    entries = parse_tales_index(html, BASE_URL, start=2, end=99)

    assert [entry.slug for entry in entries] == [
        "scp-002",
        "story-002",
        "scp-099",
        "supplement-099",
    ]


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
