# Kindle Scribe Grayscale Image Encoding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Encode all generated Kindle Scribe stable raster variants as grayscale while preserving their existing pixel dimensions, alpha channel, page structure, and non-stable build behavior.

**Architecture:** Keep grayscale conversion entirely inside `src/scp_epub/kindle_stable.py`, after EXIF orientation and stable resizing but before JPEG/PNG encoding. Extend stable image inspection with a transparency flag so the existing preparation stage can report grayscale and grayscale-alpha variant counts without reopening output files; retain the current conservative four-byte-per-pixel decode model.

**Tech Stack:** Python 3.11+, Pillow, BeautifulSoup-backed existing EPUB pipeline, pytest, Calibre `ebook-convert` for final AZW3 verification.

---

## File Structure

- Modify `src/scp_epub/kindle_stable.py`: detect first-frame transparency, convert stable raster frames to `L`/`LA`, distinguish grayscale variant filenames, and expose report metadata.
- Modify `tests/test_kindle_stable.py`: specify grayscale JPEG, opaque PNG, transparent PNG, GIF, filename, alpha preservation, and report behavior.
- Modify `tests/test_pipeline.py`: verify the stable build report carries the encoding profile while the existing Kindle Scribe output path remains unchanged.
- Rebuild and audit `output/epub/SCP基金会档案精选-Kindle-Scribe.epub`, `output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3`, and the stable report; generated artifacts remain untracked.

### Task 1: Specify grayscale raster rendering

**Files:**
- Modify: `tests/test_kindle_stable.py:114-187`

- [ ] **Step 1: Change the JPEG expectation to grayscale and a profile-specific filename**

Replace the assertions in `test_render_stable_variant_bounds_jpeg_and_uses_quality_85` with:

```python
assert prepared.href.endswith("-gray-ordinary-1800x2400.jpg")
with Image.open(prepared.path) as image:
    assert image.size == (1800, 1350)
    assert image.mode == "L"
    assert image.format == "JPEG"
    assert image.info.get("progressive", 0) == 0
```

- [ ] **Step 2: Add an opaque PNG grayscale test**

```python
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
```

- [ ] **Step 3: Strengthen the transparent PNG test to require `LA` and preserved partial alpha**

Replace `test_render_stable_variant_preserves_png_transparency` with:

```python
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
```

- [ ] **Step 4: Change the animated GIF assertion to require a grayscale first frame**

Add these assertions to `test_render_stable_variant_freezes_animated_gif_to_first_frame`:

```python
assert image.mode == "L"
assert image.getpixel((0, 0)) == 76
```

The expected luminance `76` is Pillow's conversion of pure red `(255, 0, 0)`.

- [ ] **Step 5: Run the rendering tests and verify they fail against RGB/RGBA output**

Run:

```powershell
pytest -q tests/test_kindle_stable.py -k "render_stable_variant"
```

Expected: failures showing current JPEG/PNG modes are `RGB` or `RGBA`, and generated filenames lack `gray`.

- [ ] **Step 6: Commit the failing tests**

```powershell
git add -- tests/test_kindle_stable.py
git commit -m "test: specify grayscale Scribe image variants"
```

### Task 2: Implement grayscale conversion and variant identity

**Files:**
- Modify: `src/scp_epub/kindle_stable.py:364-425`

- [ ] **Step 1: Add the stable image profile constant and conversion helper**

Add near the existing format constants:

```python
IMAGE_ENCODING_PROFILE = "grayscale-preserve-alpha"
```

Add before `render_stable_variant`:

```python
def _frame_has_transparency(frame: Image.Image) -> bool:
    return "A" in frame.getbands() or "transparency" in frame.info


def _convert_frame_to_grayscale(frame: Image.Image) -> Image.Image:
    if not _frame_has_transparency(frame):
        return frame.convert("L")
    rgba = frame.convert("RGBA")
    luminance = rgba.convert("RGB").convert("L")
    return Image.merge("LA", (luminance, rgba.getchannel("A")))
```

- [ ] **Step 2: Replace RGB/RGBA normalization with grayscale conversion**

In `render_stable_variant`, keep JPEG versus PNG selection unchanged and replace:

```python
if output_format == "JPEG":
    frame = frame.convert("RGB")
elif frame.mode not in {"RGB", "RGBA"}:
    frame = frame.convert("RGBA" if "transparency" in frame.info else "RGB")
```

with:

