from __future__ import annotations

import io
import json
import zipfile
from argparse import Namespace
from pathlib import Path

import pytest
from PIL import Image

from scp_epub.cache import CacheStore
from scp_epub.fetcher import Fetcher
from scp_epub.manifest import read_manifest
from scp_epub.models import (
    AppConfig,
    AppendixSection,
    AppendixSpec,
    ConfiguredLink,
    ConfiguredPage,
    FetchResult,
    InlineDocumentSpec,
    PageOverride,
    PageRef,
    VolumeSpec,
)
from scp_epub.pipeline import (
    _load_or_build_manifest,
    _load_or_build_manifest_for_build,
    build_featured_manifest,
    build_manifest,
    build_volume,
    fetch_build_pages,
    fetch_manifest_pages,
    run_command,
    scan_linked_appendices_for_volume,
)
from scp_epub.inline_documents import fetch_inline_document_results


BASE_URL = "https://scp-wiki-cn.wikidot.com"


def app_config(
    tmp_path: Path,
    *,
    volume_key: str = "001-099",
    include_scp001_proposals: bool = False,
    index_mode: str = "tales",
    featured_archive_url: str | None = None,
    include_linked_appendices: bool = True,
    featured_title_index_paths: tuple[str, ...] = (),
    front_matter_pages: tuple[ConfiguredPage, ...] = (),
    explicit_linked_appendices: dict[str, tuple[ConfiguredLink, ...]] | None = None,
    page_tab_includes: dict[str, tuple[str, ...]] | None = None,
    page_overrides: dict[str, PageOverride] | None = None,
    appendix: AppendixSpec | None = None,
) -> AppConfig:
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
        series_index_path="/scp-series",
        scp001_path="/scp-001",
        cache_dir=tmp_path / "data" / "raw",
        manifest_dir=tmp_path / "data" / "manifests",
        processed_dir=tmp_path / "data" / "processed",
        output_dir=tmp_path / "output",
        request_delay_seconds=0,
        request_timeout_seconds=30,
        retry_count=1,
        asset_timeout_seconds=5,
        asset_retry_count=1,
        include_scp001_proposals=include_scp001_proposals,
        volumes={volume_key: volume},
        index_mode=index_mode,
        featured_archive_url=featured_archive_url,
        include_linked_appendices=include_linked_appendices,
        featured_title_index_paths=featured_title_index_paths,
        front_matter_pages=front_matter_pages,
        explicit_linked_appendices=explicit_linked_appendices or {},
        page_tab_includes=page_tab_includes or {},
        page_overrides=page_overrides or {},
        appendix=appendix,
    )


class FakeFetcher:
    def __init__(
        self,
        root: Path,
        pages: dict[str, str],
        cached_slugs: set[str] | None = None,
        failed_pages: set[str] | None = None,
        assets: dict[str, tuple[str, bytes, str]] | None = None,
        failed_assets: set[str] | None = None,
    ):
        self.root = root
        self.pages = pages
        self.cached_slugs = cached_slugs or set()
        self.failed_pages = failed_pages or set()
        self.calls: list[tuple[str, str, bool]] = []
        self.assets = assets or {}
        self.failed_assets = failed_assets or set()
        self.asset_calls: list[tuple[str, bool]] = []

    def fetch_page(self, slug: str, url: str, *, force: bool = False) -> FetchResult:
        self.calls.append((slug, url, force))
        if slug in self.failed_pages:
            raise RuntimeError(f"failed fake page for {slug}")
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

    def fetch_asset(self, url: str, *, force: bool = False) -> FetchResult:
        self.asset_calls.append((url, force))
        if url in self.failed_assets:
            raise RuntimeError(f"missing fake asset for {url}")
        if url not in self.assets:
            raise AssertionError(f"missing fake asset for {url}")
        filename, content, content_type = self.assets[url]
        asset_path = self.root / "assets" / filename
        metadata_path = self.root / "assets" / f"{filename}.json"
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(content)
        metadata_path.write_text("{}", encoding="utf-8")
        return FetchResult(
            url=url,
            path=asset_path,
            metadata_path=metadata_path,
            from_cache=False,
            status_code=200,
            content_type=content_type,
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


def image_bytes(format_name: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, format=format_name)
    return output.getvalue()


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


def simple_series_index(*slugs: str) -> str:
    items = "\n".join(
        f'<li><a href="/{slug}">{slug.upper()}</a> - Title {slug}</li>'
        for slug in slugs
    )
    return f"""
<html>
  <body>
    <div id="page-content">
      <h1>SCP系列</h1>
      <ul>{items}</ul>
    </div>
  </body>
</html>
"""


def test_build_manifest_uses_tales_index_links_by_default(tmp_path: Path):
    config = app_config(tmp_path)
    pages = {
        "scp-series-1-tales-edition": Path("tests/fixtures/index_sample.html").read_text(encoding="utf-8"),
        "scp-series": simple_series_index("scp-001", "scp-002", "scp-019", "scp-020", "scp-099"),
    }
    fetcher = FakeFetcher(tmp_path / "cache", pages)

    manifest = build_manifest(config, "001-099", fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == [
        "scp-series-1-tales-edition",
        "scp-series",
    ]
    assert [entry.slug for entry in manifest[:3]] == ["scp-001", "spc-001", "scp-002"]
    assert "scp-019" in [entry.slug for entry in manifest]
    assert "scp-020" in [entry.slug for entry in manifest]
    assert "dr-clef-s-proposal" not in [entry.slug for entry in manifest]
    manifest_path = config.manifest_dir / "test-volume.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload[0]["slug"] == "scp-001"
    assert payload[1]["slug"] == "spc-001"
    assert payload[[entry["slug"] for entry in payload].index("scp-019")]["title"] == "SCP-019 - Title scp-019"


def test_build_manifest_can_merge_scp001_proposals_when_enabled(tmp_path: Path):
    config = app_config(tmp_path, include_scp001_proposals=True)
    pages = {
        "scp-series-1-tales-edition": Path("tests/fixtures/index_sample.html").read_text(encoding="utf-8"),
        "scp-series": simple_series_index("scp-001", "scp-002", "scp-099"),
        "scp-001": Path("tests/fixtures/scp001_sample.html").read_text(encoding="utf-8"),
    }
    fetcher = FakeFetcher(tmp_path / "cache", pages)

    manifest = build_manifest(config, "001-099", fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == [
        "scp-series-1-tales-edition",
        "scp-series",
        "scp-001",
    ]
    assert [entry.slug for entry in manifest[:6]] == [
        "scp-001",
        "spc-001",
        "dr-clef-s-proposal",
        "djkaktus-s-proposal",
        "tuftos-proposal",
        "old:kalinins-proposal",
    ]
    by_slug = {entry.slug: entry for entry in manifest}
    assert by_slug["dr-clef-s-proposal"].level == 1
    assert by_slug["dr-clef-s-proposal"].parent_slug is None
    assert "spc-001" in [entry.slug for entry in manifest]
    manifest_path = config.manifest_dir / "test-volume.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload[0]["slug"] == "scp-001"
    assert payload[1]["slug"] == "spc-001"
    assert payload[2]["slug"] == "dr-clef-s-proposal"


def test_build_manifest_featured_archive_follows_pages_and_uses_cached_chinese_titles(tmp_path: Path):
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
    )
    from scp_epub.manifest import write_manifest

    write_manifest(
        [
            PageRef(
                "SCP-2152 - 鱼子酱",
                f"{BASE_URL}/scp-2152",
                "scp-2152",
                1,
                "scp",
                order=1,
            )
        ],
        config.manifest_dir / "existing-series.json",
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "featured-scp-archive": """
              <div id="page-content">
                <a href="/featured-scp-archive-ii">Featured SCP Archive II</a>
                <a href="/scp-2152">SCP-2152</a>
              </div>
            """,
            "featured-scp-archive-ii": """
              <div id="page-content">
                <a href="/featured-scp-archive">Featured SCP Archive I</a>
                <a href="/scp-1632">SCP-1632</a>
                <a href="/scp-2152">SCP-2152 duplicate</a>
              </div>
            """,
        },
    )

    manifest = build_manifest(config, "featured", fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == [
        "featured-scp-archive",
        "featured-scp-archive-ii",
    ]
    assert [entry.slug for entry in manifest] == ["scp-2152", "scp-1632"]
    assert [entry.title for entry in manifest] == ["SCP-2152 - 鱼子酱", "SCP-1632"]
    assert [entry.url for entry in manifest] == [
        f"{BASE_URL}/scp-2152",
        f"{BASE_URL}/scp-1632",
    ]


def test_build_manifest_featured_archive_uses_configured_cn_series_title_indexes(tmp_path: Path):
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
        featured_title_index_paths=("/scp-series-9", "/scp-series-10"),
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "featured-scp-archive": """
              <div id="page-content">
                <a href="/scp-9000">SCP-9000</a>
                <a href="/scp-9928">SCP-9928</a>
              </div>
            """,
            "scp-series-9": """
              <div id="page-content">
                <ul><li><a href="/scp-8597">SCP-8597</a> - 不在精选里</li></ul>
              </div>
            """,
            "scp-series-10": """
              <div id="page-content">
                <ul>
                  <li><a href="/scp-9000">SCP-9000</a> - 失落之城</li>
                  <li><a href="/scp-9928">SCP-9928</a> - 记忆天井</li>
                </ul>
              </div>
            """,
        },
    )

    manifest = build_manifest(config, "featured", fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == [
        "scp-series-9",
        "scp-series-10",
        "featured-scp-archive",
    ]
    assert [entry.title for entry in manifest] == [
        "SCP-9000 - 失落之城",
        "SCP-9928 - 记忆天井",
    ]


def test_build_manifest_featured_archive_orders_entries_from_first_rank_forward(tmp_path: Path):
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "featured-scp-archive": """
              <div id="page-content">
                <a href="/featured-scp-archive-ii">Featured SCP Archive II</a>
                <p>100. <strong><a href="/scp-2152">SCP-2152</a></strong>: Home</p>
                <p>99. <strong><a href="/scp-1632">SCP-1632</a></strong>: Better Ring Xing</p>
              </div>
            """,
            "featured-scp-archive-ii": """
              <div id="page-content">
                <p>102. <strong><a href="/scp-2409">SCP-2409</a></strong>: Lost Precinct</p>
                <p>101. <strong><a href="/scp-1131">SCP-1131</a></strong>: The Oscar Bug</p>
              </div>
            """,
        },
    )

    manifest = build_manifest(config, "featured", fetcher=fetcher)

    assert [entry.slug for entry in manifest] == [
        "scp-1632",
        "scp-2152",
        "scp-1131",
        "scp-2409",
    ]
    assert [entry.order for entry in manifest] == [1, 2, 3, 4]


