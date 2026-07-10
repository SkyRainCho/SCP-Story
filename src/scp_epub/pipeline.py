from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Protocol

from .cache import CacheStore
from .config import load_config
from .epub import write_build_report, write_epub
from .fetcher import Fetcher
from .indexer import parse_scp001_proposals, parse_tales_index
from .manifest import read_manifest, merge_manifest, write_manifest
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

    scp001_proposals: list[PageRef] = []
    if volume.start <= 1 <= volume.end:
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
    manifest_path = manifest_path_for_volume(config, volume)
    manifest = (
        read_manifest(manifest_path)
        if manifest_path.exists()
        else build_manifest(config, volume_key, fetcher=active_fetcher, force=force)
    )
    fetch_results = fetch_manifest_pages(
        config,
        manifest,
        fetcher=active_fetcher,
        force=force,
    )
    processed_pages = _process_pages(config, volume, manifest, fetch_results)

    output_path = config.output_dir / f"{volume.output_slug}.epub"
    write_epub(
        processed_pages,
        output_path,
        title=volume.title,
        language=config.language,
        creator=config.creator,
        identifier=f"urn:{config.series_id}:{volume.output_slug}",
    )
    write_build_report(
        config.output_dir / f"{volume.output_slug}-report.json",
        pages=processed_pages,
        output_path=output_path,
    )
    return output_path


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
        volume = volume_for_key(config, args.volume)
        manifest_path = manifest_path_for_volume(config, volume)
        manifest = (
            read_manifest(manifest_path)
            if manifest_path.exists()
            else (
                build_manifest(config, args.volume, force=True)
                if force
                else build_manifest(config, args.volume)
            )
        )
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
        request_delay_seconds=config.request_delay_seconds,
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
