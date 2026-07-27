# Kindle Scribe Location Badge Thumbnails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate dedicated 320×320 grayscale variants for badge images on `locations-of-interest` while preserving map resolution, page markup, and all non-stable build behavior.

**Architecture:** Extend the existing lightweight asset-reference parser to expose ancestor class metadata without rewriting XHTML. The Kindle Scribe stable planner uses page slug plus ancestor classes to select a fixed `location-badge` variant, protects that spec from adaptive resizing, and reports the number of unique rendered badge variants.

**Tech Stack:** Python 3.11+, standard-library `html.parser`, Pillow, existing EPUB/Kindle pipeline, pytest, Calibre `ebook-convert`.

---

## File Structure

- Modify `src/scp_epub/kindle.py`: add ancestor-class metadata to `LocalImageReference` using the parser's existing parent chain.
- Modify `src/scp_epub/kindle_stable.py`: classify location badges, assign the 320×320 spec, preserve fixed specs during adaptive planning, and report variant counts.
- Modify `tests/test_kindle.py`: verify direct and ancestor classes remain distinct and occurrence order is stable.
- Modify `tests/test_kindle_stable.py`: verify context matching, page scoping, map preservation, adaptive behavior, deduplication, estimates, and report output.
- Modify `tests/test_pipeline.py`: verify the stable report always exposes the new count without changing output paths.
- Rebuild ignored artifacts under `output/` and audit the Featured Kindle Scribe EPUB/AZW3.

### Task 1: Expose ancestor classes on local image references

**Files:**
- Modify: `tests/test_kindle.py:1228-1241`
- Modify: `src/scp_epub/kindle.py:694-699, 817-839`

- [ ] **Step 1: Change the parser test to specify ancestor metadata**

Replace `test_local_image_references_include_href_classes_and_occurrence` with:

```python
def test_local_image_references_include_direct_and_ancestor_classes():
    page = _page(
        '<div class="map-shell outer">'
        '<div class="enlarge">'
        '<img class="image badge" src="../assets/site.png" alt="S" />'
        "</div>"
        "</div>"
        '<img src="../assets/site.png" alt="large" />'
    )

    references = local_image_references(page)

    assert [
        (ref.href, ref.classes, ref.ancestor_classes, ref.occurrence)
        for ref in references
    ] == [
        (
            "assets/site.png",
            frozenset({"image", "badge"}),
            frozenset({"map-shell", "outer", "enlarge"}),
            0,
        ),
        ("assets/site.png", frozenset(), frozenset(), 1),
    ]
```

- [ ] **Step 2: Run the test and verify the field does not exist yet**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q tests/test_kindle.py::test_local_image_references_include_direct_and_ancestor_classes
```

Expected: FAIL with `AttributeError` for `ancestor_classes`.

- [ ] **Step 3: Add ancestor metadata to the dataclass**

Change `LocalImageReference` to:

```python
@dataclass(frozen=True)
class LocalImageReference:
    href: str
    classes: frozenset[str]
    ancestor_classes: frozenset[str]
    occurrence: int
```

- [ ] **Step 4: Collect ancestor class tokens from the existing parent chain**

Inside `local_image_references`, immediately before appending a reference, add:

```python
ancestor_classes: set[str] = set()
ancestor = element.parent
while ancestor is not None:
    ancestor_attrs = dict(ancestor.attrs)
    ancestor_classes.update(
        str(ancestor_attrs.get("class") or "").split()
    )
    ancestor = ancestor.parent
```

Then add this constructor argument:

```python
ancestor_classes=frozenset(ancestor_classes),
```

- [ ] **Step 5: Run focused parser and rewrite tests**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q tests/test_kindle.py -k "local_image_references or rewrite_page_image_references"
```

Expected: all selected tests pass and occurrence-based rewriting remains unchanged.

- [ ] **Step 6: Commit the parser metadata change**

```powershell
git add -- tests/test_kindle.py src/scp_epub/kindle.py
git commit -m "feat: expose image ancestor classes"
```

### Task 2: Select fixed 320-pixel location badge variants

**Files:**
- Modify: `tests/test_kindle_stable.py`
- Modify: `src/scp_epub/kindle_stable.py:35-48, 145-220`

- [ ] **Step 1: Add a context-selection test covering all accepted and rejected cases**

Add:

