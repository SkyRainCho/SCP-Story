from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scp_epub.models import AppConfig, FetchResult, PageRef, VolumeSpec
from scp_epub.pipeline import (
    build_manifest,
    build_volume,
    fetch_manifest_pages,
)


BASE_URL = "https://scp-wiki-cn.wikidot.com"


def app_config(tmp_path: Path, *, volume_key: str = "001-099") -> AppConfig:
    volume = VolumeSpec(
        key=volume_key,
        start=1,
        end=99,
        title="Test Volume",
        output_slug="test-volume",
    )
    return AppConfig(
        workspace=tmp_path,
        series_id="test-series",
        title="Test Series",
        language="zh-CN",
        creator="Test Creator",
        base_url=BASE_URL,
        index_path="/scp-series-1-tales-edition",
        scp001_path="/scp-001",
        cache_dir=tmp_path / "data" / "raw",
        manifest_dir=tmp_path / "data" / "manifests",
        processed_dir=tmp_path / "data" / "processed",
        output_dir=tmp_path / "output",
        request_delay_seconds=0,
        retry_count=1,
        volumes={volume_key: volume},
    )


class FakeFetcher:
    def __init__(self, root: Path, pages: dict[str, str], cached_slugs: set[str] | None = None):
        self.root = root
        self.pages = pages
        self.cached_slugs = cached_slugs or set()
        self.calls: list[tuple[str, str, bool]] = []

    def fetch_page(self, slug: str, url: str, *, force: bool = False) -> FetchResult:
        self.calls.append((slug, url, force))
        if slug not in self.pages:
            raise AssertionError(f"missing fake page for {slug}")
        safe_slug = slug.replace(":", "_")
        page_path = self.root / "pages" / f"{safe_slug}.html"
        metadata_path = self.root / "pages" / f"{safe_slug}.json"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(self.pages[slug], encoding="utf-8")
        metadata_path.write_text("{}", encoding="utf-8")
        return FetchResult(
            url=url,
            path=page_path,
            metadata_path=metadata_path,
            from_cache=slug in self.cached_slugs,
            status_code=200,
            content_type="text/html",
        )


def simple_page(title: str, body: str = "Body") -> str:
    return f"""
<html>
  <body>
    <div id="page-content">
      <h1>{title}</h1>
      <p>{body}</p>
    </div>
  </body>
</html>
"""


def simple_index(*slugs: str) -> str:
    items = "\n".join(
        f'<li><a href="/{slug}">{slug.upper()}</a></li>'
        for slug in slugs
    )
    return f"""
<html>
  <body>
    <div id="page-content">
      <h1>001到099</h1>
      <ul>{items}</ul>
    </div>
  </body>
</html>
"""


def test_build_manifest_fetches_sources_merges_scp001_and_writes_manifest(tmp_path: Path):
    config = app_config(tmp_path)
    pages = {
        "scp-series-1-tales-edition": Path("tests/fixtures/index_sample.html").read_text(encoding="utf-8"),
        "scp-001": Path("tests/fixtures/scp001_sample.html").read_text(encoding="utf-8"),
    }
    fetcher = FakeFetcher(tmp_path / "cache", pages)

    manifest = build_manifest(config, "001-099", fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == [
        "scp-series-1-tales-edition",
        "scp-001",
    ]
    assert [entry.slug for entry in manifest[:5]] == [
        "scp-001",
        "dr-clef-s-proposal",
        "djkaktus-s-proposal",
        "tuftos-proposal",
        "old:kalinins-proposal",
    ]
    assert "spc-001" in [entry.slug for entry in manifest]
    manifest_path = config.manifest_dir / "test-volume.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload[0]["slug"] == "scp-001"
    assert payload[1]["slug"] == "dr-clef-s-proposal"


def test_fetch_manifest_pages_fetches_each_manifest_entry(tmp_path: Path):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=1),
        PageRef("SCP-002", f"{BASE_URL}/scp-002", "scp-002", 1, "scp", order=2),
    ]
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-001": simple_page("SCP-001"),
            "scp-002": simple_page("SCP-002"),
        },
        cached_slugs={"scp-002"},
    )

    results = fetch_manifest_pages(config, manifest, fetcher=fetcher)

    assert [result.from_cache for result in results] == [False, True]
    assert [slug for slug, _url, _force in fetcher.calls] == ["scp-001", "scp-002"]


def test_build_volume_fetches_transforms_and_writes_epub_report_and_processed_files(tmp_path: Path):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=1),
        PageRef("SCP-002", f"{BASE_URL}/scp-002", "scp-002", 1, "scp", order=2),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-001": simple_page("SCP-001", "Hub body"),
            "scp-002": simple_page("SCP-002", 'Article body <a href="/scp-001">hub</a>'),
        },
        cached_slugs={"scp-001"},
    )

    output_path = build_volume(config, "001-099", fetcher=fetcher)

    assert output_path == config.output_dir / "epub" / "test-volume.epub"
    assert output_path.exists()
    with zipfile.ZipFile(output_path) as archive:
        names = archive.namelist()
        assert "OEBPS/text/0001-scp-001.xhtml" in names
        assert "OEBPS/text/0002-scp-002.xhtml" in names
    processed_dir = config.processed_dir / "test-volume"
    assert (processed_dir / "0001-scp-001.xhtml").exists()
    assert "Hub body" in (processed_dir / "0001-scp-001.xhtml").read_text(encoding="utf-8")
    report_path = config.output_dir / "reports" / "test-volume-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["page_count"] == 2
    assert report["output_path"] == str(output_path)
    assert report["internal_links"] == [f"{BASE_URL}/scp-001"]


def test_build_volume_force_rebuilds_existing_manifest_from_refreshed_sources(tmp_path: Path):
    config = app_config(tmp_path)
    stale_manifest = [
        PageRef("Stale Page", f"{BASE_URL}/stale-page", "stale-page", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(stale_manifest, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-series-1-tales-edition": simple_index("scp-001", "scp-002"),
            "scp-001": simple_page("SCP-001", "Refreshed hub"),
            "scp-002": simple_page("SCP-002", "Refreshed article"),
        },
    )

    output_path = build_volume(config, "001-099", fetcher=fetcher, force=True)

    assert output_path == config.output_dir / "epub" / "test-volume.epub"
    assert [slug for slug, _url, _force in fetcher.calls] == [
        "scp-series-1-tales-edition",
        "scp-001",
        "scp-001",
        "scp-002",
    ]
    assert all(force for _slug, _url, force in fetcher.calls)
    refreshed_manifest = json.loads((config.manifest_dir / "test-volume.json").read_text(encoding="utf-8"))
    assert [entry["slug"] for entry in refreshed_manifest] == ["scp-001", "scp-002"]
    report = json.loads((config.output_dir / "reports" / "test-volume-report.json").read_text(encoding="utf-8"))
    assert report["slugs"] == ["scp-001", "scp-002"]


def test_unknown_volume_key_raises_value_error(tmp_path: Path):
    config = app_config(tmp_path)

    with pytest.raises(ValueError, match="Unknown volume"):
        build_manifest(config, "missing-volume", fetcher=FakeFetcher(tmp_path / "cache", {}))
