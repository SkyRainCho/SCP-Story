from __future__ import annotations

from pathlib import Path

from PIL import Image

import scp_epub.assets as assets_module
from scp_epub.assets import (
    localize_assets,
    remote_resource_page_slugs,
)
from scp_epub.models import FetchResult, PageRef, ProcessedPage


class FakeAssetFetcher:
    def __init__(self, root: Path, assets: dict[str, tuple[str, bytes]], failures: set[str] | None = None):
        self.root = root
        self.assets = assets
        self.failures = failures or set()
        self.calls: list[tuple[str, bool]] = []

    def fetch_asset(self, url: str, *, force: bool = False) -> FetchResult:
        self.calls.append((url, force))
        if url in self.failures:
            raise RuntimeError(f"missing {url}")
        filename, content = self.assets[url]
        asset_path = self.root / filename
        metadata_path = self.root / f"{filename}.json"
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(content)
        metadata_path.write_text("{}", encoding="utf-8")
        content_type = "text/css" if filename.endswith(".css") else "image/png"
        return FetchResult(
            url=url,
            path=asset_path,
            metadata_path=metadata_path,
            from_cache=False,
            status_code=200,
            content_type=content_type,
        )


def _page(
    slug: str,
    order: int,
    xhtml: str,
    asset_urls: tuple[str, ...],
) -> ProcessedPage:
    return ProcessedPage(
        entry=PageRef(
            title=slug.upper(),
            url=f"https://scp-wiki-cn.wikidot.com/{slug}",
            slug=slug,
            level=1,
            role="scp",
            order=order,
        ),
        xhtml=xhtml,
        asset_urls=asset_urls,
        internal_links=(),
        external_links=(),
    )


def test_localize_assets_fetches_unique_assets_rewrites_xhtml_and_preserves_data_assets(tmp_path: Path):
    image_url = "https://scp-wiki-cn.wikidot.com/images/photo.png"
    css_url = "https://scp-wiki-cn.wikidot.com/css/page.css"
    pages = [
        _page(
            "scp-001",
            1,
            (
                f'<p><img src="{image_url}" alt="one"/>'
                f'<img src="data:image/png;base64,AAAA" alt="inline"/>'
                f'<link rel="stylesheet" href="{css_url}"/></p>'
            ),
            (image_url, css_url),
        ),
        _page(
            "scp-002",
            2,
            f'<figure><img src="{image_url}" alt="two"/></figure>',
            (image_url,),
        ),
    ]
    fetcher = FakeAssetFetcher(
        tmp_path,
        {
            image_url: ("photo.png", b"image"),
            css_url: ("page.css", b"body{}"),
        },
    )

    localized_pages, assets, missing_assets = localize_assets(pages, fetcher)

    assert fetcher.calls == [(image_url, False), (css_url, False)]
    assert missing_assets == []
    assert [asset.source_url for asset in assets] == [image_url, css_url]
    assert [asset.href for asset in assets] == ["assets/photo.png", "assets/page.css"]
    assert '../assets/photo.png' in localized_pages[0].xhtml
    assert '../assets/page.css' in localized_pages[0].xhtml
    assert 'src="data:image/png;base64,AAAA"' in localized_pages[0].xhtml
    assert '../assets/photo.png' in localized_pages[1].xhtml
    assert localized_pages[0].asset_urls == (image_url, css_url)


def test_localize_assets_leaves_failed_assets_remote_and_reports_missing(tmp_path: Path):
    good_url = "https://scp-wiki-cn.wikidot.com/images/photo.png"
    missing_url = "https://scp-wiki-cn.wikidot.com/images/missing.png"
    pages = [
        _page(
            "scp-001",
            1,
            f'<img src="{good_url}"/><source src="{missing_url}"/>',
            (good_url, missing_url),
        )
    ]
    fetcher = FakeAssetFetcher(
        tmp_path,
        {good_url: ("photo.png", b"image")},
        failures={missing_url},
    )

    localized_pages, assets, missing_assets = localize_assets(pages, fetcher)

    assert [asset.source_url for asset in assets] == [good_url]
    assert missing_assets == [missing_url]
    assert '../assets/photo.png' in localized_pages[0].xhtml
    assert missing_url in localized_pages[0].xhtml


def test_localize_assets_passes_force_to_fetcher(tmp_path: Path):
    image_url = "https://scp-wiki-cn.wikidot.com/images/photo.png"
    page = _page("scp-001", 1, f'<img src="{image_url}"/>', (image_url,))
    fetcher = FakeAssetFetcher(tmp_path, {image_url: ("photo.png", b"image")})

    localize_assets([page], fetcher, force=True)

    assert fetcher.calls == [(image_url, True)]


