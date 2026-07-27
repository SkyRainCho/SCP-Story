# Kindle Scribe Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `--kindle-stable` build that creates screen-appropriate image variants, enforces a per-XHTML decoded-image budget, and writes separate Kindle Scribe stable EPUB/AZW3/report artifacts.

**Architecture:** Keep the existing high-quality Kindle pipeline unchanged. Add a focused `kindle_stable.py` layer that consumes already validated Kindle pages/assets, plans page-specific variants, renders them deterministically, rewrites only matching image references, and returns performance metrics. Represent output selection with a `BuildMode` enum and pass the stable performance payload through the existing EPUB/report pipeline.

**Tech Stack:** Python 3.11, Pillow, tinycss2, BeautifulSoup/custom HTML parsers already present in the repository, pytest, Calibre `ebook-convert`.

---

## File Structure

- Create `src/scp_epub/kindle_stable.py`: stable image policy, metadata inspection, page reference planning, variant rendering, decoded-memory accounting, page-specific XHTML rewriting, and performance report structures.
- Modify `src/scp_epub/kindle.py`: expose lossless local-image reference/rewrite helpers and add the stable-only CSS safety pass without changing default Kindle behavior.
- Modify `src/scp_epub/cli.py`: add mutually exclusive `--kindle` and `--kindle-stable` build flags.
- Modify `src/scp_epub/pipeline.py`: introduce `BuildMode`, select stable filenames/directories, call stable preparation, and pass metrics to the report writer.
- Modify `src/scp_epub/epub.py`: accept an optional `kindle_performance` report object.
- Modify `README.md`: document the stable command, outputs, limits, and failure behavior.
- Create `tests/test_kindle_stable.py`: focused policy, rendering, budgeting, and rewriting tests.
- Modify `tests/test_kindle.py`, `tests/test_cli.py`, `tests/test_pipeline.py`, and `tests/test_epub.py`: integration and regression coverage.

`src/scp_epub/pipeline.py` already contains unrelated user changes. Every commit touching it must use `git add -p src/scp_epub/pipeline.py` and stage only hunks for `BuildMode`, stable output selection, stable preparation, and stable reporting. Reject all pre-existing worker/fetcher hunks.

### Task 1: Explicit build modes and stable CLI/output contract

**Files:**
- Modify: `src/scp_epub/cli.py`
- Modify: `src/scp_epub/pipeline.py:220-340, 840-905`
- Modify: `tests/test_cli.py:39-49, 131-165`
- Modify: `tests/test_pipeline.py:2390-2485`

- [ ] **Step 1: Write failing CLI tests for the stable flag and mutual exclusion**

Add these tests to `tests/test_cli.py`:

```python
def test_parser_accepts_kindle_stable_only_for_build():
    parser = build_parser()

    args = parser.parse_args(["build", "--volume", "featured", "--kindle-stable"])

    assert args.command == "build"
    assert args.kindle is False
    assert args.kindle_stable is True
    with pytest.raises(SystemExit):
        parser.parse_args(["fetch", "--kindle-stable"])


def test_parser_rejects_both_kindle_modes():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["build", "--kindle", "--kindle-stable"])
```

Update the existing command-dispatch test so the fake accepts `build_mode` and add:

```python
def test_build_command_passes_stable_mode_and_prints_stable_outputs(
    monkeypatch, tmp_path, capsys
):
    calls = []
    epub_path = tmp_path / "output" / "epub" / "book-Kindle-Scribe.epub"
    azw3_path = tmp_path / "output" / "azw3" / "book-Kindle-Scribe.azw3"
    monkeypatch.setattr("scp_epub.pipeline.load_config", lambda _path: "config")

    def fake_build_volume(config, volume, *, force=False, build_mode=None):
        calls.append((config, volume, force, build_mode))
        return epub_path

    monkeypatch.setattr("scp_epub.pipeline.build_volume", fake_build_volume)
    monkeypatch.setattr(
        "scp_epub.pipeline.kindle_azw3_path_for_volume",
        lambda _config, _volume, *, build_mode: azw3_path,
    )

    result = main(
        [
            "build",
            "--config",
            "config/featured-scp.yaml",
            "--volume",
            "featured",
            "--kindle-stable",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert calls[0][3].value == "kindle-stable"
    assert str(epub_path) in captured.out
    assert str(azw3_path) in captured.out
```

- [ ] **Step 2: Run the new CLI tests and verify RED**

