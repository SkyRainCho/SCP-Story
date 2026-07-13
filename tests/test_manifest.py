import json

import pytest

from scp_epub.manifest import merge_manifest, supplement_missing_scp_entries
from scp_epub.models import PageRef


def page_ref(
    slug: str,
    *,
    title: str | None = None,
    level: int = 1,
    role: str = "scp",
    parent_slug: str | None = None,
    source: str = "tales-index",
    order: int = 0,
    children: tuple[PageRef, ...] = (),
) -> PageRef:
    return PageRef(
        title=title or slug,
        url=f"https://scp-wiki-cn.wikidot.com/{slug}",
        slug=slug,
        level=level,
        role=role,
        parent_slug=parent_slug,
        source=source,
        order=order,
        children=children,
    )


def test_merge_inserts_proposals_after_scp001_and_renumbers_order():
    index_entries = [
        page_ref("scp-001", order=10),
        page_ref("scp-002", order=20),
        page_ref("story-002", level=2, role="related", parent_slug="scp-002", order=30),
    ]
    proposals = [
        page_ref(
            "alpha-proposal",
            title="Alpha Proposal",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=1,
        ),
        page_ref(
            "beta-proposal",
            title="Beta Proposal",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=2,
        ),
    ]

    manifest = merge_manifest(index_entries, proposals)

    assert [entry.slug for entry in manifest] == [
        "scp-001",
        "alpha-proposal",
        "beta-proposal",
        "scp-002",
        "story-002",
    ]
    assert [entry.order for entry in manifest] == [1, 2, 3, 4, 5]
    assert manifest[4].level == 2
    assert manifest[4].parent_slug == "scp-002"


def test_merge_deduplicates_slugs_with_index_entries_winning():
    index_entries = [
        page_ref("scp-001", order=1),
        page_ref(
            "alpha-proposal",
            title="Indexed Alpha",
            level=2,
            role="related",
            parent_slug="scp-001",
            source="tales-index",
            order=2,
        ),
        page_ref("scp-002", title="SCP-002", order=3),
        page_ref("scp-002", title="Duplicate SCP-002", order=4),
    ]
    proposals = [
        page_ref(
            "alpha-proposal",
            title="Proposal Alpha",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=1,
        ),
        page_ref(
            "beta-proposal",
            title="Beta Proposal",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=2,
        ),
    ]

    manifest = merge_manifest(index_entries, proposals)

    assert [entry.slug for entry in manifest] == [
        "scp-001",
        "alpha-proposal",
        "beta-proposal",
        "scp-002",
    ]
    assert [entry.order for entry in manifest] == [1, 2, 3, 4]

    by_slug = {entry.slug: entry for entry in manifest}
    assert by_slug["alpha-proposal"].title == "Indexed Alpha"
    assert by_slug["alpha-proposal"].source == "tales-index"
    assert by_slug["scp-002"].title == "SCP-002"


def test_merge_reorders_scp001_children_to_match_hub_proposal_order():
    index_entries = [
        page_ref("scp-001", title="SCP-001", order=1),
        page_ref(
            "beta-proposal",
            title="Indexed Beta With Tales",
            level=1,
            role="related",
            parent_slug=None,
            source="tales-index",
            order=2,
        ),
        page_ref(
            "alpha-proposal",
            title="Indexed Alpha With Tales",
            level=1,
            role="related",
            parent_slug=None,
            source="tales-index",
            order=3,
        ),
        page_ref("scp-002", title="SCP-002", order=4),
    ]
    proposals = [
        page_ref(
            "alpha-proposal",
            title="Hub Alpha",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=1,
        ),
        page_ref(
            "missing-proposal",
            title="Hub Missing",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=2,
        ),
        page_ref(
            "beta-proposal",
            title="Hub Beta",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=3,
        ),
    ]

    manifest = merge_manifest(index_entries, proposals)

    assert [entry.slug for entry in manifest] == [
        "scp-001",
        "alpha-proposal",
        "missing-proposal",
        "beta-proposal",
        "scp-002",
    ]
    by_slug = {entry.slug: entry for entry in manifest}
    assert by_slug["alpha-proposal"].title == "Indexed Alpha With Tales"
    assert by_slug["beta-proposal"].title == "Indexed Beta With Tales"
    assert by_slug["missing-proposal"].title == "Hub Missing"
    assert [entry.level for entry in manifest[1:4]] == [1, 1, 1]
    assert [entry.parent_slug for entry in manifest[1:4]] == [
        None,
        None,
        None,
    ]


