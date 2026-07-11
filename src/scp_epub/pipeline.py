from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Protocol

from .assets import localize_assets, remote_resource_page_slugs
from .cache import CacheStore
from .config import load_config
from .epub import write_build_report, write_epub
from .fetcher import Fetcher
from .indexer import parse_scp001_proposals, parse_series_index, parse_tales_index
from .manifest import read_manifest, merge_manifest, supplement_missing_scp_entries, write_manifest
from .models import AppConfig, FetchResult, PageRef, ProcessedPage, VolumeSpec
from .transform import transform_page
from .urls import safe_filename, slug_from_url


class PageFetcher(Protocol):
    def fetch_page(self, slug: str, url: str, *, force: bool = False) -> FetchResult:
        ...


def build_manifest(
    config: AppConfig,
    volume_key: str,
    *,
    fetcher: PageFetcher | None = None,
    force: bool = False,
) -> list[PageRef]:
    volume = volume_for_key(config, volume_key)
    active_fetcher = fetcher or make_fetcher(config)

    index_result = active_fetcher.fetch_page(
        slug_from_url(config.index_url),
        config.index_url,
        force=force,
    )
    index_entries = parse_tales_index(
        index_result.path.read_text(encoding="utf-8"),
        config.base_url,
        volume.start,
        volume.end,
    )

    series_index_result = active_fetcher.fetch_page(
        slug_from_url(config.series_index_url),
        config.series_index_url,
        force=force,
    )
    series_entries = parse_series_index(
        series_index_result.path.read_text(encoding="utf-8"),
        config.base_url,
        volume.start,
        volume.end,
    )
    index_entries = supplement_missing_scp_entries(index_entries, series_entries)

    scp001_proposals: list[PageRef] = []
    if config.include_scp001_proposals and volume.start <= 1 <= volume.end:
        scp001_result = active_fetcher.fetch_page(
            slug_from_url(config.scp001_url),
            config.scp001_url,
            force=force,
        )
        scp001_proposals = parse_scp001_proposals(
            scp001_result.path.read_text(encoding="utf-8"),
            config.base_url,
        )

    manifest = merge_manifest(index_entries, scp001_proposals)
    write_manifest(manifest, manifest_path_for_volume(config, volume))
    return manifest


def fetch_manifest_pages(
    config: AppConfig,
    manifest: list[PageRef],
    *,
    fetcher: PageFetcher | None = None,
    force: bool = False,
) -> list[FetchResult]:
    active_fetcher = fetcher or make_fetcher(config)
    return [
        active_fetcher.fetch_page(entry.slug, entry.url, force=force)
        for entry in manifest
    ]


def build_volume(
    config: AppConfig,
    volume_key: str,
    *,
    fetcher: PageFetcher | None = None,
    force: bool = False,
) -> Path:
    volume = volume_for_key(config, volume_key)
    active_fetcher = fetcher or make_fetcher(config)
    manifest = _load_or_build_manifest(
        config,
        volume_key,
        active_fetcher,
        force=force,
    )
    available_manifest, fetch_results, missing_pages = fetch_build_pages(
        manifest,
        active_fetcher,
        force=force,
    )
    processed_pages = _process_pages(config, volume, available_manifest, fetch_results)
    localized_pages, localized_assets, missing_assets = localize_assets(
        processed_pages,
        active_fetcher,
        force=force,
    )
    remote_slugs = remote_resource_page_slugs(localized_pages, missing_assets)

    output_path = config.output_dir / "epub" / f"{volume.output_slug}.epub"
    write_epub(
        localized_pages,
        output_path,
        title=volume.title,
        language=config.language,
        creator=config.creator,
        identifier=f"urn:{config.series_id}:{volume.output_slug}",
        assets=localized_assets,
        remote_resource_page_slugs=remote_slugs,
    )
    write_build_report(
        config.output_dir / "reports" / f"{volume.output_slug}-report.json",
        pages=processed_pages,
        output_path=output_path,
        missing_assets=missing_assets,
        missing_pages=missing_pages,
    )
    return output_path