def test_build_manifest_featured_archive_prepends_front_matter_pages(tmp_path: Path):
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
        front_matter_pages=(
            ConfiguredPage(
                title="关于SCP基金会",
                url=f"{BASE_URL}/about-the-scp-foundation",
                slug="about-the-scp-foundation",
            ),
        ),
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "featured-scp-archive": """
              <div id="page-content">
                <p>1. <strong><a href="/scp-173">SCP-173</a></strong>: The Sculpture</p>
              </div>
            """,
        },
    )

    manifest = build_manifest(config, "featured", fetcher=fetcher)

    assert [entry.slug for entry in manifest] == ["about-the-scp-foundation", "scp-173"]
    assert [entry.title for entry in manifest] == ["关于SCP基金会", "SCP-173"]
    assert [entry.role for entry in manifest] == ["front-matter", "scp"]
    assert [entry.order for entry in manifest] == [1, 2]


def test_build_featured_manifest_appends_configured_appendix_sections_and_children_in_source_order(
    tmp_path: Path,
):
    appendix = AppendixSpec(
        title="附录",
        slug="appendix",
        sections=(
            AppendixSection("项目等级", f"{BASE_URL}/object-classes", "object-classes"),
            AppendixSection(
                "安保许可等级",
                f"{BASE_URL}/security-clearance-levels",
                "security-clearance-levels",
                include_tabs=("简介",),
                unwrap_single_tab=True,
            ),
            AppendixSection(
                "基金会设施",
                f"{BASE_URL}/secure-facilities-locations",
                "secure-facilities-locations",
                mode="facility-links",
            ),
            AppendixSection("基金会部门", f"{BASE_URL}/departments", "departments"),
            AppendixSection(
                "人事档案",
                f"{BASE_URL}/personnel-and-character-dossier",
                "personnel-and-character-dossier",
                mode="tabs-as-pages",
            ),
            AppendixSection(
                "O5指挥部档案",
                f"{BASE_URL}/o5-command-dossier",
                "o5-command-dossier",
                mode="tabs-as-pages",
            ),
            AppendixSection("相关组织", f"{BASE_URL}/groups-of-interest", "groups-of-interest"),
            AppendixSection("相关地点", f"{BASE_URL}/locations-of-interest", "locations-of-interest"),
        ),
    )
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
        appendix=appendix,
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "featured-scp-archive": """
              <div id="page-content">
                <p>2. <strong><a href="/scp-002">SCP-002</a></strong>: Two</p>
                <p>1. <strong><a href="/scp-001">SCP-001</a></strong>: One</p>
              </div>
            """,
            "object-classes": simple_page("项目等级"),
            "security-clearance-levels": simple_page("安保许可等级"),
            "secure-facilities-locations": """
              <div id="page-content">
                <a href="/site-19">安保设施档案：Site-19</a>
                <a href="/site-06">安保设施档案：Site-06</a>
              </div>
            """,
            "departments": simple_page("基金会部门"),
            "personnel-and-character-dossier": """
              <div id="page-content">
                <div class="yui-navset"><ul class="yui-nav">
                  <li>人事档案</li><li>研究人员</li>
                </ul><div class="yui-content"><div>档案</div><div>研究</div></div></div>
              </div>
            """,
            "o5-command-dossier": """
              <div id="page-content">
                <div class="yui-navset"><ul class="yui-nav">
                  <li>O5成员</li><li>历任成员</li>
                </ul><div class="yui-content"><div>成员</div><div>历任</div></div></div>
              </div>
            """,
            "groups-of-interest": simple_page("相关组织"),
            "locations-of-interest": simple_page("相关地点"),
        },
    )

    manifest = build_manifest(config, "featured", fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == [
        "featured-scp-archive",
        "object-classes",
        "security-clearance-levels",
        "secure-facilities-locations",
        "departments",
        "personnel-and-character-dossier",
        "o5-command-dossier",
        "groups-of-interest",
        "locations-of-interest",
    ]
    assert [entry.slug for entry in manifest[:2]] == ["scp-001", "scp-002"]
    assert manifest[-1].slug == "locations-of-interest"
    appendix_entry = next(entry for entry in manifest if entry.slug == "appendix")
    assert (appendix_entry.title, appendix_entry.level, appendix_entry.parent_slug) == (
        "附录",
        1,
        None,
    )
    assert [
        entry.slug for entry in manifest if entry.level == 1 and entry.parent_slug is None
    ][-1] == "appendix"
    sections = [
        entry
        for entry in manifest
        if entry.level == 2 and entry.parent_slug == "appendix"
    ]
    assert [entry.title for entry in sections] == [
        "项目等级",
        "安保许可等级",
        "基金会设施",
        "基金会部门",
        "人事档案",
        "O5指挥部档案",
        "相关组织",
        "相关地点",
    ]
    assert [(entry.title, entry.parent_slug) for entry in manifest if entry.level == 3] == [
        ("安保设施档案：Site-19", "secure-facilities-locations--appendix-group"),
        ("安保设施档案：Site-06", "secure-facilities-locations--appendix-group"),
        ("人事档案", "personnel-and-character-dossier--appendix-group"),
        ("研究人员", "personnel-and-character-dossier--appendix-group"),
        ("O5成员", "o5-command-dossier--appendix-group"),
        ("历任成员", "o5-command-dossier--appendix-group"),
    ]
    assert [entry.order for entry in manifest] == list(range(1, len(manifest) + 1))


def test_build_featured_manifest_preserves_configured_appendix_tab_titles(
    tmp_path: Path,
):
    tab_source_url = f"{BASE_URL}/personnel-and-character-dossier"
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
        appendix=AppendixSpec(
            title="附录",
            slug="appendix",
            sections=(
                AppendixSection(
                    "人事档案",
                    tab_source_url,
                    "personnel-and-character-dossier",
                    mode="tabs-as-pages",
                ),
            ),
        ),
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "featured-scp-archive": """
              <div id="page-content"><p>1. <a href="/scp-173">SCP-173</a></p></div>
            """,
            "personnel-and-character-dossier": """
              <div id="page-content"><div class="yui-navset">
                <ul class="yui-nav"><li>档案</li><li>研究</li></ul>
                <div class="yui-content"><div>档案正文。</div><div>研究正文。</div></div>
              </div></div>
            """,
        },
    )

    manifest = build_featured_manifest(config, "featured", fetcher=fetcher)
    tab_entries = [entry for entry in manifest if entry.role == "appendix-tab"]

    assert [(entry.slug, entry.tab_title) for entry in tab_entries] == [
        ("personnel-and-character-dossier--tab-1", "档案"),
        ("personnel-and-character-dossier--tab-2", "研究"),
    ]
    persisted_tab_entries = [
        entry
        for entry in read_manifest(config.manifest_dir / "test-volume.json")
        if entry.role == "appendix-tab"
    ]
    assert [(entry.slug, entry.tab_title) for entry in persisted_tab_entries] == [
        ("personnel-and-character-dossier--tab-1", "档案"),
        ("personnel-and-character-dossier--tab-2", "研究"),
    ]


