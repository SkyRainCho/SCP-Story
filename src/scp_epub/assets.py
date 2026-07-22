from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, Sequence

from bs4 import BeautifulSoup, Tag
import resvg_py

from .models import FetchResult, ProcessedPage
from .transform import ASSET_ATTRIBUTES


EPUB_BACKGROUND_ASSET_ATTRIBUTE = "data-epub-background-url"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ANOMALY_DIAMOND_ICON_CENTERS = {
    "top": (80.0, 30.4),
    "right": (129.6, 80.0),
    "left": (30.4, 80.0),
    "bottom": (80.0, 129.6),
}
_ANOMALY_DIAMOND_ICON_SIZE = 52.8
_ANOMALY_DIAMOND_ICON_RADIUS = 24.9
_ANOMALY_DIAMOND_ICON_BORDER_WIDTH = 3.0


@dataclass(frozen=True)
class AssetRef:
    source_url: str
    path: Path
    href: str
    content_type: str


class AssetFetcher(Protocol):
    def fetch_asset(self, url: str, *, force: bool = False) -> FetchResult:
        ...


def localize_assets(
    pages: list[ProcessedPage],
    fetcher: AssetFetcher,
    *,
    force: bool = False,
) -> tuple[list[ProcessedPage], list[AssetRef], list[str]]:
    localized_by_url: dict[str, AssetRef] = {}
    missing_assets: list[str] = []
    seen_missing: set[str] = set()
    used_hrefs: set[str] = set()

    for url in _unique(value for page in pages for value in page.asset_urls):
        try:
            result = fetcher.fetch_asset(url, force=force)
        except Exception:
            if url not in seen_missing:
                seen_missing.add(url)
                missing_assets.append(url)
            continue

        href = _asset_href(url, result.path, used_hrefs)
        used_hrefs.add(href)
        localized_by_url[url] = AssetRef(
            source_url=url,
            path=result.path,
            href=href,
            content_type=result.content_type,
        )

    localized_pages = [_rewrite_page_assets(page, localized_by_url) for page in pages]
    return localized_pages, list(localized_by_url.values()), missing_assets


def materialize_anomaly_diamond_assets(
    pages: Sequence[ProcessedPage],
    assets: Sequence[AssetRef],
    output_dir: Path,
) -> tuple[list[ProcessedPage], list[AssetRef]]:
    """Render generated ACS diamond SVGs to reader-compatible PNG assets."""
    prepared_assets = list(assets)
    asset_by_href = {asset.href: asset for asset in assets}
    embedded_icon_uris: dict[str, str | None] = {}
    generated_by_digest: dict[str, AssetRef] = {}
    prepared_pages: list[ProcessedPage] = []

    for page in pages:
        soup = BeautifulSoup(f"<root>{page.xhtml}</root>", "html.parser")
        root = soup.find("root")
        if root is None:
            prepared_pages.append(page)
            continue
        changed = False
        for frame in list(root.select("svg.anomaly-diamond-frame")):
            diamond = frame.parent if isinstance(frame.parent, Tag) else None
            layout = (
                diamond.select_one("table.anomaly-diamond-layout")
                if diamond is not None
                else None
            )
            svg_markup = str(frame)
            svg_markup = re.sub(r"\bviewbox=", "viewBox=", svg_markup, count=1)
            if "xmlns=" not in svg_markup[: svg_markup.find(">")]:
                svg_markup = svg_markup.replace(
                    "<svg ",
                    '<svg xmlns="http://www.w3.org/2000/svg" ',
                    1,
                )
            icon_markup = _anomaly_diamond_icon_markup(
                frame,
                layout,
                asset_by_href,
                embedded_icon_uris,
            )
            if icon_markup:
                svg_markup = svg_markup.replace(
                    "</svg>",
                    f"{icon_markup}</svg>",
                    1,
                )
            digest = hashlib.sha256(svg_markup.encode("utf-8")).hexdigest()[:16]
            asset = generated_by_digest.get(digest)
            if asset is None:
                try:
                    rendered = resvg_py.svg_to_bytes(
                        svg_string=svg_markup,
                        width=640,
                        dpi=96,
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"Could not render generated anomaly diamond for {page.entry.slug}"
                    ) from exc
                if not rendered.startswith(_PNG_SIGNATURE):
                    raise RuntimeError(
                        f"Generated anomaly diamond is not PNG for {page.entry.slug}"
                    )
                filename = f"anomaly-diamond-{digest}.png"
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = output_dir / filename
                output_path.write_bytes(rendered)
                asset = AssetRef(
                    source_url=f"builtin://anomaly-diamond/{digest}.svg",
                    path=output_path,
                    href=f"assets/{filename}",
                    content_type="image/png",
                )
                generated_by_digest[digest] = asset
                prepared_assets.append(asset)
            image = soup.new_tag(
                "img",
                attrs={
                    "class": "anomaly-diamond-frame",
                    "src": f"../{asset.href}",
                    "alt": "",
                },
            )
            frame.replace_with(image)
            if layout is not None:
                layout.decompose()
            changed = True
        if not changed:
            prepared_pages.append(page)
            continue
        xhtml = "".join(str(child) for child in root.contents).strip()
        prepared_pages.append(replace(page, xhtml=xhtml))

    return prepared_pages, prepared_assets


