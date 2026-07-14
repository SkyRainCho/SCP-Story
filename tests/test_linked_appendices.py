from pathlib import Path

from scp_epub.cache import CacheStore
from scp_epub.linked_appendices import scan_linked_appendices, write_linked_appendix_report
from scp_epub.models import PageRef


def test_scan_detects_same_scp_test_appendix(tmp_path):
    cache = CacheStore(tmp_path / "raw")
    cache.write_page(
        "scp-093",
        "https://scp-wiki-cn.wikidot.com/scp-093",
        """
        <html><body><div id="page-content">
          <p><a href="/scp-093-blue-test">SCP-093“蓝色”测试</a></p>
          <p><a href="/scp-094">SCP-094</a></p>
          <p><a href="/licensing-guide">授权指南</a></p>
        </div></body></html>
        """,
        200,
        "text/html",
    )
    manifest = [
        PageRef(
            title="SCP-093 - 红海物件",
            url="https://scp-wiki-cn.wikidot.com/scp-093",
            slug="scp-093",
            level=1,
            role="scp",
            order=1,
        ),
        PageRef(
            title="SCP-094",
            url="https://scp-wiki-cn.wikidot.com/scp-094",
            slug="scp-094",
            level=1,
            role="scp",
            order=2,
        ),
    ]

    documents = scan_linked_appendices(manifest, cache, "https://scp-wiki-cn.wikidot.com")

    assert [(doc.entry.slug, [candidate.slug for candidate in doc.candidates]) for doc in documents] == [
        ("scp-093", ["scp-093-blue-test"])
    ]


def test_scan_detects_linked_part_sequence_without_cross_reference_noise(tmp_path):
    cache = CacheStore(tmp_path / "raw")
    cache.write_page(
        "conspiracy",
        "https://scp-wiki-cn.wikidot.com/conspiracy",
        """
        <html><body><div id="page-content">
          <p><a href="/conspiracy-part-i">Part I</a></p>
          <p><a href="/global-occult-coalition-casefiles">普通推荐阅读</a></p>
          <p><a href="/user:example">作者页</a></p>
        </div></body></html>
        """,
        200,
        "text/html",
    )
    manifest = [
        PageRef(
            title="阴谋",
            url="https://scp-wiki-cn.wikidot.com/conspiracy",
            slug="conspiracy",
            level=1,
            role="related",
            order=1,
        )
    ]

    documents = scan_linked_appendices(manifest, cache, "https://scp-wiki-cn.wikidot.com")

    assert [candidate.slug for candidate in documents[0].candidates] == ["conspiracy-part-i"]


def test_scan_detects_chinese_linked_part_sequence(tmp_path):
    cache = CacheStore(tmp_path / "raw")
    cache.write_page(
        "the-drooling-path",
        "https://scp-wiki-cn.wikidot.com/the-drooling-path",
        """
        <html><body><div id="page-content">
          <p><a href="/the-drooling-path-part-1">第一部分</a></p>
        </div></body></html>
        """,
        200,
        "text/html",
    )
    manifest = [
        PageRef(
            title="垂涎之路",
            url="https://scp-wiki-cn.wikidot.com/the-drooling-path",
            slug="the-drooling-path",
            level=1,
            role="related",
            order=1,
        )
    ]

    documents = scan_linked_appendices(manifest, cache, "https://scp-wiki-cn.wikidot.com")

    assert [candidate.slug for candidate in documents[0].candidates] == [
        "the-drooling-path-part-1"
    ]


def test_scan_detects_proposal_path_links_conservatively(tmp_path):
    cache = CacheStore(tmp_path / "raw")
    cache.write_page(
        "yoshihides-proposal",
        "https://scp-wiki-cn.wikidot.com/yoshihides-proposal",
        """
        <html><body><div id="page-content">
          <p><a href="/the-trail-for-beasts">野兽之径</a></p>
          <p><a href="/the-path-of-swords">剑刃之路</a></p>
          <p><a href="/random-roadside-story">普通道路故事</a></p>
        </div></body></html>
        """,
        200,
        "text/html",
    )
    manifest = [
        PageRef(
            title="代号：良秀",
            url="https://scp-wiki-cn.wikidot.com/yoshihides-proposal",
            slug="yoshihides-proposal",
            level=1,
            role="proposal",
            order=1,
        )
    ]

    documents = scan_linked_appendices(manifest, cache, "https://scp-wiki-cn.wikidot.com")

    assert [candidate.slug for candidate in documents[0].candidates] == [
        "the-trail-for-beasts",
        "the-path-of-swords",
    ]


def test_write_linked_appendix_report(tmp_path):
    cache = CacheStore(tmp_path / "raw")
    cache.write_page(
        "scp-026",
        "https://scp-wiki-cn.wikidot.com/scp-026",
        """
        <html><body><div id="page-content">
          <a href="/interview-log-026-01">采访记录026-01</a>
        </div></body></html>
        """,
        200,
        "text/html",
    )
    manifest = [
        PageRef(
            title="SCP-026 - 课后禁闭",
            url="https://scp-wiki-cn.wikidot.com/scp-026",
            slug="scp-026",
            level=1,
            role="scp",
            order=1,
        )
    ]
    documents = scan_linked_appendices(manifest, cache, "https://scp-wiki-cn.wikidot.com")

    path = write_linked_appendix_report(documents, tmp_path / "report.json")

    assert path == tmp_path / "report.json"
    assert '"source_slug": "scp-026"' in path.read_text(encoding="utf-8")
    assert '"slug": "interview-log-026-01"' in path.read_text(encoding="utf-8")
