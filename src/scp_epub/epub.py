from __future__ import annotations

import json
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Iterable

from scp_epub.models import ProcessedPage
from scp_epub.urls import safe_filename

MIMETYPE = "application/epub+zip"


@dataclass(frozen=True)
class _ChapterEntry:
    id: str
    href: str
    archive_path: str
    page: ProcessedPage


def write_epub(
    pages: list[ProcessedPage],
    output_path: Path,
    *,
    title: str,
    language: str,
    creator: str,
    identifier: str | None = None,
    modified: datetime | str | None = None,
) -> Path:
    ordered_pages = _ordered_pages(pages)
    if not ordered_pages:
        raise ValueError("write_epub requires at least one page")

    book_identifier = identifier or f"urn:uuid:{uuid.uuid4()}"
    modified_value = _format_modified(modified)
    page_entries = [_chapter_entry(page) for page in ordered_pages]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        mimetype_info = zipfile.ZipInfo("mimetype")
        mimetype_info.compress_type = zipfile.ZIP_STORED
        archive.writestr(mimetype_info, MIMETYPE)
        archive.writestr("META-INF/container.xml", _container_xml())
        archive.writestr(
            "OEBPS/content.opf",
            _content_opf(
                title=title,
                language=language,
                creator=creator,
                identifier=book_identifier,
                modified=modified_value,
                page_entries=page_entries,
            ),
        )
        archive.writestr("OEBPS/nav.xhtml", _nav_xhtml(title=title, language=language, page_entries=page_entries))
        for entry in page_entries:
            archive.writestr(entry.archive_path, _page_xhtml(entry.page, language=language))

    return output_path


def write_build_report(
    path: Path,
    *,
    pages: list[ProcessedPage],
    output_path: Path,
    external_links: list[str] | tuple[str, ...] = (),
    missing_assets: list[str] | tuple[str, ...] = (),
) -> Path:
    ordered_pages = _ordered_pages(pages)
    page_summaries = [{"slug": page.entry.slug, "title": page.entry.title} for page in ordered_pages]
    report = {
        "page_count": len(ordered_pages),
        "output_path": str(output_path),
        "pages": page_summaries,
        "slugs": [page.entry.slug for page in ordered_pages],
        "titles": [page.entry.title for page in ordered_pages],
        "asset_urls": _unique(value for page in ordered_pages for value in page.asset_urls),
        "internal_links": _unique(value for page in ordered_pages for value in page.internal_links),
        "external_links": _unique(
            [*(value for page in ordered_pages for value in page.external_links), *external_links]
        ),
        "missing_assets": list(missing_assets),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _ordered_pages(pages: list[ProcessedPage]) -> list[ProcessedPage]:
    return sorted(pages, key=lambda page: page.entry.order)


def _chapter_entry(page: ProcessedPage) -> _ChapterEntry:
    filename = f"{page.entry.order:04d}-{safe_filename(page.entry.slug)}.xhtml"
    return _ChapterEntry(
        id=f"page-{page.entry.order:04d}",
        href=f"text/{filename}",
        archive_path=f"OEBPS/text/{filename}",
        page=page,
    )


def _format_modified(modified: datetime | str | None) -> str:
    if isinstance(modified, str):
        return modified

    value = modified or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _container_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _content_opf(
    *,
    title: str,
    language: str,
    creator: str,
    identifier: str,
    modified: str,
    page_entries: list[_ChapterEntry],
) -> str:
    manifest_items = "\n".join(
        f'    <item id="{entry.id}" href="{escape(entry.href, quote=True)}" '
        'media-type="application/xhtml+xml"/>'
        for entry in page_entries
    )
    spine_items = "\n".join(f'    <itemref idref="{entry.id}"/>' for entry in page_entries)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="book-id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">
    <dc:title>{escape(title)}</dc:title>
    <dc:language>{escape(language)}</dc:language>
    <dc:creator>{escape(creator)}</dc:creator>
    <dc:identifier id="book-id">{escape(identifier)}</dc:identifier>
    <meta property="dcterms:modified">{escape(modified)}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
{manifest_items}
  </manifest>
  <spine>
{spine_items}
  </spine>
</package>
"""


def _nav_xhtml(*, title: str, language: str, page_entries: list[_ChapterEntry]) -> str:
    nav_items = "\n".join(_nav_item(entry) for entry in page_entries)
    escaped_language = escape(language, quote=True)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{escaped_language}" xml:lang="{escaped_language}">
  <head>
    <meta charset="utf-8"/>
    <title>{escape(title)}</title>
  </head>
  <body>
    <nav epub:type="toc" id="toc">
      <h1>{escape(title)}</h1>
      <ol>
{nav_items}
      </ol>
    </nav>
  </body>
</html>
"""


def _nav_item(entry: _ChapterEntry) -> str:
    level = max(entry.page.entry.level, 1)
    return (
        f'        <li class="level-{level}"><a href="{escape(entry.href, quote=True)}">'
        f"{escape(entry.page.entry.title)}</a></li>"
    )


def _page_xhtml(page: ProcessedPage, *, language: str) -> str:
    page_title = escape(page.entry.title)
    escaped_language = escape(language, quote=True)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="{escaped_language}" xml:lang="{escaped_language}">
  <head>
    <meta charset="utf-8"/>
    <title>{page_title}</title>
  </head>
  <body>
    <h1>{page_title}</h1>
{page.xhtml}
  </body>
</html>
"""


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values