Run:

```powershell
pytest -q tests/test_cli.py -k "kindle_stable or both_kindle_modes"
```

Expected: failures because `--kindle-stable` and `BuildMode` do not exist.

- [ ] **Step 3: Implement mutually exclusive CLI flags and `BuildMode`**

In `src/scp_epub/cli.py`, replace the single build flag with:

```python
if command == "build":
    kindle_group = subparser.add_mutually_exclusive_group()
    kindle_group.add_argument("--kindle", action="store_true")
    kindle_group.add_argument("--kindle-stable", action="store_true")
```

In `src/scp_epub/pipeline.py`, add:

```python
from enum import StrEnum


class BuildMode(StrEnum):
    EPUB = "epub"
    KINDLE = "kindle"
    KINDLE_STABLE = "kindle-stable"

    @property
    def is_kindle(self) -> bool:
        return self is not BuildMode.EPUB

    @property
    def output_suffix(self) -> str:
        return {
            BuildMode.EPUB: "",
            BuildMode.KINDLE: "-Kindle",
            BuildMode.KINDLE_STABLE: "-Kindle-Scribe",
        }[self]
```

Change `build_volume` to accept:

```python
def build_volume(
    config: AppConfig,
    volume_key: str,
    *,
    fetcher: PageFetcher | None = None,
    force: bool = False,
    build_mode: BuildMode = BuildMode.EPUB,
    kindle_converter: KindleConverter | None = None,
) -> Path:
```

Replace Kindle boolean branches with `build_mode.is_kindle`, and derive the slug with:

```python
output_slug = f"{volume.output_slug}{build_mode.output_suffix}"
```

Change the AZW3 helper to:

```python
def kindle_azw3_path_for_volume(
    config: AppConfig,
    volume: VolumeSpec | str,
    *,
    build_mode: BuildMode = BuildMode.KINDLE,
) -> Path:
    if not build_mode.is_kindle:
        raise ValueError("AZW3 output requires a Kindle build mode")
    volume_spec = volume_for_key(config, volume) if isinstance(volume, str) else volume
    return config.output_dir / "azw3" / (
        f"{volume_spec.output_slug}{build_mode.output_suffix}.azw3"
    )
```

Select the command mode in `run_command`:

```python
build_mode = (
    BuildMode.KINDLE_STABLE
    if bool(getattr(args, "kindle_stable", False))
    else BuildMode.KINDLE
    if bool(getattr(args, "kindle", False))
    else BuildMode.EPUB
)
output_path = build_volume(
    config,
    args.volume,
    force=force,
    build_mode=build_mode,
)
print(f"Wrote {output_path}")
if build_mode.is_kindle:
    print(
        f"Wrote {kindle_azw3_path_for_volume(config, args.volume, build_mode=build_mode)}"
    )
```

Update existing tests/callers from `kindle=True` to `build_mode=BuildMode.KINDLE` and import `BuildMode` where required.

- [ ] **Step 4: Run CLI and existing Kindle pipeline tests and verify GREEN**

Run:

```powershell
pytest -q tests/test_cli.py tests/test_pipeline.py -k "kindle or stable"
```

Expected: all selected tests pass; existing `-Kindle` output assertions remain unchanged.

- [ ] **Step 5: Commit only Task 1 hunks**

```powershell
git add src/scp_epub/cli.py tests/test_cli.py tests/test_pipeline.py
git add -p src/scp_epub/pipeline.py
git diff --cached --check
git commit -m "feat: add Kindle Scribe stable build mode"
```

During `git add -p`, stage only Task 1 mode/output hunks.

### Task 2: Stable-only CSS safety pass

**Files:**
- Modify: `src/scp_epub/kindle.py:1061-1125`
- Modify: `tests/test_kindle.py:1087-1378`

- [ ] **Step 1: Write failing stable CSS tests**

Add to `tests/test_kindle.py`:

```python
def test_prepare_kindle_pages_stable_removes_runtime_css_without_changing_content():
    xhtml = """
    <style>
      .card { animation: pulse 2s infinite; transition: all .2s; color: #111; }
      .panel { position: fixed; filter: blur(2px); background: white; }
    </style>
    <div class="card" style="position: sticky; transition: opacity 1s; color: red">
      正文
    </div>
    """

    [stable] = prepare_kindle_pages([_page(xhtml)], stable=True)
    [high_quality] = prepare_kindle_pages([_page(xhtml)])

    assert "animation" not in stable.xhtml
    assert "transition" not in stable.xhtml
    assert "filter" not in stable.xhtml
    assert "position: fixed" not in stable.xhtml
    assert "position: sticky" not in stable.xhtml
    assert "color: #111" in stable.xhtml
    assert "background: white" in stable.xhtml
    assert "正文" in stable.xhtml
    assert high_quality.xhtml == xhtml
```