def test_build_volume_rebuilds_legacy_featured_appendix_tab_manifest(tmp_path: Path):
    tab_source_url = f"{BASE_URL}/personnel-and-character-dossier"
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
        include_linked_appendices=False,
        appendix=AppendixSpec(
            title="附录",
            slug="appendix",
            sections=(
                AppendixSection(
                    "人事档案",
                    tab_source_url,
                    "personnel-and-character-dossier",
                    mode="tabs-as-pages",
                ),
            ),
        ),
    )
    from scp_epub.manifest import write_manifest

    write_manifest(
        [
            PageRef(
                "档案",
                tab_source_url,
                "personnel-and-character-dossier--tab-1",
                3,
                "appendix-tab",
                parent_slug="personnel-and-character-dossier--appendix-group",
                order=1,
            ),
        ],
        config.manifest_dir / "test-volume.json",
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "featured-scp-archive": """
              <div id="page-content"><p>1. <a href="/scp-173">SCP-173</a></p></div>
            """,
            "personnel-and-character-dossier": """
              <div id="page-content"><div class="yui-navset">
                <ul class="yui-nav"><li>档案</li><li>研究</li></ul>
                <div class="yui-content"><div>档案正文。</div><div>研究正文。</div></div>
              </div></div>
            """,
            "scp-173": simple_page("SCP-173"),
        },
    )

    build_volume(config, "featured", fetcher=fetcher)

    rebuilt_tab_entries = [
        entry
        for entry in read_manifest(config.manifest_dir / "test-volume.json")
        if entry.role == "appendix-tab"
    ]
    assert [(entry.slug, entry.tab_title) for entry in rebuilt_tab_entries] == [
        ("personnel-and-character-dossier--tab-1", "档案"),
        ("personnel-and-character-dossier--tab-2", "研究"),
    ]


def test_build_volume_rebuilds_legacy_featured_manifest_without_appendix_root(
    tmp_path: Path,
):
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
        include_linked_appendices=False,
        appendix=AppendixSpec(
            title="附录",
            slug="appendix",
            sections=(
                AppendixSection("项目等级", f"{BASE_URL}/object-classes", "object-classes"),
            ),
        ),
    )
    from scp_epub.manifest import write_manifest

    write_manifest(
        [PageRef("SCP-173", f"{BASE_URL}/scp-173", "scp-173", 1, "scp", order=1)],
        config.manifest_dir / "test-volume.json",
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "featured-scp-archive": """
              <div id="page-content"><p>1. <a href="/scp-173">SCP-173</a></p></div>
            """,
            "object-classes": simple_page("项目等级"),
            "scp-173": simple_page("SCP-173"),
        },
    )

    build_volume(config, "featured", fetcher=fetcher)

    assert [entry.slug for entry in read_manifest(config.manifest_dir / "test-volume.json")] == [
        "scp-173",
        "appendix",
        "object-classes",
    ]


