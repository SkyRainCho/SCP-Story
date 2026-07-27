from __future__ import annotations

import hashlib
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from .assets import AssetRef
from .kindle import (
    _rewrite_kindle_asset_references,
    local_image_references,
    rewrite_page_image_references,
)
from .models import ProcessedPage


MIB = 1024 * 1024
_SUPPORTED_RASTER_FORMATS = frozenset({"GIF", "JPEG", "MPO", "PNG"})
IMAGE_ENCODING_PROFILE = "grayscale-preserve-alpha"


class KindleStabilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class StableVariantSpec:
    purpose: str
    max_width: int
    max_height: int


@dataclass(frozen=True)
class StableImageInfo:
    href: str
    width: int
    height: int
    frame_count: int
    format_name: str
    has_transparency: bool

    def fitted_size(self, spec: StableVariantSpec) -> tuple[int, int]:
        scale = min(
            1.0,
            spec.max_width / self.width,
            spec.max_height / self.height,
        )
        return (
            max(1, round(self.width * scale)),
            max(1, round(self.height * scale)),
        )


FACILITY_SPEC = StableVariantSpec("facility", 384, 384)
ORDINARY_SPEC = StableVariantSpec("ordinary", 1800, 2400)
ADAPTIVE_SPECS = (
    StableVariantSpec("adaptive", 1600, 2200),
    StableVariantSpec("adaptive", 1400, 1900),
    StableVariantSpec("adaptive", 1200, 1600),
    StableVariantSpec("adaptive", 1000, 1400),
    StableVariantSpec("adaptive", 800, 1100),
)
TARGET_DECODE_BYTES = 64 * MIB
HARD_DECODE_BYTES = 96 * MIB


@dataclass(frozen=True)
class StablePagePerformance:
    slug: str
    image_count: int
    before_decode_bytes: int
    after_decode_bytes: int
    selected_bound: tuple[int, int]
    warning: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "slug": self.slug,
            "image_count": self.image_count,
            "before_decode_bytes": self.before_decode_bytes,
            "after_decode_bytes": self.after_decode_bytes,
            "selected_bound": list(self.selected_bound),
            "warning": self.warning,
        }


@dataclass(frozen=True)
class StableVariantPlan:
    reference_specs: dict[tuple[str, int], StableVariantSpec]
    image_info_by_href: dict[str, StableImageInfo]
    page_performance: tuple[StablePagePerformance, ...]
    warnings: tuple[str, ...]
    hard_failures: tuple[str, ...] = ()

    def spec_for(self, slug: str, occurrence: int) -> StableVariantSpec:
        return self.reference_specs[(slug, occurrence)]


@dataclass(frozen=True)
class StableKindleResult:
    pages: list[ProcessedPage]
    assets: list[AssetRef]
    missing_assets: list[str]
    performance: dict[str, object]


def stable_passthrough_asset(asset: AssetRef) -> bool:
    suffix = asset.path.suffix.casefold()
    return asset.content_type.casefold() not in {
        "image/gif",
        "image/jpeg",
        "image/png",
    } and suffix not in {".gif", ".jpeg", ".jpg", ".png"}


def inspect_stable_image(asset: AssetRef) -> StableImageInfo:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(asset.path) as image:
            format_name = str(image.format or "").upper()
            if format_name not in _SUPPORTED_RASTER_FORMATS:
                raise KindleStabilityError(
                    f"Unsupported stable raster format for {asset.href}: {format_name or 'unknown'}"
                )
            width, height = image.size
            orientation = image.getexif().get(274)
            if orientation in {5, 6, 7, 8}:
                width, height = height, width
            image.seek(0)
            return StableImageInfo(
                href=asset.href,
                width=width,
                height=height,
                frame_count=int(getattr(image, "n_frames", 1)),
                format_name=format_name,
                has_transparency=_frame_has_transparency(image),
            )