- [ ] **Step 2: Run the CSS test and verify RED**

Run:

```powershell
pytest -q tests/test_kindle.py::test_prepare_kindle_pages_stable_removes_runtime_css_without_changing_content
```

Expected: `TypeError` because `prepare_kindle_pages` has no `stable` parameter.

- [ ] **Step 3: Implement the stable CSS declaration filter**

Change the public function to:

```python
def prepare_kindle_pages(
    pages: Sequence[ProcessedPage], *, stable: bool = False
) -> list[ProcessedPage]:
    return [
        replace(
            page,
            xhtml=_prepare_kindle_xhtml(
                page.xhtml,
                page_slug=page.entry.slug,
                stable=stable,
            ),
        )
        for page in pages
    ]
```

Add a declaration filter using `tinycss2`:

```python
_STABLE_REMOVED_CSS_PROPERTIES = frozenset(
    {
        "animation",
        "animation-delay",
        "animation-direction",
        "animation-duration",
        "animation-fill-mode",
        "animation-iteration-count",
        "animation-name",
        "animation-play-state",
        "animation-timing-function",
        "backdrop-filter",
        "filter",
        "transition",
        "transition-delay",
        "transition-duration",
        "transition-property",
        "transition-timing-function",
    }
)


def _stable_css_declarations(css: str) -> str:
    declarations = tinycss2.parse_declaration_list(
        css,
        skip_comments=True,
        skip_whitespace=True,
    )
    kept = []
    for declaration in declarations:
        if declaration.type != "declaration":
            continue
        name = declaration.lower_name
        value = tinycss2.serialize(declaration.value).strip()
        if name in _STABLE_REMOVED_CSS_PROPERTIES:
            continue
        if name == "position" and value.casefold() in {"fixed", "sticky"}:
            value = "static"
        suffix = " !important" if declaration.important else ""
        kept.append(f"{name}: {value}{suffix}")
    return "; ".join(kept)
```

Apply it to inline style values through the existing start-tag edit path. For
`<style>` content, parse the XHTML with the existing structure parser, replace
only style-element text ranges, and preserve non-style bytes. Call this pass only
when `stable=True`, after the existing Kindle semantic edits.

- [ ] **Step 4: Run Kindle page tests and verify GREEN**

```powershell
pytest -q tests/test_kindle.py -k "prepare_kindle_pages"
```

Expected: all selected tests pass, including the exact-output ordinary Kindle test.

- [ ] **Step 5: Commit Task 2**

```powershell
git add src/scp_epub/kindle.py tests/test_kindle.py
git diff --cached --check
git commit -m "feat: add stable Kindle CSS safety pass"
```

### Task 3: Stable raster metadata and deterministic variant rendering

**Files:**
- Create: `src/scp_epub/kindle_stable.py`
- Create: `tests/test_kindle_stable.py`

- [ ] **Step 1: Write failing raster-variant tests**

Create `tests/test_kindle_stable.py` with helpers that build temporary JPEG, PNG,
GIF, and EXIF-oriented images. Add tests equivalent to:

```python
def test_render_stable_variant_bounds_jpeg_and_uses_quality_85(tmp_path: Path):
    source = _asset(tmp_path, "photo.jpg", _jpeg_bytes((4000, 3000)))
    spec = StableVariantSpec("ordinary", 1800, 2400)

    prepared = render_stable_variant(source, spec, tmp_path / "stable-assets")

    assert prepared.href.endswith("-ordinary-1800x2400.jpg")
    with Image.open(prepared.path) as image:
        assert image.size == (1800, 1350)
        assert image.mode == "RGB"
        assert image.format == "JPEG"


def test_render_stable_variant_preserves_png_transparency(tmp_path: Path):
    source = _asset(tmp_path, "icon.png", _png_bytes((1200, 800), alpha=True))
    spec = StableVariantSpec("facility", 384, 384)

    prepared = render_stable_variant(source, spec, tmp_path / "stable-assets")

    with Image.open(prepared.path) as image:
        assert image.size == (384, 256)
        assert image.mode == "RGBA"
        assert image.format == "PNG"


def test_render_stable_variant_freezes_animated_gif_to_first_frame(tmp_path: Path):
    source = _asset(tmp_path, "animated.gif", _animated_gif_bytes((600, 600)))
    spec = StableVariantSpec("ordinary", 1800, 2400)

    prepared = render_stable_variant(source, spec, tmp_path / "stable-assets")

    assert prepared.content_type == "image/png"
    with Image.open(prepared.path) as image:
        assert image.n_frames == 1
        assert image.getpixel((0, 0))[:3] == (255, 0, 0)


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
```

