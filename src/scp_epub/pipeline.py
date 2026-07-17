from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from html import escape
from typing import Protocol
from urllib.parse import urlparse

from .appendix import (
    APPENDIX_TAB_ROLE,
    appendix_group_html,
    extract_facility_children,
    extract_tab_children,
)
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
from .inline_documents import fetch_inline_document_results, inline_document_urls
from .linked_appendices import (
    LINKED_APPENDIX_ROLE,
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
from .models import AppConfig, FetchResult, InlineDocumentSpec, PageRef, ProcessedPage, VolumeSpec
from .transform import PageTransformOptions, insert_inline_fragments, transform_page
from .urls import safe_filename, slug_from_url


APPENDIX_GROUP_ROLE = "appendix-group"


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
    appendix_fetch_results: dict[tuple[str, str], FetchResult] | None = None,
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
    front_matter_entries = [_configured_page_to_page_ref(page) for page in config.front_matter_pages]
    appendix_entries = _featured_appendix_entries(
        config,
        active_fetcher,
        force=force,
        fetch_results=appendix_fetch_results,
    )
    manifest = [
        _with_page_order(entry, order)
        for order, entry in enumerate(
            [*front_matter_entries, *entries, *appendix_entries],
            start=1,
        )
    ]
    write_manifest(manifest, manifest_path_for_volume(config, volume))
    return manifest


def fetch_manifest_pages(
    config: AppConfig,
    manifest: list[PageRef],
    *,
    fetcher: PageFetcher | None = None,
    force: bool = False,
    appendix_fetch_results: dict[tuple[str, str], FetchResult] | None = None,
) -> list[FetchResult]:
    return _fetch_manifest_entries(
        config,
        manifest,
        fetcher or make_fetcher(config),
        force=force,
        appendix_fetch_results=appendix_fetch_results,
    )


def build_volume(
    config: AppConfig,
    volume_key: str,
    *,
    fetcher: PageFetcher | None = None,
    force: bool = False,
) -> Path:
    volume = volume_for_key(config, volume_key)
    active_fetcher = fetcher or make_fetcher(config)
    manifest, appendix_fetch_results = _load_or_build_manifest_for_build(
        config,
        volume_key,
        active_fetcher,
        force=force,
    )
    available_manifest, fetch_results, missing_pages = fetch_build_pages(
        config,
        manifest,
        active_fetcher,
        force=force,
        appendix_fetch_results=appendix_fetch_results,
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
    inline_document_results = fetch_inline_document_results(
        config,
        available_manifest,
        active_fetcher,
        force=force,
    )
    processed_pages = _process_pages(
        config,
        volume,
        available_manifest,
        fetch_results,
        inline_document_results,
    )
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
    documents = _exclude_configured_inline_documents(
        config,
        scan_linked_appendices_from_fetch_results(
        manifest,
        fetch_results,
        config.base_url,
        ),
    )
    documents = _merge_linked_appendix_documents(
        manifest,
        documents,
        _configured_linked_appendix_documents(config, manifest),
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
    manifest = _load_or_build_manifest(
        config,
        volume_key,
        None,
        force=False,
        repair_legacy_appendix_tabs=False,
    )
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
    config: AppConfig,
    manifest: list[PageRef],
    fetcher: PageFetcher,
    *,
    force: bool = False,
    appendix_fetch_results: dict[tuple[str, str], FetchResult] | None = None,
) -> tuple[list[PageRef], list[FetchResult], list[dict[str, str]]]:
    available_manifest: list[PageRef] = []
    fetch_results: list[FetchResult] = []
    missing_pages: list[dict[str, str]] = []

    tab_fetch_results: dict[tuple[str, str], FetchResult] = {}
    cache = CacheStore(config.cache_dir)

    for entry in manifest:
        try:
            if entry.role == APPENDIX_GROUP_ROLE:
                result = _write_appendix_group_fetch_result(cache, entry)
            elif entry.role == APPENDIX_TAB_ROLE:
                source_key = _tab_source_key(config, entry)
                result = tab_fetch_results.get(source_key)
                if result is None:
                    result = (appendix_fetch_results or {}).get(source_key)
                    if result is None:
                        result = fetcher.fetch_page(*source_key, force=force)
                    tab_fetch_results[source_key] = result
            else:
                source_key = (entry.slug, entry.url)
                if _is_configured_appendix_page_entry(config, entry):
                    result = (appendix_fetch_results or {}).get(source_key)
                else:
                    result = None
                if result is None:
                    result = fetcher.fetch_page(*source_key, force=force)
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


def _fetch_manifest_entries(
    config: AppConfig,
    manifest: list[PageRef],
    fetcher: PageFetcher,
    *,
    force: bool,
    appendix_fetch_results: dict[tuple[str, str], FetchResult] | None = None,
) -> list[FetchResult]:
    cache = CacheStore(config.cache_dir)
    tab_fetch_results: dict[tuple[str, str], FetchResult] = {}
    results: list[FetchResult] = []

    for entry in manifest:
        if entry.role == APPENDIX_GROUP_ROLE:
            results.append(_write_appendix_group_fetch_result(cache, entry))
            continue

        if entry.role == APPENDIX_TAB_ROLE:
            source_key = _tab_source_key(config, entry)
            result = tab_fetch_results.get(source_key)
            if result is None:
                result = (appendix_fetch_results or {}).get(source_key)
                if result is None:
                    result = fetcher.fetch_page(*source_key, force=force)
                tab_fetch_results[source_key] = result
        else:
            source_key = (entry.slug, entry.url)
            if _is_configured_appendix_page_entry(config, entry):
                result = (appendix_fetch_results or {}).get(source_key)
            else:
                result = None
            if result is None:
                result = fetcher.fetch_page(*source_key, force=force)
        results.append(result)

    return results


def _write_appendix_group_fetch_result(cache: CacheStore, entry: PageRef) -> FetchResult:
    path, metadata_path = cache.write_page(
        entry.slug,
        entry.url,
        appendix_group_html(entry),
        200,
        "text/html",
    )
    return FetchResult(
        url=entry.url,
        path=path,
        metadata_path=metadata_path,
        from_cache=False,
        status_code=200,
        content_type="text/html",
    )


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
        if force:
            active_fetcher = make_fetcher(config)
            manifest, appendix_fetch_results = _load_or_build_manifest_for_build(
                config,
                args.volume,
                active_fetcher,
                force=True,
            )
            results = fetch_manifest_pages(
                config,
                manifest,
                fetcher=active_fetcher,
                force=True,
                appendix_fetch_results=appendix_fetch_results,
            )
        else:
            manifest = _load_or_build_manifest(config, args.volume, None, force=False)
            results = fetch_manifest_pages(config, manifest)
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


def _featured_appendix_entries(
    config: AppConfig,
    fetcher: PageFetcher,
    *,
    force: bool,
    fetch_results: dict[tuple[str, str], FetchResult] | None = None,
) -> list[PageRef]:
    appendix = config.appendix
    if appendix is None:
        return []

    source = "featured-appendix"
    entries = [
        PageRef(
            title=appendix.title,
            url=f"{config.base_url.rstrip('/')}/{appendix.slug}",
            slug=appendix.slug,
            level=1,
            role=APPENDIX_GROUP_ROLE,
            source=source,
        )
    ]
    for section in appendix.sections:
        result = fetcher.fetch_page(section.slug, section.url, force=force)
        if fetch_results is not None:
            fetch_results[(section.slug, section.url)] = result
        source_entry = PageRef(
            title=section.title,
            url=section.url,
            slug=section.slug,
            level=2,
            role="appendix-section",
            parent_slug=appendix.slug,
            source=source,
        )
        group_slug = _appendix_group_slug(section.slug)
        entry = PageRef(
            title=section.title,
            url=section.url,
            slug=section.slug if section.mode == "page" else group_slug,
            level=2,
            role="appendix-section" if section.mode == "page" else APPENDIX_GROUP_ROLE,
            parent_slug=appendix.slug,
            source=source,
        )
        entries.append(entry)
        html = result.path.read_text(encoding="utf-8")
        if section.mode == "facility-links":
            entries.extend(
                _with_parent_slug(
                    extract_facility_children(source_entry, html, config.base_url),
                    entry.slug,
                )
            )
        elif section.mode == "tabs-as-pages":
            entries.extend(_with_parent_slug(extract_tab_children(source_entry, html), entry.slug))

    return entries


def _appendix_group_slug(source_slug: str) -> str:
    return f"{source_slug}--appendix-group"


def _with_parent_slug(entries: list[PageRef], parent_slug: str) -> list[PageRef]:
    return [
        PageRef(
            title=entry.title,
            url=entry.url,
            slug=entry.slug,
            level=entry.level,
            role=entry.role,
            parent_slug=parent_slug,
            source=entry.source,
            order=entry.order,
            children=entry.children,
            tab_title=entry.tab_title,
        )
        for entry in entries
    ]


def _tab_source_key(config: AppConfig, entry: PageRef) -> tuple[str, str]:
    appendix = config.appendix
    if appendix is not None:
        for section in appendix.sections:
            if _appendix_group_slug(section.slug) == entry.parent_slug:
                return section.slug, section.url
    return entry.parent_slug or entry.slug, entry.url


def _is_configured_appendix_page_entry(config: AppConfig, entry: PageRef) -> bool:
    if entry.role != "appendix-section" or entry.source != "featured-appendix":
        return False
    appendix = config.appendix
    return appendix is not None and any(
        section.mode == "page" and section.slug == entry.slug and section.url == entry.url
        for section in appendix.sections
    )


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


def _configured_page_to_page_ref(page: object) -> PageRef:
    return PageRef(
        title=page.title,
        url=page.url,
        slug=page.slug,
        level=1,
        role=page.role,
        source="front-matter",
    )


def _configured_linked_appendix_documents(
    config: AppConfig,
    manifest: list[PageRef],
) -> list[LinkedAppendixDocument]:
    entries_by_slug = {entry.slug: entry for entry in manifest}
    documents: list[LinkedAppendixDocument] = []
    for source_slug, links in config.explicit_linked_appendices.items():
        entry = entries_by_slug.get(source_slug)
        if entry is None or not links:
            continue
        documents.append(
            LinkedAppendixDocument(
                entry=entry,
                candidates=tuple(
                    LinkedAppendixCandidate(
                        title=link.title,
                        url=link.url,
                        slug=link.slug,
                        reason="configured-appendix",
                    )
                    for link in links
                ),
            )
        )
    return documents


def _merge_linked_appendix_documents(
    manifest: list[PageRef],
    scanned_documents: list[LinkedAppendixDocument],
    configured_documents: list[LinkedAppendixDocument],
) -> list[LinkedAppendixDocument]:
    candidates_by_source: dict[str, list[LinkedAppendixCandidate]] = {}
    seen_by_source: dict[str, set[str]] = {}
    entry_by_source: dict[str, PageRef] = {}

    for document in [*scanned_documents, *configured_documents]:
        source_slug = document.entry.slug
        entry_by_source[source_slug] = document.entry
        candidates = candidates_by_source.setdefault(source_slug, [])
        seen = seen_by_source.setdefault(source_slug, set())
        for candidate in document.candidates:
            if candidate.slug in seen:
                continue
            seen.add(candidate.slug)
            candidates.append(candidate)

    return [
        LinkedAppendixDocument(
            entry=entry_by_source[entry.slug],
            candidates=tuple(candidates_by_source[entry.slug]),
        )
        for entry in manifest
        if entry.slug in candidates_by_source
    ]


def _exclude_configured_inline_documents(
    config: AppConfig,
    documents: list[LinkedAppendixDocument],
) -> list[LinkedAppendixDocument]:
    urls_by_owner = inline_document_urls(config)
    filtered_documents: list[LinkedAppendixDocument] = []
    for document in documents:
        excluded_page_slugs = {
            slug_from_url(url)
            for url in urls_by_owner.get(document.entry.slug, set())
        }
        candidates = tuple(
            candidate
            for candidate in document.candidates
            if slug_from_url(candidate.url) not in excluded_page_slugs
        )
        if candidates:
            filtered_documents.append(
                LinkedAppendixDocument(entry=document.entry, candidates=candidates)
            )
    return filtered_documents


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
        tab_title=entry.tab_title,
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
    repair_legacy_appendix_tabs: bool = True,
) -> list[PageRef]:
    volume = volume_for_key(config, volume_key)
    manifest_path = manifest_path_for_volume(config, volume)
    if force or not manifest_path.exists():
        return build_manifest(config, volume_key, fetcher=fetcher, force=force)
    manifest = read_manifest(manifest_path)
    if repair_legacy_appendix_tabs and _cached_manifest_requires_appendix_tab_title_rebuild(
        config, manifest
    ):
        return build_manifest(config, volume_key, fetcher=fetcher, force=force)
    return manifest


def _load_or_build_manifest_for_build(
    config: AppConfig,
    volume_key: str,
    fetcher: PageFetcher,
    *,
    force: bool,
) -> tuple[list[PageRef], dict[tuple[str, str], FetchResult]]:
    volume = volume_for_key(config, volume_key)
    manifest_path = manifest_path_for_volume(config, volume)
    if not force and manifest_path.exists():
        manifest = read_manifest(manifest_path)
        if not (
            _cached_manifest_requires_appendix_tab_title_rebuild(config, manifest)
            or _cached_featured_manifest_requires_appendix_root_rebuild(config, manifest)
        ):
            return manifest, {}

    appendix_fetch_results: dict[tuple[str, str], FetchResult] = {}
    if config.index_mode == "featured-scp-archive":
        manifest = build_featured_manifest(
            config,
            volume_key,
            fetcher=fetcher,
            force=force,
            appendix_fetch_results=appendix_fetch_results,
        )
    else:
        manifest = build_manifest(config, volume_key, fetcher=fetcher, force=force)
    return manifest, appendix_fetch_results


def _cached_manifest_requires_appendix_tab_title_rebuild(
    config: AppConfig,
    manifest: list[PageRef],
) -> bool:
    return config.appendix is not None and any(
        entry.role == APPENDIX_TAB_ROLE and entry.tab_title is None for entry in manifest
    )


def _cached_featured_manifest_requires_appendix_root_rebuild(
    config: AppConfig,
    manifest: list[PageRef],
) -> bool:
    appendix = config.appendix
    return (
        config.index_mode == "featured-scp-archive"
        and appendix is not None
        and not any(entry.slug == appendix.slug for entry in manifest)
    )


def _process_pages(
    config: AppConfig,
    volume: VolumeSpec,
    manifest: list[PageRef],
    fetch_results: list[FetchResult],
    inline_document_results: dict[
        str, tuple[tuple[InlineDocumentSpec, FetchResult], ...]
    ] | None = None,
) -> list[ProcessedPage]:
    manifest_slugs = {entry.slug for entry in manifest}
    results_by_slug = {
        entry.slug: result
        for entry, result in zip(manifest, fetch_results, strict=True)
    }
    processed_pages: list[ProcessedPage] = []
    processed_dir = config.processed_dir / volume.output_slug
    processed_dir.mkdir(parents=True, exist_ok=True)
    configured_pages_by_slug = {page.slug: page for page in config.front_matter_pages}
    appendix_sections_by_slug = {
        section.slug: section for section in config.appendix.sections
    } if config.appendix is not None else {}

    for entry in manifest:
        result = results_by_slug[entry.slug]
        configured_page = configured_pages_by_slug.get(entry.slug)
        appendix_section = appendix_sections_by_slug.get(entry.slug)
        include_tab_titles = set(config.page_tab_includes.get(entry.slug, ()))
        unwrap_single_included_tab = bool(
            configured_page and configured_page.unwrap_single_included_tab
        )
        if entry.role == APPENDIX_TAB_ROLE:
            include_tab_titles = {entry.tab_title} if entry.tab_title else set()
            unwrap_single_included_tab = True
        elif appendix_section is not None:
            include_tab_titles = set(appendix_section.include_tabs)
            unwrap_single_included_tab = appendix_section.unwrap_single_tab
        page = transform_page(
            entry,
            result.path.read_text(encoding="utf-8"),
            entry.url,
            manifest_slugs,
            include_tab_titles=include_tab_titles,
            unwrap_single_included_tab=unwrap_single_included_tab,
            background_asset_url=(
                configured_page.epub_background_url if configured_page is not None else None
            ),
            page_options=_page_transform_options(config, entry),
        )
        inline_fragments: list[tuple[InlineDocumentSpec, ProcessedPage]] = []
        for document, inline_result in (inline_document_results or {}).get(entry.slug, ()):
            inline_entry = PageRef(
                title=document.title,
                url=document.url,
                slug=document.slug,
                level=entry.level,
                role=entry.role,
            )
            inline_fragments.append(
                (
                    document,
                    transform_page(
                        inline_entry,
                        inline_result.path.read_text(encoding="utf-8"),
                        inline_entry.url,
                        manifest_slugs,
                        page_options=_page_transform_options(config, inline_entry),
                    ),
                )
            )
        if inline_fragments:
            page = insert_inline_fragments(page, fragments=inline_fragments)
        processed_pages.append(page)
        _write_processed_page(processed_dir, page)

    return processed_pages


def _page_transform_options(config: AppConfig, entry: PageRef) -> PageTransformOptions:
    override = config.page_overrides.get(entry.slug)
    inherited_terminal_navigation = (
        entry.role == LINKED_APPENDIX_ROLE
        and entry.parent_slug == linked_appendix_group_slug("scp-5109")
        and config.page_overrides.get("scp-5109", None) is not None
        and config.page_overrides["scp-5109"].remove_terminal_navigation
    )
    return PageTransformOptions(
        remove_terminal_navigation=(
            inherited_terminal_navigation
            or bool(override and override.remove_terminal_navigation)
        ),
        remove_leading_metadata=bool(override and override.remove_leading_metadata),
        remove_adult_content_warning=bool(override and override.remove_adult_content_warning),
        remove_author_work_list=bool(override and override.remove_author_work_list),
        layout_profile=override.layout_profile if override is not None else None,
    )


def _write_processed_page(processed_dir: Path, page: ProcessedPage) -> Path:
    path = processed_dir / f"{page.entry.order:04d}-{safe_filename(page.entry.slug)}.xhtml"
    path.write_text(page.xhtml + "\n", encoding="utf-8")
    return path