```python
frame = _convert_frame_to_grayscale(frame)
if output_format == "JPEG" and frame.mode == "LA":
    frame = frame.getchannel("L")
```

JPEG/MPO sources should normally be opaque; the defensive `LA` branch guarantees Pillow never receives alpha for JPEG output.

- [ ] **Step 3: Make filenames and digests encoding-profile-specific**

Change the digest input to:

```python
digest = hashlib.sha256(
    (
        f"{asset.source_url}|{IMAGE_ENCODING_PROFILE}|{spec.purpose}|"
        f"{spec.max_width}x{spec.max_height}"
    ).encode("utf-8")
).hexdigest()[:12]
```

Change the filename to:

```python
filename = (
    f"{Path(asset.href).stem}-{digest}-gray-{spec.purpose}-"
    f"{spec.max_width}x{spec.max_height}{suffix}"
)
```

- [ ] **Step 4: Run the focused rendering tests**

Run:

```powershell
pytest -q tests/test_kindle_stable.py -k "render_stable_variant"
```

Expected: all selected tests pass, including `L`, `LA`, alpha preservation, first-frame GIF, EXIF orientation, and MPO output.

- [ ] **Step 5: Commit the implementation**

```powershell
git add -- src/scp_epub/kindle_stable.py
git commit -m "feat: encode Scribe image variants as grayscale"
```

### Task 3: Report grayscale profile and variant counts

**Files:**
- Modify: `tests/test_kindle_stable.py`
- Modify: `src/scp_epub/kindle_stable.py:38-50, 120-145, 262-357`

- [ ] **Step 1: Add a preparation helper import and report test**

Add `prepare_stable_kindle_assets` to the imports from `scp_epub.kindle_stable`, then add:

```python
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
```

- [ ] **Step 2: Run the report test and verify the new keys are missing**

Run:

```powershell
pytest -q tests/test_kindle_stable.py::test_prepare_stable_assets_reports_grayscale_variants
```

Expected: FAIL with `KeyError: 'image_encoding_profile'`.

- [ ] **Step 3: Extend inspected image metadata with first-frame transparency**

Add this field to `StableImageInfo`:

```python
has_transparency: bool
```

In `inspect_stable_image`, seek to the first frame before returning and populate it:

```python
image.seek(0)
has_transparency = _frame_has_transparency(image)
return StableImageInfo(
    href=asset.href,
    width=width,
    height=height,
    frame_count=int(getattr(image, "n_frames", 1)),
    format_name=format_name,
    has_transparency=has_transparency,
)
```

Keep the existing EXIF-orientation dimension calculation unchanged.

- [ ] **Step 4: Add report metadata from successfully rendered requests**

Immediately before constructing `performance`, calculate:

```python
rendered_requests = tuple(rendered)
grayscale_alpha_variant_count = sum(
    1
    for href, _spec in rendered_requests
    if plan.image_info_by_href[href].has_transparency
)
```

Add these keys to `performance`:

```python
"image_encoding_profile": IMAGE_ENCODING_PROFILE,
"grayscale_variant_count": len(rendered_requests),
"grayscale_alpha_variant_count": grayscale_alpha_variant_count,
```

- [ ] **Step 5: Run all stable-image tests**

Run:

```powershell
pytest -q tests/test_kindle_stable.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit report coverage and implementation together**

```powershell
git add -- tests/test_kindle_stable.py src/scp_epub/kindle_stable.py
git commit -m "feat: report Scribe grayscale image profile"
```

### Task 4: Verify pipeline integration and non-stable isolation

**Files:**
- Modify: `tests/test_pipeline.py:2496-2578`

- [ ] **Step 1: Assert the Scribe build report exposes the grayscale profile**

In `test_build_volume_kindle_stable_writes_scribe_variants_and_report`, after loading `performance`, add:

```python
assert performance["image_encoding_profile"] == "grayscale-preserve-alpha"
assert performance["grayscale_variant_count"] >= 1
assert performance["grayscale_alpha_variant_count"] >= 0
```

The fixture's stable asset preparation must run normally rather than mocking the report, so these assertions exercise the pipeline boundary.

- [ ] **Step 2: Run the stable pipeline test**

Run:

```powershell
pytest -q tests/test_pipeline.py::test_build_volume_kindle_stable_writes_scribe_variants_and_report
```

Expected: PASS, with the same `-Kindle-Scribe` paths and the additional report keys.

- [ ] **Step 3: Run Kindle and EPUB regression groups**

Run:

```powershell
pytest -q tests/test_kindle.py tests/test_cli.py tests/test_epub.py tests/test_pipeline.py
```

Expected: all tests pass. In particular, ordinary report omission and the existing `--kindle` output naming assertions remain unchanged.

- [ ] **Step 4: Commit the pipeline assertion**

```powershell
git add -- tests/test_pipeline.py
git commit -m "test: verify Scribe grayscale report integration"
```

### Task 5: Run full verification and rebuild the Kindle Scribe artifacts

**Files:**
- Generated, untracked: `output/epub/SCP基金会档案精选-Kindle-Scribe.epub`
- Generated, untracked: `output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3`
- Generated, untracked: `output/reports/SCP基金会档案精选-Kindle-Scribe-report.json`

- [ ] **Step 1: Record current artifact sizes for comparison**

Run:

```powershell
Get-Item output/epub/SCP基金会档案精选-Kindle-Scribe.epub, output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3 |
  Select-Object FullName, Length
