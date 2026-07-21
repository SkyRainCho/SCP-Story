from scp_epub.classification import classification_component_inventory
from scp_epub.models import PageRef, ProcessedPage


def page(slug: str, title: str, xhtml: str) -> ProcessedPage:
    return ProcessedPage(
        entry=PageRef(title, f"https://example.test/{slug}", slug, 1, "scp"),
        xhtml=xhtml,
        asset_urls=(),
        internal_links=(),
        external_links=(),
    )


def test_inventory_aggregates_components_by_document_and_family():
    pages = [
        page(
            "scp-713",
            "SCP-713 - 哪里不会点哪里",
            '<div data-epub-classification-family="acs" '
            'data-epub-classification-status="normalized"></div>'
            '<div data-epub-classification-family="acs" '
            'data-epub-classification-status="normalized"></div>',
        ),
        page(
            "scp-1297",
            "SCP-1297 - 逆时指甲罐",
            '<div data-epub-classification-family="woed" '
            'data-epub-classification-status="unrecognized"></div>',
        ),
    ]

    records = classification_component_inventory(pages)

    assert [record.as_dict() for record in records] == [
        {
            "slug": "scp-713",
            "title": "SCP-713 - 哪里不会点哪里",
            "family": "acs",
            "component_count": 2,
            "status": "normalized",
        },
        {
            "slug": "scp-1297",
            "title": "SCP-1297 - 逆时指甲罐",
            "family": "woed",
            "component_count": 1,
            "status": "unrecognized",
        },
    ]


def test_inventory_uses_unrecognized_when_any_component_is_unrecognized():
    records = classification_component_inventory(
        [
            page(
                "scp-713",
                "SCP-713",
                '<div data-epub-classification-family="acs" '
                'data-epub-classification-status="normalized"></div>'
                '<div data-epub-classification-family="acs" '
                'data-epub-classification-status="unrecognized"></div>',
            )
        ]
    )

    assert records[0].component_count == 2
    assert records[0].status == "unrecognized"