def test_build_manifest_load_reuses_non_featured_appendix_cache_without_root(
    tmp_path: Path,
):
    config = app_config(
        tmp_path,
        appendix=AppendixSpec(
            title="附录",
            slug="appendix",
            sections=(
                AppendixSection("项目等级", f"{BASE_URL}/object-classes", "object-classes"),
            ),
        ),
    )
    cached_manifest = [
        PageRef("SCP-173", f"{BASE_URL}/scp-173", "scp-173", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(cached_manifest, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-series-1-tales-edition": simple_page("故事索引"),
            "scp-series": simple_page("SCP索引"),
        },
    )

    manifest, appendix_fetch_results = _load_or_build_manifest_for_build(
        config,
        "001-099",
        fetcher,
        force=False,
    )

    assert manifest == cached_manifest
    assert appendix_fetch_results == {}
    assert fetcher.calls == []


def test_fetch_manifest_load_reuses_legacy_featured_manifest_without_appendix_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
        appendix=AppendixSpec(
            title="附录",
            slug="appendix",
            sections=(
                AppendixSection("项目等级", f"{BASE_URL}/object-classes", "object-classes"),
            ),
        ),
    )
    cached_manifest = [
        PageRef("SCP-173", f"{BASE_URL}/scp-173", "scp-173", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(cached_manifest, config.manifest_dir / "test-volume.json")

    def fail_rebuild(*args: object, **kwargs: object) -> list[PageRef]:
        pytest.fail("normal fetch must not rebuild a manifest missing the appendix root")

    monkeypatch.setattr("scp_epub.pipeline.build_manifest", fail_rebuild)

    manifest = _load_or_build_manifest(config, "featured", None, force=False)

    assert manifest == cached_manifest


def test_build_volume_materializes_appendix_groups_and_unwraps_tab_children(tmp_path: Path):
    appendix = AppendixSpec(
        title="附录",
        slug="appendix",
        sections=(
            AppendixSection(
                "人事档案",
                f"{BASE_URL}/personnel-and-character-dossier",
                "personnel-and-character-dossier",
                mode="tabs-as-pages",
            ),
        ),
    )
    config = app_config(tmp_path, include_linked_appendices=False, appendix=appendix)
    manifest = [
        PageRef("附录", f"{BASE_URL}/appendix", "appendix", 1, "appendix-group", order=1),
        PageRef(
            "人事档案",
            f"{BASE_URL}/personnel-and-character-dossier",
            "personnel-and-character-dossier--appendix-group",
            2,
            "appendix-group",
            parent_slug="appendix",
            order=2,
        ),
        PageRef(
            "人事档案",
            f"{BASE_URL}/personnel-and-character-dossier",
            "personnel-and-character-dossier--tab-1",
            3,
            "appendix-tab",
            parent_slug="personnel-and-character-dossier--appendix-group",
            order=3,
            tab_title="人事档案",
        ),
        PageRef(
            "研究人员",
            f"{BASE_URL}/personnel-and-character-dossier",
            "personnel-and-character-dossier--tab-2",
            3,
            "appendix-tab",
            parent_slug="personnel-and-character-dossier--appendix-group",
            order=4,
            tab_title="研究人员",
        ),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "personnel-and-character-dossier": """
              <div id="page-content"><div class="yui-navset">
                <ul class="yui-nav"><li>人事档案</li><li>研究人员</li></ul>
                <div class="yui-content"><div><p>档案正文。</p></div><div><p>研究正文。</p></div></div>
              </div></div>
            """,
        },
    )

    build_volume(config, "001-099", fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == ["personnel-and-character-dossier"]
    first_tab = (config.processed_dir / "test-volume" / "0003-personnel-and-character-dossier--tab-1.xhtml").read_text(encoding="utf-8")
    second_tab = (config.processed_dir / "test-volume" / "0004-personnel-and-character-dossier--tab-2.xhtml").read_text(encoding="utf-8")
    assert "档案正文。" in first_tab
    assert "研究正文。" not in first_tab
    assert "tabview-epub" not in first_tab
    assert "标签：人事档案" not in first_tab
    assert "研究正文。" in second_tab
    assert "档案正文。" not in second_tab


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


def test_fetch_paths_preserve_normal_duplicate_fetches_and_reuse_appendix_tab_sources(
    tmp_path: Path,
):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=1),
        PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=2),
        PageRef(
            "档案",
            f"{BASE_URL}/personnel-and-character-dossier",
            "personnel-and-character-dossier--tab-1",
            3,
            "appendix-tab",
            parent_slug="personnel-and-character-dossier",
            order=3,
            tab_title="档案",
        ),
        PageRef(
            "研究",
            f"{BASE_URL}/personnel-and-character-dossier",
            "personnel-and-character-dossier--tab-2",
            3,
            "appendix-tab",
            parent_slug="personnel-and-character-dossier",
            order=4,
            tab_title="研究",
        ),
    ]
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-001": simple_page("SCP-001"),
            "personnel-and-character-dossier": simple_page("人事档案"),
        },
    )

    fetch_manifest_pages(config, manifest, fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == [
        "scp-001",
        "scp-001",
        "personnel-and-character-dossier",
    ]
    fetcher.calls.clear()

    available_manifest, _results, missing_pages = fetch_build_pages(config, manifest, fetcher)

    assert available_manifest == manifest
    assert missing_pages == []
    assert [slug for slug, _url, _force in fetcher.calls] == [
        "scp-001",
        "scp-001",
        "personnel-and-character-dossier",
    ]


def test_fetching_generated_appendix_groups_does_not_replace_cached_facility_source(
    tmp_path: Path,
):
    source_url = f"{BASE_URL}/secure-facilities-locations"
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
        appendix=AppendixSpec(
            title="附录",
            slug="appendix",
            sections=(
                AppendixSection(
                    "基金会设施",
                    source_url,
                    "secure-facilities-locations",
                    mode="facility-links",
                ),
            ),
        ),
    )
    requested_urls: list[str] = []
    pages = {
        "https://scp-wiki.wikidot.com/featured-scp-archive": """
          <div id="page-content"><p>1. <a href="/scp-173">SCP-173</a></p></div>
        """,
        f"{BASE_URL}/scp-173": simple_page("SCP-173"),
        f"{BASE_URL}/site-19": simple_page("Site-19"),
        source_url: """
          <div id="page-content"><a href="/site-19">安保设施档案：Site-19</a></div>
        """,
    }

    def http_client(url: str, *, headers: dict[str, str]):
        requested_urls.append(url)
        return pages[url], 200, "text/html"

    fetcher = Fetcher(CacheStore(config.cache_dir), http_client=http_client)
    manifest = build_manifest(config, "featured", fetcher=fetcher)

    fetch_manifest_pages(config, manifest, fetcher=fetcher)
    rebuilt_manifest = build_manifest(config, "featured", fetcher=fetcher)

    facility_group = next(
        entry for entry in rebuilt_manifest if entry.title == "基金会设施"
    )
    assert facility_group.slug == "secure-facilities-locations--appendix-group"
    assert [
        (entry.title, entry.parent_slug)
        for entry in rebuilt_manifest
        if entry.role == "appendix-facility"
    ] == [("安保设施档案：Site-19", facility_group.slug)]
    assert requested_urls == [
        "https://scp-wiki.wikidot.com/featured-scp-archive",
        source_url,
        f"{BASE_URL}/scp-173",
        f"{BASE_URL}/site-19",
    ]


def test_force_build_reuses_configured_appendix_sources_from_manifest_expansion(
    tmp_path: Path,
):
    page_source_url = f"{BASE_URL}/object-classes"
    tab_source_url = f"{BASE_URL}/personnel-and-character-dossier"
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
        include_linked_appendices=False,
        appendix=AppendixSpec(
            title="附录",
            slug="appendix",
            sections=(
                AppendixSection("项目等级", page_source_url, "object-classes"),
                AppendixSection(
                    "人事档案",
                    tab_source_url,
                    "personnel-and-character-dossier",
                    mode="tabs-as-pages",
                ),
            ),
        ),
    )
    requested_urls: list[str] = []
    pages = {
        "https://scp-wiki.wikidot.com/featured-scp-archive": """
          <div id="page-content"><p>1. <a href="/scp-173">SCP-173</a></p></div>
        """,
        f"{BASE_URL}/scp-173": simple_page("SCP-173"),
        page_source_url: simple_page("项目等级"),
        tab_source_url: """
          <div id="page-content"><div class="yui-navset">
            <ul class="yui-nav"><li>档案</li><li>研究</li></ul>
            <div class="yui-content"><div>档案正文。</div><div>研究正文。</div></div>
          </div></div>
        """,
    }

    def http_client(url: str, *, headers: dict[str, str]):
        requested_urls.append(url)
        return pages[url], 200, "text/html"

    build_volume(
        config,
        "featured",
        fetcher=Fetcher(CacheStore(config.cache_dir), http_client=http_client),
        force=True,
    )

    assert requested_urls.count(page_source_url) == 1
    assert requested_urls.count(tab_source_url) == 1