def plan_stable_variants(
    pages: Sequence[ProcessedPage],
    assets: Sequence[AssetRef],
) -> StableVariantPlan:
    assets_by_href = {asset.href: asset for asset in assets}
    referenced_hrefs = {
        reference.href
        for page in pages
        for reference in local_image_references(page)
    }
    image_info_by_href: dict[str, StableImageInfo] = {}
    for href in sorted(referenced_hrefs):
        asset = assets_by_href.get(href)
        if asset is None or stable_passthrough_asset(asset):
            continue
        image_info_by_href[href] = inspect_stable_image(asset)

    reference_specs: dict[tuple[str, int], StableVariantSpec] = {}
    performance: list[StablePagePerformance] = []
    hard_failures: list[tuple[str, int]] = []

    for page in pages:
        slug = page.entry.slug
        references = [
            reference
            for reference in local_image_references(page)
            if reference.href in image_info_by_href
        ]
        for reference in references:
            reference_specs[(slug, reference.occurrence)] = (
                FACILITY_SPEC
                if "facility-icon-epub" in reference.classes
                else ORDINARY_SPEC
            )

        before_decode_bytes = sum(
            image_info_by_href[href].width
            * image_info_by_href[href].height
            * 4
            for href in {reference.href for reference in references}
        )
        selected_spec = ORDINARY_SPEC
        after_decode_bytes = _estimate_page_decode_bytes(
            slug,
            references,
            reference_specs,
            image_info_by_href,
        )
        has_ordinary = any(
            reference_specs[(slug, reference.occurrence)] is ORDINARY_SPEC
            for reference in references
        )
        if has_ordinary and after_decode_bytes > TARGET_DECODE_BYTES:
            for adaptive_spec in ADAPTIVE_SPECS:
                for reference in references:
                    key = (slug, reference.occurrence)
                    if "facility-icon-epub" not in reference.classes:
                        reference_specs[key] = adaptive_spec
                selected_spec = adaptive_spec
                after_decode_bytes = _estimate_page_decode_bytes(
                    slug,
                    references,
                    reference_specs,
                    image_info_by_href,
                )
                if after_decode_bytes <= TARGET_DECODE_BYTES:
                    break
        elif references and not has_ordinary:
            selected_spec = FACILITY_SPEC

        warning = after_decode_bytes > TARGET_DECODE_BYTES
        if after_decode_bytes > HARD_DECODE_BYTES:
            hard_failures.append((slug, after_decode_bytes))
        performance.append(
            StablePagePerformance(
                slug=slug,
                image_count=len(references),
                before_decode_bytes=before_decode_bytes,
                after_decode_bytes=after_decode_bytes,
                selected_bound=(
                    (selected_spec.max_width, selected_spec.max_height)
                    if references
                    else (0, 0)
                ),
                warning=warning,
            )
        )

    if hard_failures:
        details = ", ".join(
            f"{slug} ({decode_bytes / MIB:.1f} MiB)"
            for slug, decode_bytes in hard_failures
        )
        raise KindleStabilityError(f"Pages over 96 MiB decoded image budget: {details}")

    return StableVariantPlan(
        reference_specs=reference_specs,
        image_info_by_href=image_info_by_href,
        page_performance=tuple(performance),
        warnings=tuple(item.slug for item in performance if item.warning),
    )


def _estimate_page_decode_bytes(
    slug: str,
    references: Sequence[object],
    reference_specs: dict[tuple[str, int], StableVariantSpec],
    image_info_by_href: dict[str, StableImageInfo],
) -> int:
    unique_variants = {
        (
            reference.href,
            reference_specs[(slug, reference.occurrence)],
        )
        for reference in references
    }
    return sum(
        width * height * 4
        for href, spec in unique_variants
        for width, height in [image_info_by_href[href].fitted_size(spec)]
    )