```python
def test_plan_uses_location_badge_spec_only_for_matching_page_contexts(
    tmp_path: Path,
):
    assets = [
        _large_png_asset(tmp_path, f"image-{index}.png", (1200, 1200))
        for index in range(6)
    ]
    page = _page(
        "locations-of-interest",
        f'<div class="enlarge"><img src="../{assets[0].href}" /></div>'
        f'<div class="legend-box"><p><img src="../{assets[1].href}" /></p></div>'
        f'<div class="image-container floatright"><img src="../{assets[2].href}" /></div>'
        f'<div class="mainmap"><img src="../{assets[3].href}" /></div>'
        f'<div class="secmap"><img src="../{assets[4].href}" /></div>'
        f'<p><img src="../{assets[5].href}" /></p>',
    )
    other_page = _page(
        "another-page",
        f'<div class="enlarge"><img src="../{assets[0].href}" /></div>',
    )

    plan = plan_stable_variants([page, other_page], assets)

    for occurrence in range(3):
        assert plan.spec_for("locations-of-interest", occurrence) == (
            StableVariantSpec("location-badge", 320, 320)
        )
    for occurrence in range(3, 6):
        assert plan.spec_for("locations-of-interest", occurrence).purpose != (
            "location-badge"
        )
    assert plan.spec_for("another-page", 0).purpose != "location-badge"
```

- [ ] **Step 2: Add an adaptive-planning regression test**

```python
def test_adaptive_planning_does_not_expand_location_badges(tmp_path: Path):
    badge = _large_png_asset(tmp_path, "badge.png", (3000, 3000))
    ordinary = [
        _large_png_asset(tmp_path, f"ordinary-{index}.png", (3000, 3000))
        for index in range(12)
    ]
    page = _page(
        "locations-of-interest",
        f'<div class="enlarge"><img src="../{badge.href}" /></div>'
        + "".join(
            f'<img src="../{asset.href}" />' for asset in ordinary
        ),
    )

    plan = plan_stable_variants([page], [badge, *ordinary])

    assert plan.spec_for("locations-of-interest", 0) == StableVariantSpec(
        "location-badge", 320, 320
    )
    assert plan.spec_for("locations-of-interest", 1).purpose == "adaptive"
    assert plan.page_performance[0].after_decode_bytes <= 64 * MIB
```

- [ ] **Step 3: Run both tests and verify badge references currently use ordinary/adaptive specs**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q tests/test_kindle_stable.py -k "location_badge_spec or does_not_expand_location_badges"
```

Expected: both tests fail because no `location-badge` spec exists.

- [ ] **Step 4: Add the fixed spec and context predicate**

Add beside `FACILITY_SPEC`:

```python
LOCATION_BADGE_SPEC = StableVariantSpec("location-badge", 320, 320)
```

Add `LocalImageReference` to the existing import list from `.kindle`, then add
before `plan_stable_variants`:

```python
def _is_location_badge(
    slug: str, reference: LocalImageReference
) -> bool:
    if slug != "locations-of-interest":
        return False
    ancestor_classes = reference.ancestor_classes
    return (
        "enlarge" in ancestor_classes
        or "legend-box" in ancestor_classes
        or {"image-container", "floatright"} <= ancestor_classes
    )
```

- [ ] **Step 5: Apply explicit spec precedence during initial planning**

Replace the current two-way assignment with:

```python
if "facility-icon-epub" in reference.classes:
    spec = FACILITY_SPEC
elif _is_location_badge(slug, reference):
    spec = LOCATION_BADGE_SPEC
else:
    spec = ORDINARY_SPEC
reference_specs[(slug, reference.occurrence)] = spec
```

- [ ] **Step 6: Protect both fixed thumbnail specs from the adaptive loop**

Define fixed specs inside the page loop:

```python
fixed_specs = {FACILITY_SPEC, LOCATION_BADGE_SPEC}
```

Change `has_ordinary` to:

```python
has_ordinary = any(
    reference_specs[(slug, reference.occurrence)] not in fixed_specs
    for reference in references
)
```

Inside each adaptive iteration, replace the class-only guard with:

```python
if reference_specs[key] not in fixed_specs:
    reference_specs[key] = adaptive_spec
```

For pages containing only fixed variants, choose the largest fixed spec for the
reported bound:

```python
elif references and not has_ordinary:
    selected_spec = max(
        (
            reference_specs[(slug, reference.occurrence)]
            for reference in references
        ),
        key=lambda spec: (spec.max_width * spec.max_height, spec.purpose),
    )
```

- [ ] **Step 7: Run all stable planning tests**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q tests/test_kindle_stable.py -k "plan or location_badge"
```