def test_fetch_refresh_reuses_configured_appendix_sources_from_manifest_expansion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source_url = f"{BASE_URL}/object-classes"
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
        appendix=AppendixSpec(
            title="附录",
            slug="appendix",
            sections=(AppendixSection("项目等级", source_url, "object-classes"),),
        ),
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "featured-scp-archive": """
              <div id="page-content"><p>1. <a href="/scp-173">SCP-173</a></p></div>
            """,
            "scp-173": simple_page("SCP-173"),
            "object-classes": simple_page("项目等级"),
        },
    )
    monkeypatch.setattr("scp_epub.pipeline.load_config", lambda _path: config)
    monkeypatch.setattr("scp_epub.pipeline.make_fetcher", lambda _config: fetcher)

    run_command(
        Namespace(
            config=tmp_path / "featured.yaml",
            command="fetch",
            volume="featured",
            refresh=True,
        )
    )

    assert [slug for slug, _url, _force in fetcher.calls].count("object-classes") == 1
    assert all(force for _slug, _url, force in fetcher.calls)


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


def test_build_volume_attaches_matching_cover_image_when_present(tmp_path: Path):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    cover_path = config.workspace / "cover" / "test-volume-cover.png"
    cover_path.parent.mkdir(parents=True)
    cover_path.write_bytes(b"cover png")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {"scp-001": simple_page("SCP-001", "Hub body")},
    )

    output_path = build_volume(config, "001-099", fetcher=fetcher)

    with zipfile.ZipFile(output_path) as archive:
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        assert archive.read("OEBPS/images/cover.png") == b"cover png"
        assert "OEBPS/cover.xhtml" in archive.namelist()
    assert '<meta name="cover" content="cover-image"/>' in opf
    assert 'properties="cover-image"' in opf


def test_build_volume_localizes_assets_and_reports_missing_assets(tmp_path: Path):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    good_url = f"{BASE_URL}/images/photo.png"
    missing_url = f"{BASE_URL}/images/missing.png"
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-001": simple_page(
                "SCP-001",
                f'Article body <img src="/images/photo.png"/><object data="/images/missing.png"></object>',
            ),
        },
        assets={good_url: ("photo.png", b"png data", "image/png")},
        failed_assets={missing_url},
    )

    output_path = build_volume(config, "001-099", fetcher=fetcher)

    assert fetcher.asset_calls == [(good_url, False), (missing_url, False)]
    with zipfile.ZipFile(output_path) as archive:
        assert archive.read("OEBPS/assets/photo.png") == b"png data"
        chapter = archive.read("OEBPS/text/0001-scp-001.xhtml").decode("utf-8")
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
    assert '../assets/photo.png' in chapter
    assert missing_url in chapter
    assert '<item id="asset-0001" href="assets/photo.png" media-type="image/png"/>' in opf
    assert (
        '<item id="page-0001" href="text/0001-scp-001.xhtml" '
        'media-type="application/xhtml+xml" properties="remote-resources"/>'
    ) in opf
    report = json.loads((config.output_dir / "reports" / "test-volume-report.json").read_text(encoding="utf-8"))
    assert report["asset_urls"] == [good_url, missing_url]
    assert report["missing_assets"] == [missing_url]


def test_build_volume_skips_failed_pages_and_reports_missing_pages(tmp_path: Path):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=1),
        PageRef("Missing Tale", f"{BASE_URL}/missing-tale", "missing-tale", 2, "related", order=2),
        PageRef("SCP-002", f"{BASE_URL}/scp-002", "scp-002", 1, "scp", order=3),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-001": simple_page("SCP-001", "First body"),
            "scp-002": simple_page("SCP-002", "Second body"),
        },
        failed_pages={"missing-tale"},
    )

    output_path = build_volume(config, "001-099", fetcher=fetcher)

    with zipfile.ZipFile(output_path) as archive:
        names = archive.namelist()
        assert "OEBPS/text/0001-scp-001.xhtml" in names
        assert "OEBPS/text/0002-missing-tale.xhtml" not in names
        assert "OEBPS/text/0003-scp-002.xhtml" in names
    report = json.loads((config.output_dir / "reports" / "test-volume-report.json").read_text(encoding="utf-8"))
    assert report["page_count"] == 2
    assert report["missing_pages"] == [
        {
            "slug": "missing-tale",
            "title": "Missing Tale",
            "url": f"{BASE_URL}/missing-tale",
            "reason": "failed fake page for missing-tale",
        }
    ]


def test_build_volume_includes_high_confidence_linked_appendices_under_group(tmp_path: Path):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-093", f"{BASE_URL}/scp-093", "scp-093", 1, "scp", order=1),
        PageRef(
            "SCP-093 Story",
            f"{BASE_URL}/scp-093-story",
            "scp-093-story",
            2,
            "related",
            parent_slug="scp-093",
            order=2,
        ),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-093": simple_page(
                "SCP-093",
                '<a href="/scp-093-blue-test">SCP-093“蓝色”测试</a>',
            ),
            "scp-093-story": simple_page("SCP-093 Story", "Story body"),
            "scp-093-blue-test": simple_page("Blue Test", "Blue test body"),
        },
    )

    build_volume(config, "001-099", fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == [
        "scp-093",
        "scp-093-story",
        "scp-093-blue-test",
    ]
    processed_dir = config.processed_dir / "test-volume"
    assert (processed_dir / "0002-scp-093--linked-appendices.xhtml").exists()
    assert "原文附属文档" in (
        processed_dir / "0002-scp-093--linked-appendices.xhtml"
    ).read_text(encoding="utf-8")
    assert "Blue test body" in (
        processed_dir / "0003-scp-093-blue-test.xhtml"
    ).read_text(encoding="utf-8")
    report = json.loads((config.output_dir / "reports" / "test-volume-report.json").read_text(encoding="utf-8"))
    assert report["slugs"] == [
        "scp-093",
        "scp-093--linked-appendices",
        "scp-093-blue-test",
        "scp-093-story",
    ]
    assert report["titles"] == [
        "SCP-093",
        "原文附属文档",
        "SCP-093“蓝色”测试",
        "SCP-093 Story",
    ]


def test_build_volume_inherits_only_scp5109_terminal_navigation_cleanup_for_linked_appendices(
    tmp_path: Path,
):
    config = app_config(
        tmp_path,
        page_overrides={
            "scp-5109": PageOverride(
                remove_terminal_navigation=True,
                remove_adult_content_warning=True,
            )
        },
    )
    manifest = [
        PageRef("SCP-5109", f"{BASE_URL}/scp-5109", "scp-5109", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-5109": simple_page(
                "SCP-5109",
                '<a href="/scp-5109-offset">SCP-5109附件</a>',
            ),
            "scp-5109-offset": """
              <html><body><div id="page-content">
                <p>附属文档正文。</p>
                <div id="u-adult-warning">不应继承的成人警告清理。</div>
                <div id="terminal-nav">« <a href="/one">One</a> | <a href="/two">Two</a> | <a href="/three">Three</a> »</div>
              </div></body></html>
            """,
        },
    )

    build_volume(config, "001-099", fetcher=fetcher)

    appendix_xhtml = (
        config.processed_dir / "test-volume" / "0003-scp-5109-offset.xhtml"
    ).read_text(encoding="utf-8")
    assert "terminal-nav" not in appendix_xhtml
    assert "不应继承的成人警告清理" in appendix_xhtml