def _anomaly_diamond_icon_markup(
    frame: Tag,
    layout: Tag | None,
    asset_by_href: dict[str, AssetRef],
    embedded_icon_uris: dict[str, str | None],
) -> str:
    if layout is None:
        return ""
    quadrant_colors = {
        str(polygon.get("data-quadrant")): str(polygon.get("fill"))
        for polygon in frame.select("polygon[data-quadrant]")
        if polygon.get("data-quadrant") and polygon.get("fill")
    }
    definitions: list[str] = []
    icons: list[str] = []
    half_size = _ANOMALY_DIAMOND_ICON_SIZE / 2

    for slot, (center_x, center_y) in _ANOMALY_DIAMOND_ICON_CENTERS.items():
        icon = layout.select_one(
            f"td.anomaly-diamond-{slot} img.anomaly-diamond-icon"
        )
        if icon is None:
            continue
        href = _local_epub_asset_href(icon.get("src"))
        if href is None:
            continue
        asset = asset_by_href.get(href)
        if asset is None:
            continue
        if href not in embedded_icon_uris:
            embedded_icon_uris[href] = _embedded_icon_data_uri(asset)
        data_uri = embedded_icon_uris[href]
        if data_uri is None:
            continue
        fill = quadrant_colors.get(slot, "#fcfcfc")
        clip_id = f"anomaly-diamond-{slot}-icon-clip"
        definitions.append(
            f'<clipPath id="{clip_id}"><circle cx="{center_x:g}" '
            f'cy="{center_y:g}" r="{_ANOMALY_DIAMOND_ICON_RADIUS:g}" />'
            "</clipPath>"
        )
        icons.append(
            f'<circle cx="{center_x:g}" cy="{center_y:g}" '
            f'r="{_ANOMALY_DIAMOND_ICON_RADIUS:g}" fill="{fill}" '
            'stroke="#0c0c0c" '
            f'stroke-width="{_ANOMALY_DIAMOND_ICON_BORDER_WIDTH:g}" />'
            f'<image href="{data_uri}" x="{center_x - half_size:g}" '
            f'y="{center_y - half_size:g}" '
            f'width="{_ANOMALY_DIAMOND_ICON_SIZE:g}" '
            f'height="{_ANOMALY_DIAMOND_ICON_SIZE:g}" '
            'preserveAspectRatio="xMidYMid meet" '
            f'clip-path="url(#{clip_id})" />'
        )
    if not icons:
        return ""
    return f"<defs>{''.join(definitions)}</defs>{''.join(icons)}"


