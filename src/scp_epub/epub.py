from __future__ import annotations

import json
import mimetypes
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Iterable

from scp_epub.assets import AssetRef
from scp_epub.models import ProcessedPage
from scp_epub.urls import safe_filename

MIMETYPE = "application/epub+zip"


@dataclass(frozen=True)
class _ChapterEntry:
    id: str
    href: str
    archive_path: str
    page: ProcessedPage
    has_remote_resources: bool = False


@dataclass(frozen=True)
class _AssetEntry:
    id: str
    href: str
    archive_path: str
    path: Path
    media_type: str


@dataclass(frozen=True)
class _NavNode:
    entry: _ChapterEntry
    children: tuple["_NavNode", ...] = ()


def write_epub(
    pages: list[ProcessedPage],
    output_path: Path,
    *,
    title: str,
    language: str,
    creator: str,
    identifier: str | None = None,
    modified: datetime | str | None = None,
    assets: list[AssetRef] | tuple[AssetRef, ...] = (),
    remote_resource_page_slugs: set[str] | tuple[str, ...] | list[str] = (),
) -> Path:
    ordered_pages = _ordered_pages(pages)
    if not ordered_pages:
        raise ValueError("write_epub requires at least one page")

    book_identifier = identifier or f"urn:uuid:{uuid.uuid4()}"
    modified_value = _format_modified(modified)
    remote_slugs = set(remote_resource_page_slugs)
    page_entries = [
        _chapter_entry(page, has_remote_resources=page.entry.slug in remote_slugs)
        for page in ordered_pages
    ]
    asset_entries = _asset_entries(assets)

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
                asset_entries=asset_entries,
            ),
        )
        archive.writestr("OEBPS/nav.xhtml", _nav_xhtml(title=title, language=language, page_entries=page_entries))
        archive.writestr("OEBPS/toc.ncx", _toc_ncx(title=title, identifier=book_identifier, page_entries=page_entries))
        for entry in page_entries:
            archive.writestr(entry.archive_path, _page_xhtml(entry.page, language=language))
        for entry in asset_entries:
            archive.write(entry.path, entry.archive_path)

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


def _chapter_entry(page: ProcessedPage, *, has_remote_resources: bool = False) -> _ChapterEntry:
    filename = f"{page.entry.order:04d}-{safe_filename(page.entry.slug)}.xhtml"
    return _ChapterEntry(
        id=f"page-{page.entry.order:04d}",
        href=f"text/{filename}",
        archive_path=f"OEBPS/text/{filename}",
        page=page,
        has_remote_resources=has_remote_resources,
    )


def _asset_entries(assets: list[AssetRef] | tuple[AssetRef, ...]) -> list[_AssetEntry]:
    entries: list[_AssetEntry] = []
    seen_hrefs: set[str] = set()
    for index, asset in enumerate(assets, start=1):
        if asset.href in seen_hrefs:
            continue
        seen_hrefs.add(asset.href)
        href = asset.href.replace("\\", "/")
        entries.append(
            _AssetEntry(
                id=f"asset-{index:04d}",
                href=href,
                archive_path=f"OEBPS/{href}",
                path=asset.path,
                media_type=_asset_media_type(asset),
            )
        )
    return entries


def _asset_media_type(asset: AssetRef) -> str:
    content_type = asset.content_type.split(";", 1)[0].strip().lower()
    if content_type:
        return content_type
    guessed, _encoding = mimetypes.guess_type(asset.path.name)
    return guessed or "application/octet-stream"


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
    asset_entries: list[_AssetEntry],
) -> str:
    page_manifest_items = "\n".join(_page_manifest_item(entry) for entry in page_entries)
    asset_manifest_items = "\n".join(
        f'    <item id="{entry.id}" href="{escape(entry.href, quote=True)}" '
        f'media-type="{escape(entry.media_type, quote=True)}"/>'
        for entry in asset_entries
    )
    manifest_items = "\n".join(value for value in (page_manifest_items, asset_manifest_items) if value)
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
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
{manifest_items}
  </manifest>
  <spine toc="ncx">
{spine_items}
  </spine>