```

Expected: both existing files are nonempty; save the byte counts in the execution notes.

- [ ] **Step 2: Run the complete test suite**

Run:

```powershell
pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Rebuild the Featured Kindle Scribe edition**

Run:

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

Expected: the Kindle Scribe EPUB, AZW3, and report are regenerated successfully; standard and `-Kindle` output files are not overwritten.

- [ ] **Step 4: Audit XHTML, image references, raster modes, dimensions, and facilities counts**

Run a read-only Python audit against the rebuilt EPUB which:

```python
from io import BytesIO
import posixpath
from xml.etree import ElementTree
from zipfile import ZipFile

from bs4 import BeautifulSoup
from PIL import Image

epub_path = "output/epub/SCP基金会档案精选-Kindle-Scribe.epub"
allowed_modes = {"L", "LA"}
with ZipFile(epub_path) as archive:
    names = set(archive.namelist())
    xhtml_names = sorted(name for name in names if name.endswith(".xhtml"))
    unresolved = []
    stable_modes = set()
    facility_cards = 0
    facility_icons = 0
    for name in xhtml_names:
        xhtml = archive.read(name)
        ElementTree.fromstring(xhtml)
        soup = BeautifulSoup(xhtml, "xml")
        for image in soup.find_all("img"):
            src = image.get("src")
            if not src:
                continue
            target = posixpath.normpath(
                posixpath.join(posixpath.dirname(name), src)
            )
            if target not in names:
                unresolved.append((name, src))
            if "-gray-" in src and target in names:
                with Image.open(BytesIO(archive.read(target))) as raster:
                    stable_modes.add(raster.mode)
        if "secure-facilities-locations" in name:
            facility_cards += len(soup.select(".facility-card-epub"))
            facility_icons += len(soup.select("img.facility-icon-epub"))
    assert not unresolved, unresolved[:10]
    assert stable_modes <= allowed_modes, stable_modes
    assert facility_cards == 92, facility_cards
    assert facility_icons == 91, facility_icons
```

Expected: no unresolved image references; all `-gray-` assets are `L` or `LA`; facilities retain 92 cards and 91 visible icons. `ElementTree.fromstring` successfully parses every XHTML document before the structural checks run.

- [ ] **Step 5: Verify report metadata and compare final artifact sizes**

Run:

```powershell
python -c "import json, pathlib; p=pathlib.Path('output/reports/SCP基金会档案精选-Kindle-Scribe-report.json'); d=json.loads(p.read_text(encoding='utf-8')); print(d['kindle_performance']['image_encoding_profile'], d['kindle_performance']['grayscale_variant_count'], d['kindle_performance']['grayscale_alpha_variant_count'])"
Get-Item output/epub/SCP基金会档案精选-Kindle-Scribe.epub, output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3 |
  Select-Object FullName, Length
```

Expected: profile is `grayscale-preserve-alpha`, both counts are nonnegative with total variants greater than zero, and both rebuilt artifacts are nonempty. Report the before/after size comparison without claiming grayscale alone reduces decoded pixel memory.

- [ ] **Step 6: Check repository status and leave generated artifacts untracked**

Run:

```powershell
git status --short
```

Expected: only the user's pre-existing modifications to `src/scp_epub/fetcher.py`, `src/scp_epub/pipeline.py`, and `tests/test_fetcher.py` remain; `output/` artifacts do not appear because they are ignored.
