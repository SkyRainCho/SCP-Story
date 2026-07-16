from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class VolumeSpec:
    key: str
    start: int
    end: int
    title: str
    output_slug: str


@dataclass(frozen=True)
class ConfiguredPage:
    title: str
    url: str
    slug: str
    role: str = "front-matter"


@dataclass(frozen=True)
class ConfiguredLink:
    title: str
    url: str
    slug: str


@dataclass(frozen=True)
class AppConfig:
    workspace: Path
    series_id: str
    title: str
    language: str
    creator: str
    base_url: str
    index_path: str
    series_index_path: str
    scp001_path: str
    cache_dir: Path
    manifest_dir: Path
    processed_dir: Path
    output_dir: Path
    request_delay_seconds: float
    request_timeout_seconds: float
    retry_count: int
    asset_timeout_seconds: float
    asset_retry_count: int
    include_scp001_proposals: bool
    volumes: dict[str, VolumeSpec]
    index_mode: str = "tales"
    featured_archive_url: str | None = None
    include_linked_appendices: bool = True
    featured_title_index_paths: tuple[str, ...] = ()
    front_matter_pages: tuple[ConfiguredPage, ...] = ()
    explicit_linked_appendices: dict[str, tuple[ConfiguredLink, ...]] = field(default_factory=dict)
    page_tab_includes: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def index_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.index_path.lstrip('/')}"

    @property
    def series_index_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.series_index_path.lstrip('/')}"

    @property
    def scp001_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.scp001_path.lstrip('/')}"


@dataclass(frozen=True)
class PageRef:
    title: str
    url: str
    slug: str
    level: int
    role: str
    parent_slug: str | None = None
    source: str = "index"
    order: int = 0
    children: tuple["PageRef", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FetchResult:
    url: str
    path: Path
    metadata_path: Path
    from_cache: bool
    status_code: int
    content_type: str


@dataclass(frozen=True)
class ProcessedPage:
    entry: PageRef
    xhtml: str
    asset_urls: tuple[str, ...]
    internal_links: tuple[str, ...]
    external_links: tuple[str, ...]