</package>
"""


def _page_manifest_item(entry: _ChapterEntry) -> str:
    properties = ' properties="remote-resources"' if entry.has_remote_resources else ""
    return (
        f'    <item id="{entry.id}" href="{escape(entry.href, quote=True)}" '
        f'media-type="application/xhtml+xml"{properties}/>'
    )


def _nav_xhtml(*, title: str, language: str, page_entries: list[_ChapterEntry]) -> str:
    nav_items = _nav_items(_nav_tree(page_entries))
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


def _nav_tree(page_entries: list[_ChapterEntry]) -> list[_NavNode]:
    entries_by_slug = {entry.page.entry.slug: entry for entry in page_entries}
    children_by_parent: dict[str, list[_ChapterEntry]] = {}
    roots: list[_ChapterEntry] = []

    for entry in page_entries:
        parent_slug = entry.page.entry.parent_slug
        if parent_slug and parent_slug in entries_by_slug:
            children_by_parent.setdefault(parent_slug, []).append(entry)
        else:
            roots.append(entry)

    visited: set[str] = set()
    return [
        node
        for entry in roots
        if (node := _nav_node(entry, children_by_parent, visited)) is not None
    ]


def _nav_node(
    entry: _ChapterEntry,
    children_by_parent: dict[str, list[_ChapterEntry]],
    visited: set[str],
) -> _NavNode | None:
    slug = entry.page.entry.slug
    if slug in visited:
        return None
    visited.add(slug)

    children = tuple(
        node
        for child in children_by_parent.get(slug, [])
        if (node := _nav_node(child, children_by_parent, visited)) is not None
    )
    return _NavNode(entry=entry, children=children)


def _nav_items(nodes: list[_NavNode] | tuple[_NavNode, ...]) -> str:
    return "\n".join(_nav_item(node, indent=8) for node in nodes)


def _nav_item(node: _NavNode, *, indent: int) -> str:
    entry = node.entry
    level = max(entry.page.entry.level, 1)
    padding = " " * indent
    link = (
        f'{padding}<li class="level-{level}"><a href="{escape(entry.href, quote=True)}">'
        f"{escape(entry.page.entry.title)}</a>"
    )
    child_items = [_nav_item(child, indent=indent + 4) for child in node.children]
    if not child_items:
        return f"{link}</li>"

    child_padding = " " * (indent + 2)
    return "\n".join(
        [
            link,
            f"{child_padding}<ol>",
            *child_items,
            f"{child_padding}</ol>",
            f"{padding}</li>",
        ]
    )


def _toc_ncx(*, title: str, identifier: str, page_entries: list[_ChapterEntry]) -> str:
    nodes = _nav_tree(page_entries)
    play_order = [0]
    nav_points = "\n".join(_ncx_nav_point(node, play_order=play_order, indent=4) for node in nodes)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{escape(identifier, quote=True)}"/>
    <meta name="dtb:depth" content="{_nav_depth(nodes)}"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{escape(title)}</text></docTitle>
  <navMap>
{nav_points}
  </navMap>
</ncx>
"""


def _ncx_nav_point(node: _NavNode, *, play_order: list[int], indent: int) -> str:
    play_order[0] += 1
    order = play_order[0]
    padding = " " * indent
    child_items = [
        _ncx_nav_point(child, play_order=play_order, indent=indent + 2)
        for child in node.children
    ]
    lines = [
        f'{padding}<navPoint id="navPoint-{order:04d}" playOrder="{order}">',
        f"{padding}  <navLabel><text>{escape(node.entry.page.entry.title)}</text></navLabel>",
        f'{padding}  <content src="{escape(node.entry.href, quote=True)}"/>',
    ]
    lines.extend(child_items)
    lines.append(f"{padding}</navPoint>")
    return "\n".join(lines)


def _nav_depth(nodes: list[_NavNode] | tuple[_NavNode, ...]) -> int:
    if not nodes:
        return 0
    return max(1 + _nav_depth(node.children) for node in nodes)


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
