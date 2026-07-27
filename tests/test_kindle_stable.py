from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
import pytest

from scp_epub.assets import AssetRef
import scp_epub.kindle_stable as kindle_stable_module
from scp_epub.kindle_stable import (
    MIB,
    KindleStabilityError,
    StableVariantSpec,
    plan_stable_variants,
    prepare_stable_kindle_assets,
    render_stable_variant,
)
from scp_epub.models import PageRef, ProcessedPage


def _asset(tmp_path: Path, name: str, data: bytes) -> AssetRef:
    path = tmp_path / name
    path.write_bytes(data)
    suffix = path.suffix.casefold()
    content_type = {
        ".gif": "image/gif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }[suffix]
    return AssetRef(
        source_url=f"https://example.test/{name}",
        path=path,
        href=f"assets/{name}",
        content_type=content_type,
    )


def _jpeg_bytes(
    size: tuple[int, int], *, exif_orientation: int | None = None
) -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", size, (180, 90, 30))
    exif = Image.Exif()
    if exif_orientation is not None:
        exif[274] = exif_orientation
    image.save(output, format="JPEG", quality=95, exif=exif)
    return output.getvalue()


def _png_bytes(size: tuple[int, int], *, alpha: bool = False) -> bytes:
    output = io.BytesIO()
    mode = "RGBA" if alpha else "RGB"
    color = (30, 120, 210, 100) if alpha else (30, 120, 210)
    Image.new(mode, size, color).save(output, format="PNG")
    return output.getvalue()


def _animated_gif_bytes(size: tuple[int, int]) -> bytes:
    output = io.BytesIO()
    first = Image.new("RGB", size, (255, 0, 0))
    second = Image.new("RGB", size, (0, 0, 255))
    first.save(
        output,
        format="GIF",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    return output.getvalue()


def _page(slug: str, xhtml: str) -> ProcessedPage:
    return ProcessedPage(
        entry=PageRef(
            title=slug,
            url=f"https://scp-wiki-cn.wikidot.com/{slug}",
            slug=slug,
            level=1,
            role="scp",
            order=1,
        ),
        xhtml=xhtml,
        asset_urls=(),
        internal_links=(),
        external_links=(),
    )


def _large_png_asset(
    tmp_path: Path, name: str, size: tuple[int, int]
) -> AssetRef:
    return _asset(tmp_path, name, _png_bytes(size))


def _page_with_assets(slug: str, assets: list[AssetRef]) -> ProcessedPage:
    return _page(
        slug,
        "".join(f'<img src="../{asset.href}" alt="" />' for asset in assets),
    )


def _plan_fixed_images(
    tmp_path: Path, *, count: int, size: tuple[int, int]
):
    assets = [
        _large_png_asset(tmp_path, f"fixed-{index}.png", size)
        for index in range(count)
    ]
    return plan_stable_variants([_page_with_assets("fixed", assets)], assets)


def test_render_stable_variant_bounds_jpeg_and_uses_quality_85(tmp_path: Path):
    source = _asset(tmp_path, "photo.jpg", _jpeg_bytes((4000, 3000)))
    spec = StableVariantSpec("ordinary", 1800, 2400)

    prepared = render_stable_variant(source, spec, tmp_path / "stable-assets")

    assert prepared.href.endswith("-gray-ordinary-1800x2400.jpg")
    with Image.open(prepared.path) as image:
        assert image.size == (1800, 1350)
        assert image.mode == "L"
        assert image.format == "JPEG"
        assert image.info.get("progressive", 0) == 0


def test_render_stable_variant_encodes_opaque_png_as_grayscale(tmp_path: Path):
    source = _asset(tmp_path, "diagram.png", _png_bytes((1200, 800)))

    prepared = render_stable_variant(
        source,
        StableVariantSpec("ordinary", 1800, 2400),
        tmp_path / "stable-assets",
    )

    assert "-gray-ordinary-1800x2400.png" in prepared.href
    with Image.open(prepared.path) as image:
        assert image.size == (1200, 800)
        assert image.mode == "L"
        assert image.format == "PNG"


def test_render_stable_variant_preserves_png_alpha_in_grayscale(tmp_path: Path):
    source = _asset(tmp_path, "icon.png", _png_bytes((1200, 800), alpha=True))

    prepared = render_stable_variant(
        source,
        StableVariantSpec("facility", 384, 384),
        tmp_path / "stable-assets",
    )

    with Image.open(prepared.path) as image:
        assert image.size == (384, 256)
        assert image.mode == "LA"
        assert image.getchannel("A").getpixel((0, 0)) == 100
        assert image.format == "PNG"


def test_render_stable_variant_freezes_animated_gif_to_first_frame(tmp_path: Path):
    source = _asset(tmp_path, "animated.gif", _animated_gif_bytes((600, 600)))
    spec = StableVariantSpec("ordinary", 1800, 2400)

    prepared = render_stable_variant(source, spec, tmp_path / "stable-assets")

    assert prepared.content_type == "image/png"
    with Image.open(prepared.path) as image:
        assert getattr(image, "n_frames", 1) == 1
        assert image.mode == "L"
        assert image.getpixel((0, 0)) == 76
        assert image.convert("RGB").getpixel((0, 0)) == (76, 76, 76)


def test_render_stable_variant_applies_exif_orientation_before_sizing(tmp_path: Path):
    source = _asset(
        tmp_path,
        "rotated.jpg",
        _jpeg_bytes((1200, 600), exif_orientation=6),
    )

    prepared = render_stable_variant(
        source,
        StableVariantSpec("ordinary", 1800, 2400),
        tmp_path / "stable-assets",
    )

    with Image.open(prepared.path) as image:
        assert image.size == (600, 1200)


def test_render_stable_variant_treats_mpo_as_first_frame_jpeg(
    tmp_path: Path, monkeypatch
):
    source = _asset(tmp_path, "stereo.jpg", _jpeg_bytes((1600, 1200)))
    real_open = kindle_stable_module.Image.open

    def open_as_mpo(*args, **kwargs):
        image = real_open(*args, **kwargs)
        image.format = "MPO"
        return image

    monkeypatch.setattr(kindle_stable_module.Image, "open", open_as_mpo)

    prepared = render_stable_variant(
        source,
        StableVariantSpec("ordinary", 1800, 2400),
        tmp_path / "stable-assets",
    )

    assert prepared.content_type == "image/jpeg"
    assert prepared.path.suffix == ".jpg"


def test_prepare_stable_assets_reports_grayscale_variants(tmp_path: Path):
    opaque = _asset(tmp_path, "opaque.png", _png_bytes((200, 100)))
    alpha = _asset(tmp_path, "alpha.png", _png_bytes((200, 100), alpha=True))
    page = _page_with_assets("gray-report", [opaque, alpha])

    result = prepare_stable_kindle_assets(
        [page],
        [opaque, alpha],
        tmp_path / "stable-assets",
    )

    assert result.performance["image_encoding_profile"] == (
        "grayscale-preserve-alpha"
    )
    assert result.performance["grayscale_variant_count"] == 2
    assert result.performance["grayscale_alpha_variant_count"] == 1


def test_plan_uses_facility_thumbnail_only_for_facility_reference(tmp_path: Path):
    asset = _large_png_asset(tmp_path, "site.png", (4500, 4500))
    pages = [
        _page(
            "facilities",
            '<img class="facility-icon-epub" src="../assets/site.png" />',
        ),
        _page("dossier", '<img src="../assets/site.png" />'),
    ]

    plan = plan_stable_variants(pages, [asset])

    assert plan.spec_for("facilities", 0).max_width == 384
    assert plan.spec_for("dossier", 0) == StableVariantSpec(
        "ordinary", 1800, 2400
    )


def test_plan_selects_largest_adaptive_cap_under_64_mib(tmp_path: Path):
    assets = [
        _large_png_asset(tmp_path, f"image-{index}.png", (3000, 3000))
        for index in range(12)
    ]
    page = _page_with_assets("heavy", assets)

    plan = plan_stable_variants([page], assets)
    performance = plan.page_performance[0]

    assert performance.after_decode_bytes <= 64 * MIB
    assert performance.selected_bound != (1800, 2400)
    assert performance.selected_bound in {
        (1600, 2200),
        (1400, 1900),
        (1200, 1600),
        (1000, 1400),
        (800, 1100),
    }


def test_plan_warns_between_64_and_96_mib_and_rejects_over_96_mib(tmp_path: Path):
    warning_plan = _plan_fixed_images(tmp_path, count=30, size=(800, 800))
    assert warning_plan.warnings
    assert warning_plan.hard_failures == ()

    with pytest.raises(KindleStabilityError, match="over 96 MiB"):
        _plan_fixed_images(tmp_path, count=40, size=(800, 800))
