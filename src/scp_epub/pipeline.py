from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from html import escape
from typing import Protocol
from urllib.parse import urlparse

from .assets import localize_assets, remote_resource_page_slugs
from .cache import CacheStore
from .config import load_config
from .epub import write_build_report, write_epub
from .fetcher import Fetcher
from .indexer import (
    parse_featured_scp_archive,
    parse_scp001_proposals,
    parse_series_index,
    parse_tales_index,
)
from .linked_appendices import (
    LINKED_APPENDIX_GROUP_ROLE,
    LinkedAppendixCandidate,
    LinkedAppendixDocument,
    expand_manifest_with_linked_appendices,
    linked_appendix_group_slug,
    scan_linked_appendices,
    scan_linked_appendices_from_fetch_results,
    write_linked_appendix_report,
)
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
    if config.index_mode == "featured-scp-archive":
        return build_featured_manifest(config, volume_key, fetcher=fetcher, force=force)

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


def build_featured_manifest(
    config: AppConfig,
    volume_key: str,
    *,
    fetcher: PageFetcher | None = None,
    force: bool = False,
) -> list[PageRef]:
    volume = volume_for_key(config, volume_key)
    active_fetcher = fetcher or make_fetcher(config)
    initial_url = config.featured_archive_url or config.index_url
    archive_base_url = _url_origin(initial_url)
    title_by_slug = _manifest_titles_by_slug(config)
    title_by_slug.update(
        {
            slug: title
            for slug, title in _featured_title_index_titles(
                config,
                active_fetcher,
                force=force,
            ).items()
            if slug not in title_by_slug
        }
    )

    entries: list[PageRef] = []
    seen_entry_slugs: set[str] = set()
    seen_archive_urls: set[str] = set()
    archive_urls = [initial_url]

    while archive_urls:
        archive_url = archive_urls.pop(0)
        if archive_url in seen_archive_urls:
            continue
        seen_archive_urls.add(archive_url)

        result = active_fetcher.fetch_page(
            slug_from_url(archive_url),
            archive_url,
            force=force,
        )
        parsed = parse_featured_scp_archive(
            result.path.read_text(encoding="utf-8"),
            archive_base_url=archive_base_url,
            target_base_url=config.base_url,
        )

        for entry in parsed.entries:
            if entry.slug in seen_entry_slugs:
                continue
            seen_entry_slugs.add(entry.slug)
            entries.append(_with_featured_title(entry, title_by_slug.get(entry.slug)))

        for next_archive_url in parsed.archive_urls:
            if next_archive_url not in seen_archive_urls and next_archive_url not in archive_urls:
                archive_urls.append(next_archive_url)

    entries.sort(key=lambda entry: (entry.order <= 0, entry.order))
    manifest = [_with_page_order(entry, order) for order, entry in enumerate(entries, start=1)]
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
    available_manifest, fetch_results, linked_appendix_documents, linked_missing_pages = (
        (
            include_linked_appendices(
                config,
                available_manifest,
                fetch_results,
                active_fetcher,
                force=force,
            )
            if config.include_linked_appendices
            else (available_manifest, fetch_results, [], [])
        )
    )
    missing_pages.extend(linked_missing_pages)
    if linked_appendix_documents:
        write_linked_appendix_report(
            linked_appendix_documents,
            config.output_dir / "reports" / f"{volume.output_slug}-linked-appendices.json",
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
        cover_image_path=cover_image_path_for_volume(config, volume),
    )
    write_build_report(
        config.output_dir / "reports" / f"{volume.output_slug}-report.json",
        pages=processed_pages,
        output_path=output_path,
        missing_assets=missing_assets,
        missing_pages=missing_pages,
    )
    return output_path


def include_linked_appendices(
    config: AppConfig,
    manifest: list[PageRef],
    fetch_results: list[FetchResult],
    fetcher: PageFetcher,
    *,
    force: bool = False,
) -> tuple[list[PageRef], list[FetchResult], list[LinkedAppendixDocument], list[dict[str, str]]]:
    documents = scan_linked_appendices_from_fetch_results(
        manifest,
        fetch_results,
        config.base_url,
    )
    if not documents:
        return manifest, fetch_results, [], []

    manifest_slugs = {entry.slug for entry in manifest}
    fetched_results_by_slug = {
        entry.slug: result
        for entry, result in zip(manifest, fetch_results, strict=True)
    }
    successful_documents: list[LinkedAppendixDocument] = []
    missing_pages: list[dict[str, str]] = []

    for document in documents:
        successful_candidates: list[LinkedAppendixCandidate] = []
        for candidate in document.candidates:
            if candidate.slug in manifest_slugs or candidate.slug in fetched_results_by_slug:
                continue
            try:
                fetched_results_by_slug[candidate.slug] = fetcher.fetch_page(
                    candidate.slug,
                    candidate.url,
                    force=force,
                )
            except Exception as exc:
                missing_pages.append(
                    {
                        "slug": candidate.slug,
                        "title": candidate.title,
                        "url": candidate.url,
                        "reason": str(exc),
                    }
                )
                continue
            successful_candidates.append(candidate)

        if successful_candidates:
            successful_documents.append(
                LinkedAppendixDocument(
                    entry=document.entry,
                    candidates=tuple(successful_candidates),
                )
            )

    if not successful_documents:
        return manifest, fetch_results, [], missing_pages

    expanded_manifest = expand_manifest_with_linked_appendices(
        manifest,
        successful_documents,
    )
    successful_documents_by_group_slug = {
        linked_appendix_group_slug(document.entry.slug): document
        for document in successful_documents
    }
    ordered_results: list[FetchResult] = []
    cache = CacheStore(config.cache_dir)

    for entry in expanded_manifest:
        if entry.role == LINKED_APPENDIX_GROUP_ROLE:
            result = _write_linked_appendix_group_fetch_result(
                cache,
                entry,
                successful_documents_by_group_slug[entry.slug],
            )
            ordered_results.append(result)
            continue
        ordered_results.append(fetched_results_by_slug[entry.slug])

    return expanded_manifest, ordered_results, successful_documents, missing_pages