- [ ] **Step 2: Run the new module tests and verify RED**

```powershell
pytest -q tests/test_kindle_stable.py
```

Expected: import failure because `scp_epub.kindle_stable` does not exist.

- [ ] **Step 3: Implement policy, metadata, and rendering primitives**

Create `src/scp_epub/kindle_stable.py` with these public structures:

```python
from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .assets import AssetRef


MIB = 1024 * 1024


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
```

Implement `inspect_stable_image(asset)` with Pillow header loading and decompression
bomb warnings promoted to errors. Implement `render_stable_variant` so it:

1. opens the source under the same bomb-warning policy;
2. seeks frame zero;
3. applies `ImageOps.exif_transpose`;
4. calculates the bounded size and resizes with `Image.Resampling.LANCZOS`;
5. saves animated GIFs and PNG inputs as optimized PNG;
6. saves JPEG inputs as RGB JPEG with `quality=85`, `optimize=True`, and
   `progressive=False`;
7. creates a deterministic filename from source URL, purpose, and bounds;
8. returns an `AssetRef` with the new stable href.

Use this filename implementation:

```python
digest = hashlib.sha256(
    f"{asset.source_url}|{spec.purpose}|{spec.max_width}x{spec.max_height}".encode(
        "utf-8"
    )
).hexdigest()[:12]
suffix = ".jpg" if output_format == "JPEG" else ".png"
filename = (
    f"{Path(asset.href).stem}-{digest}-{spec.purpose}-"
    f"{spec.max_width}x{spec.max_height}{suffix}"
)
```

If an asset is not a supported raster, return it unchanged from a separate
`stable_passthrough_asset` decision; do not attempt to rasterize audio, fonts, or
other resources.

- [ ] **Step 4: Run stable raster tests and verify GREEN**

```powershell
pytest -q tests/test_kindle_stable.py
```

Expected: all raster metadata and rendering tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add src/scp_epub/kindle_stable.py tests/test_kindle_stable.py
git diff --cached --check
git commit -m "feat: render Kindle Scribe image variants"
```

### Task 4: Page-specific reference planning and decoded-memory budgets

**Files:**
- Modify: `src/scp_epub/kindle.py:684-900`
- Modify: `src/scp_epub/kindle_stable.py`
- Modify: `tests/test_kindle.py`
- Modify: `tests/test_kindle_stable.py`

- [ ] **Step 1: Write failing lossless-reference helper tests**

In `tests/test_kindle.py`, add:

```python
def test_local_image_references_include_href_classes_and_occurrence():
    page = _page(
        '<img class="facility-icon-epub image" src="../assets/site.png" alt="S" />'
        '<img src="../assets/site.png" alt="large" />'
    )

    references = local_image_references(page)

    assert [(ref.href, ref.classes, ref.occurrence) for ref in references] == [
        ("assets/site.png", frozenset({"facility-icon-epub", "image"}), 0),
        ("assets/site.png", frozenset(), 1),
    ]


def test_rewrite_page_image_references_changes_only_selected_occurrence():
    page = _page(
        '<img class="facility-icon-epub" src="../assets/site.png" alt="small" />'
        '<img src="../assets/site.png" alt="large" />'
    )

    rewritten = rewrite_page_image_references(
        page,
        {(0, "assets/site.png"): "assets/site-thumb.png"},
    )

    assert '../assets/site-thumb.png" alt="small"' in rewritten.xhtml
    assert '../assets/site.png" alt="large"' in rewritten.xhtml