def test_merge_reorders_scp001_proposal_groups_as_top_level_entries():
    index_entries = [
        page_ref("scp-001", title="SCP-001", order=1),
        page_ref("spc-001", title="SPC-001", level=2, parent_slug="scp-001", order=2),
        page_ref(
            "beta-proposal",
            title="Indexed Beta With Tales",
            level=1,
            role="related",
            parent_slug=None,
            source="tales-index",
            order=3,
        ),
        page_ref(
            "beta-story",
            title="Beta Story",
            level=2,
            role="related",
            parent_slug="beta-proposal",
            source="tales-index",
            order=4,
        ),
        page_ref(
            "alpha-proposal",
            title="Indexed Alpha With Tales",
            level=1,
            role="related",
            parent_slug=None,
            source="tales-index",
            order=5,
        ),
        page_ref(
            "alpha-story",
            title="Alpha Story",
            level=2,
            role="related",
            parent_slug="alpha-proposal",
            source="tales-index",
            order=6,
        ),
        page_ref("scp-002", title="SCP-002", order=7),
    ]
    proposals = [
        page_ref(
            "alpha-proposal",
            title="Hub Alpha",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=1,
        ),
        page_ref(
            "missing-proposal",
            title="Hub Missing",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=2,
        ),
        page_ref(
            "beta-proposal",
            title="Hub Beta",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=3,
        ),
    ]

    manifest = merge_manifest(index_entries, proposals)

    assert [entry.slug for entry in manifest] == [
        "scp-001",
        "spc-001",
        "alpha-proposal",
        "alpha-story",
        "missing-proposal",
        "beta-proposal",
        "beta-story",
        "scp-002",
    ]
    by_slug = {entry.slug: entry for entry in manifest}
    assert by_slug["alpha-proposal"].title == "Indexed Alpha With Tales"
    assert by_slug["beta-proposal"].title == "Indexed Beta With Tales"
    assert by_slug["missing-proposal"].title == "Hub Missing"
    assert [by_slug[slug].level for slug in ["alpha-proposal", "missing-proposal", "beta-proposal"]] == [1, 1, 1]
    assert [by_slug[slug].parent_slug for slug in ["alpha-proposal", "missing-proposal", "beta-proposal"]] == [None, None, None]
    assert by_slug["alpha-story"].parent_slug == "alpha-proposal"
    assert by_slug["beta-story"].parent_slug == "beta-proposal"


def test_merge_prepends_proposals_when_scp001_is_missing():
    index_entries = [
        page_ref("scp-002", order=1),
        page_ref("story-002", level=2, role="related", parent_slug="scp-002", order=2),
    ]
    proposals = [
        page_ref(
            "alpha-proposal",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=1,
        ),
        page_ref(
            "beta-proposal",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=2,
        ),
    ]

    manifest = merge_manifest(index_entries, proposals)

    assert [entry.slug for entry in manifest] == [
        "alpha-proposal",
        "beta-proposal",
        "scp-002",
        "story-002",
    ]
    assert [entry.order for entry in manifest] == [1, 2, 3, 4]