def test_build_volume_applies_configured_layout_profile(tmp_path: Path):
    config = app_config(
        tmp_path,
        page_overrides={
            "scp-4612": PageOverride(layout_profile="scp-4612"),
        },
    )
    manifest = [
        PageRef("SCP-4612", f"{BASE_URL}/scp-4612", "scp-4612", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-4612": simple_page(
                "SCP-4612",
                '<div id="estate-image" class="scp-image-block block-right" '
                'style="float: right; width: 320px"><img src="/estate.jpg" /></div>'
                "<p>宅邸的调查仍在继续。</p>",
            ),
        },
    )

    build_volume(config, "001-099", fetcher=fetcher)

    page_xhtml = (config.processed_dir / "test-volume" / "0001-scp-4612.xhtml").read_text(
        encoding="utf-8"
    )
    assert "layout-profile-scp-4612-image" in page_xhtml
    assert 'style="width: 320px; float: none; clear: both; max-width: 100%"' in page_xhtml


def test_build_volume_can_disable_linked_appendices_for_featured_books(tmp_path: Path):
    config = app_config(tmp_path, include_linked_appendices=False)
    manifest = [
        PageRef("SCP-093", f"{BASE_URL}/scp-093", "scp-093", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-093": simple_page(
                "SCP-093",
                '<a href="/scp-093-blue-test">SCP-093“蓝色”测试</a>',
            ),
            "scp-093-blue-test": simple_page("Blue Test", "Blue test body"),
        },
    )

    build_volume(config, "001-099", fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == ["scp-093"]
    report = json.loads((config.output_dir / "reports" / "test-volume-report.json").read_text(encoding="utf-8"))
    assert report["slugs"] == ["scp-093"]


def test_build_volume_includes_configured_linked_appendix_chain(tmp_path: Path):
    config = app_config(
        tmp_path,
        explicit_linked_appendices={
            "scp-5170": (
                ConfiguredLink(
                    title="#1附件A",
                    url=f"{BASE_URL}/scp-5170/offset/1",
                    slug="scp-5170/offset/1",
                ),
                ConfiguredLink(
                    title="#2附件B",
                    url=f"{BASE_URL}/scp-5170/offset/2",
                    slug="scp-5170/offset/2",
                ),
                ConfiguredLink(
                    title="#3附件C",
                    url=f"{BASE_URL}/scp-5170/offset/3",
                    slug="scp-5170/offset/3",
                ),
            )
        },
    )
    from scp_epub.manifest import write_manifest

    write_manifest(
        [PageRef("SCP-5170", f"{BASE_URL}/scp-5170", "scp-5170", 1, "scp", order=1)],
        config.manifest_dir / "test-volume.json",
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-5170": simple_page("SCP-5170", '<a href="/scp-5170/offset/1">#1附件A</a>'),
            "scp-5170/offset/1": simple_page("#1附件A", '<a href="/scp-5170/offset/2">#2附件B</a>'),
            "scp-5170/offset/2": simple_page("#2附件B", '<a href="/scp-5170/offset/3">#3附件C</a>'),
            "scp-5170/offset/3": simple_page("#3附件C", "附件C正文"),
        },
    )

    build_volume(config, "001-099", fetcher=fetcher)

    report = json.loads((config.output_dir / "reports" / "test-volume-report.json").read_text(encoding="utf-8"))
    assert report["slugs"] == [
        "scp-5170",
        "scp-5170--linked-appendices",
        "scp-5170/offset/1",
        "scp-5170/offset/2",
        "scp-5170/offset/3",
    ]


def test_fetch_inline_documents_skips_configured_owner_absent_from_manifest(tmp_path: Path):
    config = app_config(
        tmp_path,
        page_overrides={
            "scp-1898": PageOverride(
                inline_documents=(
                    InlineDocumentSpec(
                        "相关图片",
                        f"{BASE_URL}/scp-1898-offset",
                        "scp-1898-offset",
                        "append",
                    ),
                ),
            ),
        },
    )
    manifest = [PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=1)]
    fetcher = FakeFetcher(tmp_path / "cache", {"scp-001": simple_page("SCP-001")})

    results = fetch_inline_document_results(config, manifest, fetcher, force=False)

    assert results == {}
    assert fetcher.calls == []


