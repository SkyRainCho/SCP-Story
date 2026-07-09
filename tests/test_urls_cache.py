import hashlib
import json
from datetime import datetime
from pathlib import Path

from scp_epub.cache import CacheStore
from scp_epub.urls import normalize_url, safe_filename, slug_from_url


def test_normalize_url_handles_relative_and_fragments():
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "/scp-002#x") == "https://scp-wiki-cn.wikidot.com/scp-002#x"
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "http://example.test/a") == "http://example.test/a"
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "https://example.test/a") == "https://example.test/a"


def test_normalize_url_handles_wikidot_namespaced_page_links():
    normalized = normalize_url("https://scp-wiki-cn.wikidot.com", "old:kalinins-proposal")

    assert normalized == "https://scp-wiki-cn.wikidot.com/old:kalinins-proposal"
    assert slug_from_url(normalized) == "old:kalinins-proposal"
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "alt:nico-proposal") == "https://scp-wiki-cn.wikidot.com/alt:nico-proposal"


def test_normalize_url_preserves_non_fetchable_schemes():
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "mailto:test@example.test") == "mailto:test@example.test"
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "ftp://example.test/file.txt") == "ftp://example.test/file.txt"
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "javascript:void(0)") == "javascript:void(0)"
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "data:image/png;base64,abc") == "data:image/png;base64,abc"
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "tel:+123") == "tel:+123"


def test_slug_from_url_keeps_old_namespace():
    assert slug_from_url("https://scp-wiki-cn.wikidot.com/old:kalinins-proposal") == "old:kalinins-proposal"


def test_safe_filename_removes_windows_reserved_characters():
    assert safe_filename("old:kalinins-proposal") == "old_kalinins-proposal"


def test_safe_filename_avoids_windows_reserved_basenames():
    assert safe_filename("con") == "con_"
    assert safe_filename("COM1") == "COM1_"


def test_safe_filename_replaces_ascii_control_characters():
    assert safe_filename("bad\x00\x1fname") == "bad_name"


def test_cache_store_writes_page_and_metadata(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    page_path, meta_path = cache.write_page("scp-002", "https://example.test/scp-002", "<html></html>", 200, "text/html")

    assert page_path.read_text(encoding="utf-8") == "<html></html>"
    assert cache.has_page("scp-002")
    assert cache.read_page("scp-002") == "<html></html>"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["url"] == "https://example.test/scp-002"
    assert metadata["status_code"] == 200
    assert metadata["content_type"] == "text/html"
    assert metadata["sha256"] == hashlib.sha256("<html></html>".encode("utf-8")).hexdigest()
    fetched_at = datetime.fromisoformat(metadata["fetched_at"])
    assert fetched_at.tzinfo is not None
    assert fetched_at.utcoffset() is not None


def test_cache_store_asset_path_uses_parsed_url_path_for_suffix(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")

    assert cache.asset_path("https://example.test/image.png#fragment").suffix == ".png"


def test_cache_store_asset_path_rejects_unsafe_url_suffix(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")

    assert cache.asset_path("https://example.test/image.png:large").suffix == ".bin"


def test_cache_store_asset_path_content_type_parameters_map_suffix(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")

    assert cache.asset_path("https://example.test/image", "image/png; charset=binary").suffix == ".png"


def test_cache_store_asset_path_maps_epub_asset_content_types(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")

    assert cache.asset_path("https://example.test/vector", "image/svg+xml").suffix == ".svg"
    assert cache.asset_path("https://example.test/font", "font/ttf").suffix == ".ttf"
    assert cache.asset_path("https://example.test/font", "font/otf").suffix == ".otf"
    assert cache.asset_path("https://example.test/font", "application/font-woff").suffix == ".woff"
    assert cache.asset_path("https://example.test/font", "application/font-woff2").suffix == ".woff2"


def test_cache_store_writes_asset_and_metadata(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    content = b"image bytes"
    asset_path, meta_path = cache.write_asset(
        "https://example.test/image.png",
        content,
        200,
        "image/png",
    )

    assert asset_path.read_bytes() == content
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["url"] == "https://example.test/image.png"
    assert metadata["status_code"] == 200
    assert metadata["content_type"] == "image/png"
    assert metadata["sha256"] == hashlib.sha256(content).hexdigest()