```

- [ ] **Step 2: Run helper tests and verify RED**

```powershell
pytest -q tests/test_kindle.py -k "local_image_references or selected_occurrence"
```

Expected: imports fail because the public helpers do not exist.

- [ ] **Step 3: Expose lossless image reference and rewrite helpers**

In `src/scp_epub/kindle.py`, add:

```python
@dataclass(frozen=True)
class LocalImageReference:
    href: str
    classes: frozenset[str]
    occurrence: int


def local_image_references(page: ProcessedPage) -> list[LocalImageReference]:
    parser = _parse_asset_references(page.xhtml)
    if parser is None:
        return []
    references = []
    occurrence = 0
    for element in parser.elements:
        if element.tag != "img":
            continue
        attrs = dict(element.attrs)
        href = _local_asset_href(attrs.get("src"))
        if href is None:
            continue
        references.append(
            LocalImageReference(
                href=href,
                classes=frozenset(str(attrs.get("class") or "").split()),
                occurrence=occurrence,
            )
        )
        occurrence += 1
    return references
```

Implement `rewrite_page_image_references(page, replacements)` with the existing
parser and `_replace_attribute_value`, keying edits by `(occurrence, href)`. It must
return the original `ProcessedPage` when no replacements match and must not parse
or reserialize inline SVG.

- [ ] **Step 4: Write failing budget-planner tests**

Add to `tests/test_kindle_stable.py`:

```python
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
```

The helper data must be chosen so estimates are deterministic rather than relying
on encoded file size.

- [ ] **Step 5: Run budget tests and verify RED**

```powershell
pytest -q tests/test_kindle_stable.py -k "plan_"
```

Expected: failures because planning structures and functions do not exist.

- [ ] **Step 6: Implement planning and stable preparation**

Add these constants and structures to `kindle_stable.py`:

```python
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


class KindleStabilityError(RuntimeError):
    pass


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
```

`plan_stable_variants` must:

1. inspect every referenced raster asset once;
2. assign `FACILITY_SPEC` to references with `facility-icon-epub` and
   `ORDINARY_SPEC` to other images;
3. estimate each page using unique `(href, spec)` pairs;
4. if above target, retry all ordinary references on that page with each adaptive
   spec in order and select the first estimate at or below target;
5. accept the minimum adaptive spec with a warning when at or below the hard limit;
6. collect all pages still above the hard limit and raise one
   `KindleStabilityError` listing their slugs and MiB values;
7. return a plan that can answer `spec_for(slug, occurrence)` and contains the
   per-page performance records.

Implement:

```python
@dataclass(frozen=True)
class StableKindleResult:
    pages: list[ProcessedPage]
    assets: list[AssetRef]
    missing_assets: list[str]
    performance: dict[str, object]