def test_build_volume_excludes_auto_appendix_for_inline_url_with_host_case_and_trailing_slash(
    tmp_path: Path,
):
    inline_url = "https://SCP-WIKI-CN.WIKIDOT.COM/scp-1898-offset/"
    config = app_config(
        tmp_path,
        page_overrides={
            "scp-1898": PageOverride(
                inline_documents=(
                    InlineDocumentSpec(
                        "相关图片",
                        inline_url,
                        "scp-1898-offset",
                        "after_text",
                        "附录-1898-1：相关SCP-1898图片",
                    ),
                ),
            ),
        },
    )
    from scp_epub.manifest import write_manifest

    write_manifest(
        [PageRef("SCP-1898", f"{BASE_URL}/scp-1898", "scp-1898", 1, "scp", order=1)],
        config.manifest_dir / "test-volume.json",
    )
    image_url = "https://SCP-WIKI-CN.WIKIDOT.COM/images/inline.png"
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-1898": simple_page(
                "SCP-1898",
                '<p>附录-1898-1：相关SCP-1898图片</p><a href="/scp-1898-offset">附录图片</a>',
            ),
            "scp-1898-offset": simple_page(
                "相关图片",
                '<p>内联文档正文 <img src="/images/inline.png"/><a href="/scp-1898">返回</a></p>',
            ),
        },
        assets={image_url: ("inline.png", b"png", "image/png")},
    )

    output_path = build_volume(config, "001-099", fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == ["scp-1898", "scp-1898-offset"]
    report = json.loads((config.output_dir / "reports" / "test-volume-report.json").read_text(encoding="utf-8"))
    assert report["slugs"] == ["scp-1898"]
    assert report["asset_urls"] == [image_url]
    processed = (config.processed_dir / "test-volume" / "0001-scp-1898.xhtml").read_text(encoding="utf-8")
    assert "inline-document-epub" in processed
    assert "内联文档正文" in processed
    with zipfile.ZipFile(output_path) as archive:
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        assert "scp-1898-offset" not in "\n".join(archive.namelist())
        assert "相关图片" not in nav


def test_build_volume_inlines_featured_companions_without_appendix_navigation(
    tmp_path: Path,
):
    companion_specs = {
        "scp-1898": (
            InlineDocumentSpec(
                "SCP-1898 相关图片",
                f"{BASE_URL}/scp-1898-appendix",
                "scp-1898-appendix",
                "after_text",
                "附录-1898-1：相关SCP-1898图片",
            ),
        ),
        "scp-7503": tuple(
            InlineDocumentSpec(
                f"SCP-7503 Offset {index}",
                f"{BASE_URL}/scp-7503-offset-{index}",
                f"scp-7503-offset-{index}",
                "append",
            )
            for index in range(1, 5)
        ),
        "scp-6445": (
            InlineDocumentSpec(
                "SCP-6445 Offset 1",
                f"{BASE_URL}/scp-6445-offset-1",
                "scp-6445-offset-1",
                "append",
            ),
        ),
        "scp-2814": (
            InlineDocumentSpec(
                "Document 2814-Gamma",
                f"{BASE_URL}/scp-2814-appendix",
                "scp-2814-appendix",
                "before_text",
                "Footnotes",
            ),
        ),
    }
    config = app_config(
        tmp_path,
        page_overrides={
            owner: PageOverride(inline_documents=documents)
            for owner, documents in companion_specs.items()
        },
    )
    owners = [
        PageRef("SCP-1898", f"{BASE_URL}/scp-1898", "scp-1898", 1, "scp", order=1),
        PageRef("SCP-7503", f"{BASE_URL}/scp-7503", "scp-7503", 1, "scp", order=2),
        PageRef("SCP-6445", f"{BASE_URL}/scp-6445", "scp-6445", 1, "scp", order=3),
        PageRef("SCP-2814", f"{BASE_URL}/scp-2814", "scp-2814", 1, "scp", order=4),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(owners, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-1898": simple_page(
                "SCP-1898",
                "<p>附录-1898-1：相关SCP-1898图片</p>"
                '<a href="/scp-1898-appendix">SCP-1898 附录文档</a>',
            ),
            "scp-1898-appendix": simple_page("SCP-1898 相关图片", "1898 附件正文。"),
            "scp-7503": simple_page(
                "SCP-7503",
                "".join(
                    f'<a href="/scp-7503-offset-{index}">SCP-7503 附录文档 {index}</a>'
                    for index in range(1, 5)
                ),
            ),
            "scp-7503-offset-1": simple_page("Offset 1", "7503 迭代 1。"),
            "scp-7503-offset-2": simple_page("Offset 2", "7503 迭代 2。"),
            "scp-7503-offset-3": simple_page("Offset 3", "7503 迭代 3。"),
            "scp-7503-offset-4": simple_page("Offset 4", "7503 迭代 4。"),
            "scp-6445": simple_page(
                "SCP-6445",
                '<a href="/scp-6445-offset-1">SCP-6445 附录文档</a>',
            ),
            "scp-6445-offset-1": simple_page("Offset 1", "6445 附件正文。"),
            "scp-2814": simple_page(
                "SCP-2814",
                '<a href="/scp-2814-appendix">SCP-2814 附录文档</a>'
                '<div class="footnotes-footer"><div class="title">Footnotes</div></div>',
            ),
            "scp-2814-appendix": simple_page("Document 2814-Gamma", "2814 附件正文。"),
        },
    )

    output_path = build_volume(config, "001-099", fetcher=fetcher)

    report = json.loads(
        (config.output_dir / "reports" / "test-volume-report.json").read_text(encoding="utf-8")
    )
    assert report["slugs"] == [entry.slug for entry in owners]
    assert "原文附属文档" not in report["titles"]

    with zipfile.ZipFile(output_path) as archive:
        names = "\n".join(archive.namelist())
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        ncx = archive.read("OEBPS/toc.ncx").decode("utf-8")
        chapters = {
            entry.slug: archive.read(
                f"OEBPS/text/{entry.order:04d}-{entry.slug}.xhtml"
            ).decode("utf-8")
            for entry in owners
        }

    companion_slugs = [
        document.slug
        for documents in companion_specs.values()
        for document in documents
    ]
    for companion_slug in companion_slugs:
        assert companion_slug not in names
        assert companion_slug not in opf
        assert companion_slug not in nav
        assert companion_slug not in ncx
    assert "原文附属文档" not in opf
    assert "原文附属文档" not in nav
    assert "原文附属文档" not in ncx
    assert "1898 附件正文。" in chapters["scp-1898"]
    assert [chapters["scp-7503"].index(f"7503 迭代 {index}。") for index in range(1, 5)] == sorted(
        chapters["scp-7503"].index(f"7503 迭代 {index}。") for index in range(1, 5)
    )
    assert "6445 附件正文。" in chapters["scp-6445"]
    assert chapters["scp-2814"].index("2814 附件正文。") < chapters["scp-2814"].index(
        "Footnotes"
    )


def test_build_volume_force_rebuilds_existing_manifest_from_refreshed_sources(tmp_path: Path):
    config = app_config(tmp_path)
    stale_manifest = [
        PageRef("Stale Page", f"{BASE_URL}/stale-page", "stale-page", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(stale_manifest, config.manifest_dir / "test-volume.json")
    asset_url = f"{BASE_URL}/images/refreshed.png"
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-series-1-tales-edition": simple_index("scp-001", "scp-002"),
            "scp-series": simple_series_index("scp-001", "scp-002"),
            "scp-001": simple_page("SCP-001", 'Refreshed hub <img src="/images/refreshed.png"/>'),
            "scp-002": simple_page("SCP-002", "Refreshed article"),
        },
        assets={asset_url: ("refreshed.png", b"png data", "image/png")},
    )

    output_path = build_volume(config, "001-099", fetcher=fetcher, force=True)

    assert output_path == config.output_dir / "epub" / "test-volume.epub"
    assert [slug for slug, _url, _force in fetcher.calls] == [
        "scp-series-1-tales-edition",
        "scp-series",
        "scp-001",
        "scp-002",
    ]
    assert all(force for _slug, _url, force in fetcher.calls)
    assert fetcher.asset_calls == [(asset_url, True)]
    refreshed_manifest = json.loads((config.manifest_dir / "test-volume.json").read_text(encoding="utf-8"))
    assert [entry["slug"] for entry in refreshed_manifest] == ["scp-001", "scp-002"]
    report = json.loads((config.output_dir / "reports" / "test-volume-report.json").read_text(encoding="utf-8"))
    assert report["slugs"] == ["scp-001", "scp-002"]