def _local_epub_asset_href(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith("../"):
        return None
    return value[3:].replace("\\", "/")


def _embedded_icon_data_uri(asset: AssetRef) -> str | None:
    try:
        data = asset.path.read_bytes()
    except OSError:
        return None
    content_type = asset.content_type.split(";", 1)[0].strip().lower()
    if content_type == "image/svg+xml" or asset.path.suffix.casefold() == ".svg":
        try:
            rendered = resvg_py.svg_to_bytes(
                svg_string=data.decode("utf-8-sig"),
                width=256,
                dpi=96,
            )
        except Exception:
            return None
        if not rendered.startswith(_PNG_SIGNATURE):
            return None
        data = rendered
        content_type = "image/png"
    elif not content_type.startswith("image/"):
        return None
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def remote_resource_page_slugs(pages: list[ProcessedPage], missing_asset_urls: list[str] | tuple[str, ...]) -> set[str]:
    missing_urls = set(missing_asset_urls)
    if not missing_urls:
        return set()

    slugs: set[str] = set()
    for page in pages:
        if _page_references_any_asset(page, missing_urls):
            slugs.add(page.entry.slug)
    return slugs


def _asset_href(url: str, path: Path, used_hrefs: set[str]) -> str:
    href = f"assets/{path.name}"
    if href not in used_hrefs:
        return href

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    suffix = path.suffix or ".bin"
    return f"assets/{digest}{suffix}"


def _rewrite_page_assets(page: ProcessedPage, localized_by_url: dict[str, AssetRef]) -> ProcessedPage:
    if not page.asset_urls:
        return page

    soup = BeautifulSoup(f"<root>{page.xhtml}</root>", "html.parser")
    root = soup.find("root")
    if root is None:
        return page

    changed = False
    for tag in root.find_all(ASSET_ATTRIBUTES.keys()):
        if not isinstance(tag, Tag):
            continue
        attribute = ASSET_ATTRIBUTES[str(tag.name)]
        raw_url = tag.get(attribute)
        if not isinstance(raw_url, str):
            continue
        asset = localized_by_url.get(raw_url)
        if asset is None:
            continue
        tag[attribute] = f"../{asset.href}"
        changed = True

    for tag in root.find_all(attrs={EPUB_BACKGROUND_ASSET_ATTRIBUTE: True}):
        if not isinstance(tag, Tag):
            continue
        raw_url = tag.get(EPUB_BACKGROUND_ASSET_ATTRIBUTE)
        if not isinstance(raw_url, str):
            continue
        asset = localized_by_url.get(raw_url)
        if asset is None:
            continue
        existing_style = str(tag.get("style", "")).strip()
        declarations = [declaration.strip() for declaration in existing_style.split(";") if declaration.strip()]
        declarations = [
            declaration
            for declaration in declarations
            if declaration.partition(":")[0].strip().lower()
            not in {"background-image", "background-repeat"}
        ]
        declarations.extend(
            [
                f'background-image: url("../{asset.href}")',
                "background-repeat: repeat",
            ]
        )
        tag["style"] = "; ".join(declarations)
        tag.attrs.pop(EPUB_BACKGROUND_ASSET_ATTRIBUTE, None)
        changed = True

    if not changed:
        return page

    xhtml = "".join(str(child) for child in root.contents).strip()
    return replace(page, xhtml=xhtml)


def _page_references_any_asset(page: ProcessedPage, asset_urls: set[str]) -> bool:
    soup = BeautifulSoup(f"<root>{page.xhtml}</root>", "html.parser")
    root = soup.find("root")
    if root is None:
        return False

    for tag in root.find_all(ASSET_ATTRIBUTES.keys()):
        if not isinstance(tag, Tag):
            continue
        attribute = ASSET_ATTRIBUTES[str(tag.name)]
        raw_url = tag.get(attribute)
        if isinstance(raw_url, str) and raw_url in asset_urls:
            return True
    for tag in root.find_all(attrs={EPUB_BACKGROUND_ASSET_ATTRIBUTE: True}):
        raw_url = tag.get(EPUB_BACKGROUND_ASSET_ATTRIBUTE)
        if isinstance(raw_url, str) and raw_url in asset_urls:
            return True
    return False


def _unique(values) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values