def prepare_stable_kindle_assets(
    pages: Sequence[ProcessedPage],
    assets: Sequence[AssetRef],
    output_dir: Path,
    missing_assets: Sequence[str] = (),
) -> StableKindleResult:
    plan = plan_stable_variants(pages, assets)
    assets_by_href = {asset.href: asset for asset in assets}
    variant_requests: list[tuple[str, StableVariantSpec]] = []
    seen_requests: set[tuple[str, StableVariantSpec]] = set()
    for page in pages:
        for reference in local_image_references(page):
            key = (page.entry.slug, reference.occurrence)
            spec = plan.reference_specs.get(key)
            if spec is None:
                continue
            request = (reference.href, spec)
            if request not in seen_requests:
                seen_requests.add(request)
                variant_requests.append(request)

    rendered: dict[tuple[str, StableVariantSpec], AssetRef] = {}
    failed_hrefs: set[str] = set()
    missing = list(missing_assets)
    seen_missing = set(missing)
    for href, spec in variant_requests:
        asset = assets_by_href[href]
        try:
            rendered[(href, spec)] = render_stable_variant(asset, spec, output_dir)
        except Exception:
            failed_hrefs.add(href)
            if asset.source_url not in seen_missing:
                seen_missing.add(asset.source_url)
                missing.append(asset.source_url)

    stable_pages: list[ProcessedPage] = []
    for page in pages:
        replacements: dict[tuple[int, str], str] = {}
        for reference in local_image_references(page):
            spec = plan.reference_specs.get((page.entry.slug, reference.occurrence))
            if spec is None:
                continue
            variant = rendered.get((reference.href, spec))
            if variant is not None:
                replacements[(reference.occurrence, reference.href)] = variant.href
        rewritten = rewrite_page_image_references(page, replacements)
        if failed_hrefs:
            rewritten = _rewrite_kindle_asset_references(
                rewritten,
                {},
                failed_hrefs,
            )
        stable_pages.append(rewritten)

    referenced_original_hrefs = {
        asset.href
        for asset in assets
        if any(f"../{asset.href}" in page.xhtml for page in stable_pages)
    }
    stable_assets = [
        asset for asset in assets if asset.href in referenced_original_hrefs
    ]
    stable_assets.extend(rendered[request] for request in variant_requests if request in rendered)

    page_performance = plan.page_performance
    animated_hrefs = {
        href
        for href, _spec in rendered
        if plan.image_info_by_href[href].frame_count > 1
    }
    rendered_requests = tuple(rendered)
    grayscale_alpha_variant_count = sum(
        1
        for href, _spec in rendered_requests
        if plan.image_info_by_href[href].has_transparency
    )
    performance: dict[str, object] = {
        "profile": "kindle-scribe-300ppi",
        "image_encoding_profile": IMAGE_ENCODING_PROFILE,
        "grayscale_variant_count": len(rendered_requests),
        "grayscale_alpha_variant_count": grayscale_alpha_variant_count,
        "target_decode_bytes": TARGET_DECODE_BYTES,
        "hard_decode_bytes": HARD_DECODE_BYTES,
        "before_decode_bytes": sum(
            item.before_decode_bytes for item in page_performance
        ),
        "after_decode_bytes": sum(
            item.after_decode_bytes for item in page_performance
        ),
        "animated_gifs_made_static": len(animated_hrefs),
        "thumbnail_variant_count": sum(
            1 for _href, spec in rendered if spec.purpose == "facility"
        ),
        "adaptive_variant_count": sum(
            1 for _href, spec in rendered if spec.purpose == "adaptive"
        ),
        "pages": [
            item.as_dict()
            for item in page_performance
            if item.after_decode_bytes > 32 * MIB
        ],
        "warnings": list(plan.warnings),
    }
    return StableKindleResult(
        pages=stable_pages,
        assets=stable_assets,
        missing_assets=missing,
        performance=performance,
    )


def _frame_has_transparency(frame: Image.Image) -> bool:
    return "A" in frame.getbands() or "transparency" in frame.info


def _convert_frame_to_grayscale(frame: Image.Image) -> Image.Image:
    if not _frame_has_transparency(frame):
        return frame.convert("L")
    rgba = frame.convert("RGBA")
    luminance = rgba.convert("RGB").convert("L")
    return Image.merge("LA", (luminance, rgba.getchannel("A")))


def render_stable_variant(
    asset: AssetRef,
    spec: StableVariantSpec,
    output_dir: Path,
) -> AssetRef:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(asset.path) as source:
            format_name = str(source.format or "").upper()
            if format_name not in _SUPPORTED_RASTER_FORMATS:
                raise KindleStabilityError(
                    f"Unsupported stable raster format for {asset.href}: {format_name or 'unknown'}"
                )
            source.seek(0)
            frame = ImageOps.exif_transpose(source.copy())

    scale = min(
        1.0,
        spec.max_width / frame.width,
        spec.max_height / frame.height,
    )
    fitted_size = (
        max(1, round(frame.width * scale)),
        max(1, round(frame.height * scale)),
    )
    if fitted_size != frame.size:
        frame = frame.resize(fitted_size, Image.Resampling.LANCZOS)

    output_format = "JPEG" if format_name in {"JPEG", "MPO"} else "PNG"
    frame = _convert_frame_to_grayscale(frame)
    if output_format == "JPEG" and frame.mode == "LA":
        frame = frame.getchannel("L")

    digest = hashlib.sha256(
        (
            f"{asset.source_url}|{IMAGE_ENCODING_PROFILE}|{spec.purpose}|"
            f"{spec.max_width}x{spec.max_height}"
        ).encode("utf-8")
    ).hexdigest()[:12]
    suffix = ".jpg" if output_format == "JPEG" else ".png"
    filename = (
        f"{Path(asset.href).stem}-{digest}-gray-{spec.purpose}-"
        f"{spec.max_width}x{spec.max_height}{suffix}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    if output_format == "JPEG":
        frame.save(
            output_path,
            format="JPEG",
            quality=85,
            optimize=True,
            progressive=False,
        )
        content_type = "image/jpeg"
    else:
        frame.save(output_path, format="PNG", optimize=True)
        content_type = "image/png"

    return AssetRef(
        source_url=asset.source_url,
        path=output_path,
        href=f"assets/{filename}",
        content_type=content_type,
    )