def prepare_stable_kindle_assets(
    pages: Sequence[ProcessedPage],
    assets: Sequence[AssetRef],
    output_dir: Path,
    missing_assets: Sequence[str] = (),
) -> StableKindleResult:
```

This function plans first, renders each unique `(source href, StableVariantSpec)`
once, rewrites each page occurrence through `rewrite_page_image_references`, keeps
non-raster assets unchanged, and returns only assets referenced by stable pages
plus required non-image resources. If rendering fails, remove that image using the
existing Kindle missing-image behavior and append its source URL once.

The performance dictionary must contain:

```python
{
    "profile": "kindle-scribe-300ppi",
    "target_decode_bytes": TARGET_DECODE_BYTES,
    "hard_decode_bytes": HARD_DECODE_BYTES,
    "before_decode_bytes": sum(item.before_decode_bytes for item in pages),
    "after_decode_bytes": sum(item.after_decode_bytes for item in pages),
    "animated_gifs_made_static": animated_count,
    "thumbnail_variant_count": thumbnail_count,
    "adaptive_variant_count": adaptive_count,
    "pages": [
        item.as_dict()
        for item in page_performance
        if item.after_decode_bytes > 32 * MIB
    ],
    "warnings": [item.slug for item in page_performance if item.warning],
}
```

- [ ] **Step 7: Run Kindle helper and stable planner tests and verify GREEN**

```powershell
pytest -q tests/test_kindle.py tests/test_kindle_stable.py
```

Expected: all tests pass; high-quality Kindle byte-preservation tests remain green.

- [ ] **Step 8: Commit Task 4**

```powershell
git add src/scp_epub/kindle.py src/scp_epub/kindle_stable.py tests/test_kindle.py tests/test_kindle_stable.py
git diff --cached --check
git commit -m "feat: enforce Kindle Scribe page image budgets"
```

### Task 5: Pipeline integration, stable report, and atomic failure behavior

**Files:**
- Modify: `src/scp_epub/pipeline.py:287-340, 892-900`
- Modify: `src/scp_epub/epub.py:873-920`
- Modify: `tests/test_pipeline.py:2390-2676`
- Modify: `tests/test_epub.py:673-808`

- [ ] **Step 1: Write failing report payload test**

Add to `tests/test_epub.py`:

```python
def test_write_build_report_includes_optional_kindle_performance(tmp_path: Path):
    report_path = tmp_path / "reports" / "stable.json"
    performance = {
        "profile": "kindle-scribe-300ppi",
        "target_decode_bytes": 64 * 1024 * 1024,
        "hard_decode_bytes": 96 * 1024 * 1024,
        "pages": [],
        "warnings": [],
    }

    write_build_report(
        report_path,
        pages=[_page("scp-001", "SCP-001", 1)],
        output_path=tmp_path / "stable.epub",
        kindle_performance=performance,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["kindle_performance"] == performance


def test_write_build_report_omits_unsupplied_kindle_performance(tmp_path: Path):
    report_path = tmp_path / "reports" / "ordinary.json"
    write_build_report(
        report_path,
        pages=[_page("scp-001", "SCP-001", 1)],
        output_path=tmp_path / "ordinary.epub",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "kindle_performance" not in report
```

- [ ] **Step 2: Run report tests and verify RED**

```powershell
pytest -q tests/test_epub.py -k "kindle_performance"
```

Expected: unexpected keyword failure for `kindle_performance`.

- [ ] **Step 3: Add optional report payload**

Extend `write_build_report` with:

```python
kindle_performance: dict[str, object] | None = None,
```

After the base report is created, add:

```python
if kindle_performance is not None:
    report["kindle_performance"] = kindle_performance
```

- [ ] **Step 4: Write failing stable pipeline test**

Add a pipeline test that builds a page containing one 4000 by 3000 JPEG and one
4500 by 4500 `facility-icon-epub` PNG. The fake converter must inspect the EPUB
before writing its AZW3 marker. Assert:

```python
assert output_path == config.output_dir / "epub" / "test-volume-Kindle-Scribe.epub"
assert conversion_calls == [
    (
        output_path,
        config.output_dir / "azw3" / "test-volume-Kindle-Scribe.azw3",
    )
]
assert (config.processed_dir / "test-volume" / "kindle-stable-assets").is_dir()
assert not (config.output_dir / "epub" / "test-volume-Kindle.epub").exists()

report = json.loads(
    (config.output_dir / "reports" / "test-volume-Kindle-Scribe-report.json")
    .read_text(encoding="utf-8")
)
assert report["kindle_performance"]["profile"] == "kindle-scribe-300ppi"
assert report["kindle_performance"]["after_decode_bytes"] < report[
    "kindle_performance"
]["before_decode_bytes"]
```

Inside the EPUB, assert the ordinary JPEG is at most 1800 by 2400 and the facility
PNG is at most 384 by 384.

- [ ] **Step 5: Run the stable pipeline test and verify RED**

```powershell
pytest -q tests/test_pipeline.py -k "kindle_stable"
```

Expected: failure because stable asset preparation is not connected.

- [ ] **Step 6: Integrate stable preparation in `build_volume`**

Use this flow:

```python
kindle_performance = None
if build_mode.is_kindle:
    kindle_pages = prepare_kindle_pages(
        localized_pages,
        stable=build_mode is BuildMode.KINDLE_STABLE,
    )
    prepared_pages, prepared_assets, missing_assets = prepare_kindle_assets(
        kindle_pages,
        localized_assets,
        config.processed_dir / volume.output_slug / "kindle-assets",
        missing_assets,
    )
    if build_mode is BuildMode.KINDLE_STABLE:
        stable = prepare_stable_kindle_assets(
            prepared_pages,
            prepared_assets,
            config.processed_dir / volume.output_slug / "kindle-stable-assets",
            missing_assets,
        )
        output_pages = stable.pages
        output_assets = stable.assets
        missing_assets = stable.missing_assets
        kindle_performance = stable.performance
    else:
        output_pages = prepared_pages
        output_assets = prepared_assets
else:
    output_pages = localized_pages
    output_assets = localized_assets
```

Pass `kindle_performance=kindle_performance` to `write_build_report`. Pass the
selected `build_mode` to `kindle_azw3_path_for_volume`.

The stable planner must execute before `write_epub`; its hard-limit exception must
therefore leave existing stable EPUB/report/AZW3 files untouched. Add a test that
precreates all three files, forces `KindleStabilityError`, and asserts their bytes
are unchanged.

- [ ] **Step 7: Run report and pipeline Kindle tests and verify GREEN**

```powershell
pytest -q tests/test_epub.py tests/test_pipeline.py -k "kindle or report"
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit Task 5 without staging pre-existing pipeline hunks**

```powershell
git add src/scp_epub/epub.py tests/test_epub.py tests/test_pipeline.py
git add -p src/scp_epub/pipeline.py
git diff --cached --check
git commit -m "feat: integrate Kindle Scribe stability reporting"
```

Stage only Task 5 stable pipeline/report hunks from `pipeline.py`.

### Task 6: Documentation, complete regression suite, and Featured artifact audit

**Files:**
- Modify: `README.md:82-109, 302-304`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_kindle_stable.py`

- [ ] **Step 1: Document the stable command and exact outputs**

Add a README subsection after the existing Kindle build section:

```markdown
### 构建 Kindle Scribe 稳定版

稳定版会限制图片像素尺寸、将动态图静态化，并按单篇 XHTML 的预计图片解码
内存选择页面专用图片变体。现有 `--kindle` 高清版不会被覆盖。

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

生成：

```text
output/epub/SCP基金会档案精选-Kindle-Scribe.epub
output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3
output/reports/SCP基金会档案精选-Kindle-Scribe-report.json
```

设施卡片图标最大为 384×384；普通图片最大为 1800×2400。构建以64 MiB为
单篇目标、96 MiB为硬上限。若最低稳定尺寸仍超过硬上限，命令会停止并保留已有
稳定版产物。
```

- [ ] **Step 2: Run focused test files**

```powershell
pytest -q tests/test_kindle_stable.py tests/test_kindle.py tests/test_cli.py tests/test_pipeline.py tests/test_epub.py
```

Expected: all focused tests pass with zero failures.

- [ ] **Step 3: Run the complete suite**

```powershell
pytest -q
```

Expected: all repository tests pass with zero failures.

- [ ] **Step 4: Build the Featured stable artifacts**

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

Expected output:

```text
Wrote ...\output\epub\SCP基金会档案精选-Kindle-Scribe.epub
Wrote ...\output\azw3\SCP基金会档案精选-Kindle-Scribe.azw3
```

- [ ] **Step 5: Audit the generated EPUB and report**

Run a Python ZIP/Pillow audit that asserts:

```python
assert facilities_table_count == 2
assert facilities_card_count == 92
assert facilities_icon_count == 91
assert facility_child_count == 40
assert facilities_decode_bytes <= 64 * 1024 * 1024
assert max_page_decode_bytes <= 96 * 1024 * 1024
assert missing_packaged_image_references == []
assert incomplete_facility_labels == []
assert stable_epub.stat().st_size > 0
assert stable_azw3.stat().st_size > 0
assert high_quality_epub.exists()
assert high_quality_azw3.exists()
```

Also verify:

```powershell
ebook-meta output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3
```

Expected metadata: title `SCP基金会档案精选`, author `SCP基金会`, language `zho`.

- [ ] **Step 6: Review the stable performance report**

Confirm these report conditions:

```python
performance["profile"] == "kindle-scribe-300ppi"
performance["after_decode_bytes"] < performance["before_decode_bytes"]
all(page["after_decode_bytes"] <= 96 * 1024 * 1024 for page in performance["pages"])
```

Record any 64-to-96 MiB warning slugs in the handoff. Existing unrelated
`missing_assets` entries must be reported separately rather than treated as a
stable-image regression.

- [ ] **Step 7: Commit documentation and final test adjustments**

```powershell
git add README.md tests/test_cli.py tests/test_pipeline.py tests/test_kindle_stable.py
git diff --cached --check
git commit -m "docs: document Kindle Scribe stable build"
```

- [ ] **Step 8: Confirm the remaining worktree contains only pre-existing user changes**

```powershell
git status --short
```

Expected remaining modifications:

```text
 M src/scp_epub/fetcher.py
 M src/scp_epub/pipeline.py
 M tests/test_fetcher.py
```

`pipeline.py` remains listed only if its pre-existing worker-related hunks were
correctly excluded from the feature commits.
