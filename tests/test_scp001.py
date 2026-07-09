from pathlib import Path

import pytest

from scp_epub.indexer import parse_scp001_proposals


FIXTURE = Path("tests/fixtures/scp001_sample.html")
BASE_URL = "https://scp-wiki-cn.wikidot.com"


def test_parse_scp001_proposals_preserves_order_and_metadata():
    html = FIXTURE.read_text(encoding="utf-8")

    entries = parse_scp001_proposals(html, BASE_URL)

    assert [entry.slug for entry in entries] == [
        "dr-clef-s-proposal",
        "djkaktus-s-proposal",
        "tuftos-proposal",
        "old:kalinins-proposal",
        "alt:nico-proposal",
        "nameless-proposal",
    ]
    assert [entry.order for entry in entries] == [1, 2, 3, 4, 5, 6]
    assert {entry.source for entry in entries} == {"scp-001"}
    assert {entry.role for entry in entries} == {"proposal"}
    assert {entry.level for entry in entries} == {2}
    assert {entry.parent_slug for entry in entries} == {"scp-001"}

    by_slug = {entry.slug: entry for entry in entries}
    assert by_slug["old:kalinins-proposal"].url == (
        "https://scp-wiki-cn.wikidot.com/old:kalinins-proposal"
    )
    assert by_slug["nameless-proposal"].title == "nameless-proposal"


def test_parse_scp001_proposals_requires_page_content():
    with pytest.raises(ValueError, match="#page-content"):
        parse_scp001_proposals("<html><body></body></html>", BASE_URL)