Expected: all selected tests pass, including facility priority and hard-budget behavior.

- [ ] **Step 8: Commit planning behavior and tests**

```powershell
git add -- tests/test_kindle_stable.py src/scp_epub/kindle_stable.py
git commit -m "feat: plan 320px location badge variants"
```

### Task 3: Deduplicate and report generated location badge variants

**Files:**
- Modify: `tests/test_kindle_stable.py`
- Modify: `src/scp_epub/kindle_stable.py:270-370`

- [ ] **Step 1: Add a preparation/report test with a repeated badge**

```python
def test_prepare_stable_assets_deduplicates_and_reports_location_badges(
    tmp_path: Path,
):
    badge = _large_png_asset(tmp_path, "badge.png", (1200, 1200))
    map_asset = _large_png_asset(tmp_path, "map.png", (1200, 800))
    page = _page(
        "locations-of-interest",
        f'<div class="enlarge"><img src="../{badge.href}" /></div>'
        f'<div class="legend-box"><img src="../{badge.href}" /></div>'
        f'<div class="mainmap"><img src="../{map_asset.href}" /></div>',
    )

    result = prepare_stable_kindle_assets(
        [page],
        [badge, map_asset],
        tmp_path / "stable-assets",
    )

    badge_assets = [
        asset for asset in result.assets
        if "gray-location-badge-320x320" in asset.href
    ]
    assert len(badge_assets) == 1
    with Image.open(badge_assets[0].path) as image:
        assert image.size == (320, 320)
        assert image.mode == "L"
    assert result.performance["location_badge_variant_count"] == 1
    assert result.performance["warnings"] == []
```

- [ ] **Step 2: Run the test and verify the report key is missing**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q tests/test_kindle_stable.py::test_prepare_stable_assets_deduplicates_and_reports_location_badges
```

Expected: FAIL with `KeyError: 'location_badge_variant_count'` after the variant itself is generated correctly.

- [ ] **Step 3: Add the report count from successful rendered requests**

Add to the `performance` dictionary:

```python
"location_badge_variant_count": sum(
    1
    for _href, spec in rendered_requests
    if spec.purpose == "location-badge"
),
```

This counts unique successful requests because `rendered_requests` contains the
deduplicated `(href, spec)` keys from `rendered`.

- [ ] **Step 4: Add a current-page-scale estimate test**

```python
def test_location_badge_policy_brings_representative_page_below_target(
    tmp_path: Path,
):
    badges = [
        _large_png_asset(tmp_path, f"badge-{index}.png", (800, 800))
        for index in range(46)
    ]
    maps = [
        _large_png_asset(tmp_path, f"map-{index}.png", (800, 600))
        for index in range(5)
    ]
    page = _page(
        "locations-of-interest",
        "".join(
            f'<div class="image-container floatright"><img src="../{asset.href}" /></div>'
            for asset in badges
        )
        + "".join(
            f'<div class="mainmap"><img src="../{asset.href}" /></div>'
            for asset in maps
        ),
    )

    plan = plan_stable_variants([page], [*badges, *maps])
    performance = plan.page_performance[0]

    assert performance.after_decode_bytes < 64 * MIB
    assert performance.warning is False
    assert plan.warnings == ()
```

- [ ] **Step 5: Run the complete stable test module**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q tests/test_kindle_stable.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit report behavior and coverage**

```powershell
git add -- tests/test_kindle_stable.py src/scp_epub/kindle_stable.py
git commit -m "feat: report location badge variants"
```

### Task 4: Verify pipeline integration and build-mode isolation

**Files:**
- Modify: `tests/test_pipeline.py:2496-2582`

- [ ] **Step 1: Assert the general stable build reports zero location badges**

In `test_build_volume_kindle_stable_writes_scribe_variants_and_report`, add:

```python
assert performance["location_badge_variant_count"] == 0
```

This fixture contains a facility icon and an ordinary image but no
`locations-of-interest` page, proving the field is present and page-scoped.

- [ ] **Step 2: Run the stable pipeline integration test**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q tests/test_pipeline.py::test_build_volume_kindle_stable_writes_scribe_variants_and_report
```

Expected: PASS with unchanged `-Kindle-Scribe` EPUB/AZW3/report paths.

