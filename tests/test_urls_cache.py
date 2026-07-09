import json
from pathlib import Path

from scp_epub.cache import CacheStore
from scp_epub.urls import normalize_url, safe_filename, slug_from_url


def test_normalize_url_handles_relative_and_fragments():
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "/scp-002#x") == "https://scp-wiki-cn.wikidot.com/scp-002#x"
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "http://example.test/a") == "http://example.test/a"


def test_slug_from_url_keeps_old_namespace():
    assert slug_from_url("https://scp-wiki-cn.wikidot.com/old:kalinins-proposal") == "old:kalinins-proposal"


def test_safe_filename_removes_windows_reserved_characters():
    assert safe_filename("old:kalinins-proposal") == "old_kalinins-proposal"


def test_cache_store_writes_page_and_metadata(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    page_path, meta_path = cache.write_page("scp-002", "https://example.test/scp-002", "<html></html>", 200, "text/html")

    assert page_path.read_text(encoding="utf-8") == "<html></html>"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["url"] == "https://example.test/scp-002"
    assert metadata["status_code"] == 200
    assert len(metadata["sha256"]) == 64
