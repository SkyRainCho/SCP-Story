from pathlib import Path

import pytest

from scp_epub.models import PageFallback
from scp_epub.page_fallbacks import (
    load_fallback_fetch_result,
    snapshot_layout_signature,
)


SOURCE_HTML = """
<html><head><style>
.badge::before { content: "Level"; color: red; }
</style></head><body>
<main id="page-content"><section class="panel"><h1 title="Source title">Heading</h1>
<img src="https://example.test/image.png" alt="Source image" aria-label="Source label"></section></main>
</body></html>
"""

TRANSLATED_HTML = """
<html><head><style>
.badge::before { content: "等级"; color: red; }
</style></head><body>
<main id="page-content"><section class="panel"><h1 title="翻译标题">标题</h1>
<img src="https://example.test/image.png" alt="翻译图像" aria-label="翻译标签"></section></main>
</body></html>
"""


def _fallback(path: Path, signature: str) -> PageFallback:
    return PageFallback(
        source_url="https://example.test/scp-002",
        source_language="en",
        translated_title="SCP-002",
        snapshot_path=path,
        layout_signature=signature,
    )


def test_snapshot_layout_signature_ignores_translated_text_and_css_content():
    assert snapshot_layout_signature(SOURCE_HTML) == snapshot_layout_signature(TRANSLATED_HTML)


def test_snapshot_layout_signature_changes_when_page_content_tag_changes():
    changed = SOURCE_HTML.replace('<section class="panel">', '<article class="panel">').replace(
        "</section>", "</article>"
    )

    assert snapshot_layout_signature(SOURCE_HTML) != snapshot_layout_signature(changed)


def test_snapshot_layout_signature_preserves_custom_content_property_values():
    red = '<style>.badge { --content: "red"; }</style><div id="page-content"></div>'
    blue = '<style>.badge { --content: "blue"; }</style><div id="page-content"></div>'

    assert snapshot_layout_signature(red) != snapshot_layout_signature(blue)


def test_snapshot_layout_signature_ignores_html_comments():
    with_comment = SOURCE_HTML.replace("<h1", "<!-- translator note --><h1")

    assert snapshot_layout_signature(SOURCE_HTML) == snapshot_layout_signature(with_comment)


@pytest.mark.parametrize(
    ("html", "message"),
    [
        ("<html><body><p>missing</p></body></html>", "must contain exactly one #page-content"),
        (
            '<div id="page-content"></div><div id="page-content"></div>',
            "must contain exactly one #page-content",
        ),
        ('<div id="page-content"><script>alert(1)</script></div>', "must not contain script elements"),
    ],
)
def test_load_fallback_fetch_result_rejects_invalid_snapshots(
    tmp_path: Path, html: str, message: str
):
    path = tmp_path / "snapshot.html"
    path.write_text(html, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_fallback_fetch_result("scp-002", _fallback(path, "unused"))


def test_load_fallback_fetch_result_returns_valid_snapshot_metadata(tmp_path: Path):
    path = tmp_path / "snapshot.html"
    path.write_text(SOURCE_HTML, encoding="utf-8")
    fallback = _fallback(path, snapshot_layout_signature(SOURCE_HTML))

    result = load_fallback_fetch_result("scp-002", fallback)

    assert result.url == fallback.source_url
    assert result.path == fallback.snapshot_path
    assert result.metadata_path == fallback.snapshot_path
    assert result.from_cache is True
    assert result.status_code == 200
    assert result.content_type == "text/html; charset=utf-8"


def test_load_fallback_fetch_result_rejects_unreadable_snapshot(tmp_path: Path):
    path = tmp_path / "snapshot.html"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(ValueError, match="fallback snapshot for scp-002 is unreadable"):
        load_fallback_fetch_result("scp-002", _fallback(path, "unused"))


def test_load_fallback_fetch_result_rejects_layout_signature_mismatch(tmp_path: Path):
    path = tmp_path / "snapshot.html"
    path.write_text(SOURCE_HTML, encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="fallback snapshot layout signature mismatch for scp-002: expected expected, got ",
    ):
        load_fallback_fetch_result("scp-002", _fallback(path, "expected"))