def test_merge_deduplicates_repeated_proposals_with_first_occurrence_winning():
    index_entries = [
        page_ref("scp-001", order=1),
        page_ref("scp-002", order=2),
    ]
    proposals = [
        page_ref(
            "alpha-proposal",
            title="First Alpha",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=1,
        ),
        page_ref(
            "alpha-proposal",
            title="Duplicate Alpha",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=2,
        ),
        page_ref(
            "beta-proposal",
            title="Beta Proposal",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=3,
        ),
    ]

    manifest = merge_manifest(index_entries, proposals)

    assert [entry.slug for entry in manifest] == [
        "scp-001",
        "alpha-proposal",
        "beta-proposal",
        "scp-002",
    ]
    assert [entry.order for entry in manifest] == [1, 2, 3, 4]

    by_slug = {entry.slug: entry for entry in manifest}
    assert by_slug["alpha-proposal"].title == "First Alpha"


def test_supplement_missing_scp_entries_inserts_numbered_items_without_flattening_children():
    tales_entries = [
        page_ref("scp-018", title="SCP-018 - 弹力球", order=1),
        page_ref(
            "story-018",
            title="故事 018",
            level=2,
            role="related",
            parent_slug="scp-018",
            order=2,
        ),
        page_ref("scp-021", title="SCP-021 - 寄生纹身", order=3),
        page_ref(
            "story-021",
            title="故事 021",
            level=2,
            role="related",
            parent_slug="scp-021",
            order=4,
        ),
    ]
    series_entries = [
        page_ref("scp-018", title="SCP-018 - 弹力球", source="series-index"),
        page_ref("scp-019", title="SCP-019 - 怪物罐", source="series-index"),
        page_ref("scp-020", title="SCP-020 - 隐形霉菌", source="series-index"),
        page_ref("scp-021", title="SCP-021 - 寄生纹身", source="series-index"),
    ]

    manifest = supplement_missing_scp_entries(tales_entries, series_entries)

    assert [entry.slug for entry in manifest] == [
        "scp-018",
        "story-018",
        "scp-019",
        "scp-020",
        "scp-021",
        "story-021",
    ]
    assert [entry.order for entry in manifest] == [1, 2, 3, 4, 5, 6]
    assert manifest[2].title == "SCP-019 - 怪物罐"
    assert manifest[2].source == "series-index"
    assert manifest[3].level == 1
    assert manifest[5].parent_slug == "scp-021"


def test_write_and_read_manifest_round_trips_utf8_json(tmp_path):
    entries = [
        page_ref("scp-001", title="破碎之神", order=1),
        page_ref(
            "scp-001-o5",
            title="代号：O5",
            level=2,
            role="proposal",
            parent_slug="scp-001",
            source="scp-001",
            order=2,
        ),
    ]
    path = tmp_path / "manifest.json"

    from scp_epub.manifest import read_manifest, write_manifest

    written_path = write_manifest(entries, path)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    round_tripped = read_manifest(path)

    assert written_path == path
    assert text.startswith("[\n  {\n")
    assert "破碎之神" in text
    assert "\\u7834" not in text
    assert list(data[0]) == [
        "title",
        "url",
        "slug",
        "level",
        "role",
        "parent_slug",
        "source",
        "order",
    ]
    assert [entry["slug"] for entry in data] == ["scp-001", "scp-001-o5"]
    assert round_tripped == entries


def test_write_manifest_rejects_non_flat_entries(tmp_path):
    child = page_ref("story-001", level=2, role="related", parent_slug="scp-001")
    entries = [
        page_ref("scp-001", title="SCP-001", order=1, children=(child,)),
    ]

    from scp_epub.manifest import write_manifest

    with pytest.raises(ValueError, match="manifest entries must be flat"):
        write_manifest(entries, tmp_path / "manifest.json")


def test_read_manifest_rejects_non_flat_json(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            [
                {
                    "title": "SCP-001",
                    "url": "https://scp-wiki-cn.wikidot.com/scp-001",
                    "slug": "scp-001",
                    "level": 1,
                    "role": "scp",
                    "parent_slug": None,
                    "source": "tales-index",
                    "order": 1,
                    "children": [
                        {
                            "title": "Story 001",
                            "url": "https://scp-wiki-cn.wikidot.com/story-001",
                            "slug": "story-001",
                        }
                    ],
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    from scp_epub.manifest import read_manifest

    with pytest.raises(ValueError, match="manifest entries must be flat"):
        read_manifest(path)