- [ ] **Step 3: Run Kindle, EPUB, CLI, and pipeline regression modules**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q tests/test_kindle.py tests/test_kindle_stable.py tests/test_cli.py tests/test_epub.py tests/test_pipeline.py
```

Expected: all tests pass; ordinary EPUB and current `--kindle` behavior remain unchanged.

- [ ] **Step 4: Commit the pipeline assertion**

```powershell
git add -- tests/test_pipeline.py
git commit -m "test: verify location badge report integration"
```

### Task 5: Run full verification, rebuild, and audit the Featured artifacts

**Files:**
- Generated, ignored: `output/epub/SCP基金会档案精选-Kindle-Scribe.epub`
- Generated, ignored: `output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3`
- Generated, ignored: `output/reports/SCP基金会档案精选-Kindle-Scribe-report.json`

- [ ] **Step 1: Record current grayscale artifact sizes and page estimate**

Run:

```powershell
Get-Item 'output/epub/SCP基金会档案精选-Kindle-Scribe.epub','output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3' |
  Select-Object FullName,Length
$report = Get-Content -Raw 'output/reports/SCP基金会档案精选-Kindle-Scribe-report.json' | ConvertFrom-Json
$report.kindle_performance.pages | Where-Object slug -eq 'locations-of-interest'
```

Expected baseline: EPUB 120,054,893 bytes, AZW3 123,242,304 bytes, and the page estimate approximately 90,545,036 bytes with a warning.

- [ ] **Step 2: Run the complete test suite**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Rebuild the Featured Kindle Scribe edition**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

Expected: EPUB, AZW3, and stable report are regenerated successfully.

- [ ] **Step 4: Audit the rebuilt `locations-of-interest` XHTML and assets**

Run a read-only Python audit which opens the EPUB and:

```python
import json
import posixpath
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree
from zipfile import ZipFile

from bs4 import BeautifulSoup
from PIL import Image

epub_path = Path("output/epub/SCP基金会档案精选-Kindle-Scribe.epub")
with ZipFile(epub_path) as archive:
    names = set(archive.namelist())
    page_name = next(
        name for name in names if name.endswith("locations-of-interest.xhtml")
    )
    payload = archive.read(page_name)
    ElementTree.fromstring(payload)
    soup = BeautifulSoup(payload, "xml")
    badge_assets = set()
    map_assets = set()
    page_assets = set()
    unresolved = []
    for image in soup.find_all("img"):
        src = image.get("src")
        if not src:
            continue
        parsed = urlsplit(src)
        target = posixpath.normpath(
            posixpath.join(posixpath.dirname(page_name), unquote(parsed.path))
        )
        if target not in names:
            unresolved.append((page_name, src))
            continue
        page_assets.add(target)
        if "gray-location-badge-320x320" in target:
            badge_assets.add(target)
        if "map-" in str(image.get("alt", "")).casefold():
            map_assets.add(target)
    assert not unresolved, unresolved[:10]
    assert len(badge_assets) == 46, len(badge_assets)
    assert all("location-badge" not in target for target in map_assets)
    decoded_bytes = 0
    for target in page_assets:
        with Image.open(BytesIO(archive.read(target))) as raster:
            decoded_bytes += raster.width * raster.height * 4
    for target in badge_assets:
        with Image.open(BytesIO(archive.read(target))) as raster:
            assert raster.width <= 320 and raster.height <= 320
            assert raster.mode in {"L", "LA"}
    assert decoded_bytes < 64 * 1024 * 1024, decoded_bytes
    print(decoded_bytes)
```

Expected: 46 unique badge variants, all at most 320×320 and grayscale; maps do not use the badge spec; all references resolve; the packaged page's unique-image decode estimate is below 64 MiB.

- [ ] **Step 5: Verify report improvement and final artifact sizes**

Run:

```powershell
$report = Get-Content -Raw 'output/reports/SCP基金会档案精选-Kindle-Scribe-report.json' | ConvertFrom-Json
$performance = $report.kindle_performance
$performance.location_badge_variant_count
$performance.warnings
Get-Item 'output/epub/SCP基金会档案精选-Kindle-Scribe.epub','output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3' |
  Select-Object FullName,Length
```

Expected: count is 46 and `locations-of-interest` is absent from warnings. The preceding EPUB audit proves its estimated decoded bytes are below 67,108,864. Both artifacts are nonempty; report before/after sizes.

- [ ] **Step 6: Confirm only the user's existing unrelated modifications remain uncommitted**

Run:

```powershell
git status --short
```

Expected: only the pre-existing changes to `src/scp_epub/fetcher.py`, `src/scp_epub/pipeline.py`, and `tests/test_fetcher.py` remain. Generated `output/` files stay ignored.