def test_scan_linked_appendices_ignores_refresh_for_legacy_tab_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    tab_source_url = f"{BASE_URL}/personnel-and-character-dossier"
    config = app_config(
        tmp_path,
        volume_key="featured",
        index_mode="featured-scp-archive",
        featured_archive_url="https://scp-wiki.wikidot.com/featured-scp-archive",
        appendix=AppendixSpec(
            title="附录",
            slug="appendix",
            sections=(
                AppendixSection(
                    "人事档案",
                    tab_source_url,
                    "personnel-and-character-dossier",
                    mode="tabs-as-pages",
                ),
            ),
        ),
    )
    legacy_entry = PageRef(
        "档案",
        tab_source_url,
        "personnel-and-character-dossier--tab-1",
        3,
        "appendix-tab",
        parent_slug="personnel-and-character-dossier--appendix-group",
        order=1,
    )
    from scp_epub.manifest import write_manifest

    manifest_path = config.manifest_dir / "test-volume.json"
    write_manifest([legacy_entry], manifest_path)
    manifest_before = manifest_path.read_text(encoding="utf-8")
    CacheStore(config.cache_dir).write_page(
        legacy_entry.slug,
        legacy_entry.url,
        """
        <html><body><div id="page-content">
          <a href="/scp-093-blue-test">SCP-093“蓝色”测试</a>
        </div></body></html>
        """,
        200,
        "text/html",
    )

    def fail_rebuild(*args: object, **kwargs: object) -> list[PageRef]:
        pytest.fail("scan-linked-appendices must not rebuild a cached manifest")

    monkeypatch.setattr("scp_epub.pipeline.build_manifest", fail_rebuild)

    report_path = scan_linked_appendices_for_volume(config, "featured", force=True)

    assert manifest_path.read_text(encoding="utf-8") == manifest_before
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload[0]["source_slug"] == legacy_entry.slug
    assert payload[0]["candidates"][0]["slug"] == "scp-093-blue-test"


def test_scan_linked_appendices_for_volume_writes_report_from_cached_pages(tmp_path: Path):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-093", f"{BASE_URL}/scp-093", "scp-093", 1, "scp", order=1),
    ]
    from scp_epub.cache import CacheStore
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    cache = CacheStore(config.cache_dir)
    cache.write_page(
        "scp-093",
        f"{BASE_URL}/scp-093",
        """
        <html><body><div id="page-content">
          <a href="/scp-093-blue-test">SCP-093“蓝色”测试</a>
        </div></body></html>
        """,
        200,
        "text/html",
    )

    report_path = scan_linked_appendices_for_volume(config, "001-099")

    assert report_path == config.output_dir / "reports" / "test-volume-linked-appendices.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload[0]["source_slug"] == "scp-093"
    assert payload[0]["candidates"][0]["slug"] == "scp-093-blue-test"


def test_unknown_volume_key_raises_value_error(tmp_path: Path):
    config = app_config(tmp_path)

    with pytest.raises(ValueError, match="Unknown volume"):
        build_manifest(config, "missing-volume", fetcher=FakeFetcher(tmp_path / "cache", {}))


def test_build_volume_kindles_pages_css_report_and_azw3_without_mutating_processed_xhtml(
    tmp_path: Path,
):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-001": simple_page(
                "SCP-001",
                '<div class="anom-bar-container clear-4">'
                '<div class="top-right-box"><div class="clearance"></div></div>'
                '<div class="risk-class"><div class="class-text">危急</div></div>'
                '<div class="danger-diamond"></div>'
                "</div>",
            ),
        },
    )
    conversion_calls = []

    def fake_converter(epub_path: Path, azw3_path: Path) -> Path:
        conversion_calls.append((epub_path, azw3_path))
        assert epub_path.exists()
        azw3_path.parent.mkdir(parents=True, exist_ok=True)
        azw3_path.write_bytes(b"azw3")
        return azw3_path

    output_path = build_volume(
        config,
        "001-099",
        fetcher=fetcher,
        kindle=True,
        kindle_converter=fake_converter,
    )

    assert output_path == config.output_dir / "epub" / "test-volume-Kindle.epub"
    azw3_path = config.output_dir / "azw3" / "test-volume-Kindle.azw3"
    assert conversion_calls == [(output_path, azw3_path)]
    assert azw3_path.read_bytes() == b"azw3"

    with zipfile.ZipFile(output_path) as archive:
        css = archive.read("OEBPS/styles/book.css").decode("utf-8")
        chapter = archive.read("OEBPS/text/0001-scp-001.xhtml").decode("utf-8")
    assert ".kindle-clearance-label" in css
    assert '<span class="kindle-clearance-label">SECRET</span>' in chapter
    assert '<span class="kindle-danger-label">危急</span>' in chapter

    processed_path = config.processed_dir / "test-volume" / "0001-scp-001.xhtml"
    assert "kindle-clearance-label" not in processed_path.read_text(encoding="utf-8")
    report_path = config.output_dir / "reports" / "test-volume-Kindle-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["output_path"] == str(output_path)


def test_build_volume_prepares_only_kindle_assets_and_reports_invalid_images(
    tmp_path: Path,
):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    webp_url = f"{BASE_URL}/images/photo.webp"
    invalid_url = f"{BASE_URL}/images/missing.png"
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-001": simple_page(
                "SCP-001",
                '<img src="/images/photo.webp" alt="有效图"/>'
                '<img src="/images/missing.png" alt="缺失图"/>',
            ),
        },
        assets={
            webp_url: ("photo.webp", image_bytes("WEBP"), "application/octet-stream"),
            invalid_url: (
                "missing.png",
                b"<!doctype html><title>404 Not Found</title>",
                "text/html",
            ),
        },
    )
    conversion_calls = []

    def fake_converter(epub_path: Path, azw3_path: Path) -> Path:
        conversion_calls.append((epub_path, azw3_path))
        with zipfile.ZipFile(epub_path) as archive:
            names = archive.namelist()
            chapter = archive.read("OEBPS/text/0001-scp-001.xhtml").decode("utf-8")
            opf = archive.read("OEBPS/content.opf").decode("utf-8")
            normalized_name = next(
                name
                for name in names
                if name.startswith("OEBPS/assets/") and name.endswith(".png")
            )
            assert archive.read(normalized_name).startswith(b"\x89PNG\r\n\x1a\n")
        assert "photo.webp" not in "\n".join(names)
        assert "missing.png" not in "\n".join(names)
        assert "../assets/photo.webp" not in chapter
        assert "../assets/missing.png" not in chapter
        assert "缺失图" in chapter
        assert 'media-type="image/png"' in opf
        azw3_path.parent.mkdir(parents=True, exist_ok=True)
        azw3_path.write_bytes(b"azw3")
        return azw3_path

    output_path = build_volume(
        config,
        "001-099",
        fetcher=fetcher,
        kindle=True,
        kindle_converter=fake_converter,
    )

    assert conversion_calls == [
        (output_path, config.output_dir / "azw3" / "test-volume-Kindle.azw3")
    ]
    report = json.loads(
        (config.output_dir / "reports" / "test-volume-Kindle-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["missing_assets"] == [invalid_url]
    assert report["asset_urls"] == [webp_url, invalid_url]
    assert list((config.processed_dir / "test-volume" / "kindle-assets").glob("*.png"))


def test_build_volume_default_keeps_unvalidated_asset_and_missing_report_unchanged(
    tmp_path: Path,
):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    fake_url = f"{BASE_URL}/images/fake.png"
    fake_bytes = b"<!doctype html><title>404 Not Found</title>"
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {"scp-001": simple_page("SCP-001", '<img src="/images/fake.png"/>')},
        assets={fake_url: ("fake.png", fake_bytes, "text/html")},
    )

    output_path = build_volume(config, "001-099", fetcher=fetcher)

    with zipfile.ZipFile(output_path) as archive:
        assert archive.read("OEBPS/assets/fake.png") == fake_bytes
        assert "../assets/fake.png" in archive.read(
            "OEBPS/text/0001-scp-001.xhtml"
        ).decode("utf-8")
    report = json.loads(
        (config.output_dir / "reports" / "test-volume-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["missing_assets"] == []
    assert report["asset_urls"] == [fake_url]
