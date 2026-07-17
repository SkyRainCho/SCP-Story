from __future__ import annotations

from typing import Protocol

from .models import AppConfig, FetchResult, InlineDocumentSpec, PageRef


class PageFetcher(Protocol):
    def fetch_page(self, slug: str, url: str, *, force: bool = False) -> FetchResult:
        ...


def fetch_inline_document_results(
    config: AppConfig,
    manifest: list[PageRef],
    fetcher: PageFetcher,
    *,
    force: bool,
) -> dict[str, tuple[tuple[InlineDocumentSpec, FetchResult], ...]]:
    """Fetch configured companion documents for owners included in this build."""
    fetched_by_url: dict[str, FetchResult] = {}
    results_by_owner: dict[str, tuple[tuple[InlineDocumentSpec, FetchResult], ...]] = {}

    for entry in manifest:
        override = config.page_overrides.get(entry.slug)
        if override is None or not override.inline_documents:
            continue

        owner_results: list[tuple[InlineDocumentSpec, FetchResult]] = []
        for document in override.inline_documents:
            result = fetched_by_url.get(document.url)
            if result is None:
                result = fetcher.fetch_page(document.slug, document.url, force=force)
                fetched_by_url[document.url] = result
            owner_results.append((document, result))
        results_by_owner[entry.slug] = tuple(owner_results)

    return results_by_owner


def inline_document_urls(config: AppConfig) -> dict[str, set[str]]:
    return {
        slug: {document.url for document in override.inline_documents}
        for slug, override in config.page_overrides.items()
        if override.inline_documents
    }