def test_localize_assets_rewrites_explicit_epub_background_asset(tmp_path: Path):
    marble_url = "https://scp-wiki.wdfiles.com/local--files/about-the-scp-foundation/bg-marble.png"
    page = _page(
        "about-the-scp-foundation",
        1,
        f'<div class="content-panel" data-epub-background-url="{marble_url}">正文</div>',
        (marble_url,),
    )
    fetcher = FakeAssetFetcher(tmp_path, {marble_url: ("bg-marble.png", b"image")})

    localized_pages, assets, missing_assets = localize_assets([page], fetcher)

    assert [asset.source_url for asset in assets] == [marble_url]
    assert missing_assets == []
    assert 'background-image: url("../assets/bg-marble.png")' in localized_pages[0].xhtml
    assert "background-repeat: repeat" in localized_pages[0].xhtml
    assert "data-epub-background-url" not in localized_pages[0].xhtml


def test_remote_resource_page_slugs_returns_only_pages_with_missing_asset_refs():
    missing_url = "https://scp-wiki-cn.wikidot.com/images/missing.png"
    pages = [
        _page("scp-001", 1, f'<img src="{missing_url}"/>', (missing_url,)),
        _page("scp-002", 2, '<img src="../assets/photo.png"/>', ()),
    ]

    assert remote_resource_page_slugs(pages, [missing_url]) == {"scp-001"}


def test_materialize_anomaly_diamond_assets_renders_png_and_rewrites_page(tmp_path: Path):
    icon_path = tmp_path / "icon.svg"
    icon_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"></svg>',
        encoding="utf-8",
    )
    icon_asset = assets_module.AssetRef(
        "https://example.com/icon.svg",
        icon_path,
        "assets/icon.svg",
        "image/svg+xml",
    )
    page = _page(
        "scp-6764",
        1,
        (
            '<div class="danger-diamond">'
            '<svg class="anomaly-diamond-frame" viewBox="0 0 160 160">'
            '<polygon points="51.226,3.456 108.250,3.456 132.096,27.264 '
            '80.256,80.256 28.416,27.264" fill="#009f6b" '
            'fill-opacity="0.25" data-quadrant="top"></polygon>'
            '<polygon points="51.226,3.456 108.250,3.456 132.096,27.264 '
            '80.256,80.256 28.416,27.264" fill="#c40233" '
            'fill-opacity="0.25" data-quadrant="right" '
            'transform="rotate(90 80.256 80.256)"></polygon>'
            '<polygon points="51.226,3.456 108.250,3.456 132.096,27.264 '
            '80.256,80.256 28.416,27.264" fill="#0087bd" '
            'fill-opacity="0.25" data-quadrant="left" '
            'transform="rotate(270 80.256 80.256)"></polygon>'
            '<path fill="#010101" d="M136.1,133.3l23.9-23.9V51.2"></path>'
            '</svg><table class="anomaly-diamond-layout"><tbody>'
            '<tr><td></td><td class="anomaly-diamond-top">'
            '<img class="anomaly-diamond-icon" src="../assets/icon.svg"/></td><td></td></tr>'
            '<tr><td class="anomaly-diamond-left"><img class="anomaly-diamond-icon" '
            'src="../assets/icon.svg"/></td><td></td>'
            '<td class="anomaly-diamond-right"><img class="anomaly-diamond-icon" '
            'src="../assets/icon.svg"/></td></tr></tbody></table></div>'
        ),
        (),
    )

    [prepared_page], assets = assets_module.materialize_anomaly_diamond_assets(
        [page],
        [icon_asset],
        tmp_path / "generated-assets",
    )

    assert "<svg" not in prepared_page.xhtml
    assert "anomaly-diamond-frame" in prepared_page.xhtml
    assert "anomaly-diamond-composite" in prepared_page.xhtml
    assert "anomaly-diamond-layout" not in prepared_page.xhtml
    assert "anomaly-diamond-icon" not in prepared_page.xhtml
    assert len(assets) == 2
    frame_asset = assets[-1]
    assert frame_asset.source_url.startswith("builtin://anomaly-diamond/")
    assert frame_asset.href.endswith(".png")
    assert frame_asset.content_type == "image/png"
    assert frame_asset.path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert f'../{frame_asset.href}' in prepared_page.xhtml

    image = Image.open(frame_asset.path).convert("RGBA")

    def color_bounds(color: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        points = [
            (x, y)
            for y in range(image.height)
            for x in range(image.width)
            if image.getpixel((x, y)) == color
        ]
        assert points
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return min(xs), min(ys), max(xs), max(ys)

    expected_centers = {
        (0, 159, 107, 255): (320, 122),
        (0, 135, 189, 255): (122, 320),
        (196, 2, 51, 255): (518, 320),
    }
    for color, expected_center in expected_centers.items():
        left, top, right, bottom = color_bounds(color)
        assert abs((right - left) - (bottom - top)) <= 2
        assert abs((left + right) / 2 - expected_center[0]) <= 3
        assert abs((top + bottom) / 2 - expected_center[1]) <= 3