def scan_linked_appendices_for_volume(
    config: AppConfig,
    volume_key: str,
    *,
    force: bool = False,
) -> Path:
    volume = volume_for_key(config, volume_key)
    manifest = _load_or_build_manifest(config, volume_key, None, force=force)
    documents = scan_linked_appendices(
        manifest,
        CacheStore(config.cache_dir),
        config.base_url,
    )
    return write_linked_appendix_report(
        documents,
        config.output_dir / "reports" / f"{volume.output_slug}-linked-appendices.json",
    )


def _write_linked_appendix_group_fetch_result(
    cache: CacheStore,
    entry: PageRef,
    document: LinkedAppendixDocument,
) -> FetchResult:
    html = _linked_appendix_group_html(document)
    path, metadata_path = cache.write_page(entry.slug, entry.url, html, 200, "text/html")
    return FetchResult(
        url=entry.url,
        path=path,
        metadata_path=metadata_path,
        from_cache=False,
        status_code=200,
        content_type="text/html",
    )


def _linked_appendix_group_html(document: LinkedAppendixDocument) -> str:
    items = "\n".join(
        (
            f'      <li><a href="{escape(candidate.url, quote=True)}">'
            f"{escape(candidate.title or candidate.slug)}</a></li>"
        )
        for candidate in document.candidates
    )
    return f"""<html>
  <body>
    <div id="page-content">
      <h1>原文附属文档</h1>
      <p>以下页面来自《{escape(document.entry.title)}》正文中的高置信附属文档链接。</p>
      <ul>
{items}
      </ul>
    </div>
  </body>
</html>"""


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

    if command == "scan-linked-appendices":
        report_path = scan_linked_appendices_for_volume(
            config,
            args.volume,
            force=force,
        )
        print(f"Wrote {report_path}")
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


def cover_image_path_for_volume(config: AppConfig, volume: VolumeSpec | str) -> Path | None:
    volume_spec = volume_for_key(config, volume) if isinstance(volume, str) else volume
    cover_path = config.workspace / "cover" / f"{volume_spec.output_slug}-cover.png"
    return cover_path if cover_path.exists() else None


def _manifest_titles_by_slug(config: AppConfig) -> dict[str, str]:
    titles: dict[str, str] = {}
    if not config.manifest_dir.exists():
        return titles

    current_paths = {
        manifest_path_for_volume(config, volume).resolve()
        for volume in config.volumes.values()
    }
    for path in sorted(config.manifest_dir.glob("*.json")):
        if path.resolve() in current_paths:
            continue
        try:
            entries = read_manifest(path)
        except Exception:
            continue
        for entry in entries:
            if entry.role == "scp" and entry.slug not in titles:
                titles[entry.slug] = entry.title
    return titles


def _featured_title_index_titles(
    config: AppConfig,
    fetcher: PageFetcher,
    *,
    force: bool,
) -> dict[str, str]:
    titles: dict[str, str] = {}
    for path in config.featured_title_index_paths:
        url = f"{config.base_url.rstrip('/')}/{path.lstrip('/')}"
        result = fetcher.fetch_page(slug_from_url(url), url, force=force)
        for entry in parse_series_index(
            result.path.read_text(encoding="utf-8"),
            config.base_url,
            1,
            9999,
        ):
            titles.setdefault(entry.slug, entry.title)
    return titles


def _with_featured_title(entry: PageRef, title: str | None) -> PageRef:
    if not title:
        return entry
    return PageRef(
        title=title,
        url=entry.url,
        slug=entry.slug,
        level=entry.level,
        role=entry.role,
        parent_slug=entry.parent_slug,
        source=entry.source,
        order=entry.order,
        children=entry.children,
    )


def _with_page_order(entry: PageRef, order: int) -> PageRef:
    return PageRef(
        title=entry.title,
        url=entry.url,
        slug=entry.slug,
        level=entry.level,
        role=entry.role,
        parent_slug=entry.parent_slug,
        source=entry.source,
        order=order,
        children=entry.children,
    )


def _url_origin(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"featured archive URL must be absolute: {url}")
    return f"{parsed.scheme}://{parsed.netloc}"


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