def fetch_build_pages(
    manifest: list[PageRef],
    fetcher: PageFetcher,
    *,
    force: bool = False,
) -> tuple[list[PageRef], list[FetchResult], list[dict[str, str]]]:
    available_manifest: list[PageRef] = []
    fetch_results: list[FetchResult] = []
    missing_pages: list[dict[str, str]] = []

    for entry in manifest:
        try:
            result = fetcher.fetch_page(entry.slug, entry.url, force=force)
        except Exception as exc:
            missing_pages.append(
                {
                    "slug": entry.slug,
                    "title": entry.title,
                    "url": entry.url,
                    "reason": str(exc),
                }
            )
            continue
        available_manifest.append(entry)
        fetch_results.append(result)

    return available_manifest, fetch_results, missing_pages


def run_command(args: Namespace) -> None:
    config = load_config(args.config)
    command = args.command
    force = bool(getattr(args, "refresh", False))

    if command in {"index", "manifest"}:
        manifest = (
            build_manifest(config, args.volume, force=True)
            if force
            else build_manifest(config, args.volume)
        )
        print(f"Wrote {manifest_path_for_volume(config, args.volume)} ({len(manifest)} pages)")
        return

    if command == "fetch":
        manifest = _load_or_build_manifest(config, args.volume, None, force=force)
        results = (
            fetch_manifest_pages(config, manifest, force=True)
            if force
            else fetch_manifest_pages(config, manifest)
        )
        cache_hits = sum(1 for result in results if result.from_cache)
        print(f"Fetched {len(results)} pages ({cache_hits} from cache)")
        return

    if command == "build":
        output_path = (
            build_volume(config, args.volume, force=True)
            if force
            else build_volume(config, args.volume)
        )
        print(f"Wrote {output_path}")
        return

    if command == "clean":
        print("Clean is not implemented for generated files yet")
        return

    raise ValueError(f"Unknown command: {command}")


def make_fetcher(config: AppConfig) -> Fetcher:
    return Fetcher(
        CacheStore(config.cache_dir),
        retry_count=config.retry_count,
        asset_retry_count=config.asset_retry_count,
        request_delay_seconds=config.request_delay_seconds,
        request_timeout_seconds=config.request_timeout_seconds,
        asset_timeout_seconds=config.asset_timeout_seconds,
    )


def manifest_path_for_volume(config: AppConfig, volume: VolumeSpec | str) -> Path:
    volume_spec = volume_for_key(config, volume) if isinstance(volume, str) else volume
    return config.manifest_dir / f"{volume_spec.output_slug}.json"


def volume_for_key(config: AppConfig, volume_key: str) -> VolumeSpec:
    try:
        return config.volumes[volume_key]
    except KeyError:
        choices = ", ".join(sorted(config.volumes)) or "<none>"
        raise ValueError(f"Unknown volume {volume_key!r}; available volumes: {choices}") from None


def _load_or_build_manifest(
    config: AppConfig,
    volume_key: str,
    fetcher: PageFetcher | None,
    *,
    force: bool,
) -> list[PageRef]:
    volume = volume_for_key(config, volume_key)
    manifest_path = manifest_path_for_volume(config, volume)
    if force or not manifest_path.exists():
        return build_manifest(config, volume_key, fetcher=fetcher, force=force)
    return read_manifest(manifest_path)


def _process_pages(
    config: AppConfig,
    volume: VolumeSpec,
    manifest: list[PageRef],
    fetch_results: list[FetchResult],
) -> list[ProcessedPage]:
    manifest_slugs = {entry.slug for entry in manifest}
    results_by_slug = {
        entry.slug: result
        for entry, result in zip(manifest, fetch_results, strict=True)
    }
    processed_pages: list[ProcessedPage] = []
    processed_dir = config.processed_dir / volume.output_slug
    processed_dir.mkdir(parents=True, exist_ok=True)

    for entry in manifest:
        result = results_by_slug[entry.slug]
        page = transform_page(
            entry,
            result.path.read_text(encoding="utf-8"),
            entry.url,
            manifest_slugs,
        )
        processed_pages.append(page)
        _write_processed_page(processed_dir, page)

    return processed_pages


def _write_processed_page(processed_dir: Path, page: ProcessedPage) -> Path:
    path = processed_dir / f"{page.entry.order:04d}-{safe_filename(page.entry.slug)}.xhtml"
    path.write_text(page.xhtml + "\n", encoding="utf-8")
    return path
