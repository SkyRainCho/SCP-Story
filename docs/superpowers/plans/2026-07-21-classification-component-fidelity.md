# Classification Component Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconstruct the ACS anomaly classification bar and WOED Classified Bar as semantic, responsive EPUB components, report every affected Featured document, and rebuild visually verified normal and Kindle editions.

**Architecture:** `transform_page` will convert the two known source DOM families into canonical XHTML and mark every recognized or malformed component with explicit data attributes. A focused inventory module will aggregate those markers per document for the existing build report. Normal EPUB CSS may use modern responsive layout, while Kindle CSS will use table, block, float, and inline-block primitives only.

**Tech Stack:** Python 3.11+, BeautifulSoup, pytest, EPUB/XHTML/CSS, Calibre `ebook-convert`, Chromium/Playwright for visual verification.

---

## File map

- Modify `src/scp_epub/transform.py`: normalize ACS structure, create a real ACS diamond layout, normalize WOED levels/classes, and mark component status.
- Create `src/scp_epub/classification.py`: aggregate component markers into one inventory record per page and family.
- Modify `src/scp_epub/epub.py`: replace normal EPUB component CSS and serialize inventory records into build reports.
- Modify `src/scp_epub/styles/kindle.css`: render the canonical component structure without Grid, Flexbox, generated semantic content, gradients, transforms, or structural pseudo-classes.
- Modify `src/scp_epub/kindle.py`: retain Kindle-only English clearance labels while relying on canonical transformed structure.
- Modify `tests/test_transform.py`: TDD coverage for both canonicalizers, all WOED levels, fallback behavior, and semantic text/icon preservation.
- Create `tests/test_classification.py`: inventory aggregation and mixed-status coverage.
- Modify `tests/test_epub.py`: normal EPUB CSS and report serialization coverage.
- Modify `tests/test_kindle.py`: KF8 selector restrictions and canonical component preservation.
- Modify `tests/test_pipeline.py`: end-to-end normal/Kindle report coverage without mutating processed XHTML.

### Task 1: Canonicalize ACS structure and status markers

**Files:**
- Modify: `src/scp_epub/transform.py:130-220`
- Modify: `src/scp_epub/transform.py:1135-1210`
- Test: `tests/test_transform.py:860-1180`

- [ ] **Step 1: Write failing tests for the paired lower row and real diamond layout**

Add these tests beside the existing anomaly-bar tests:

```python
def test_anomaly_bar_builds_canonical_lower_row_and_diamond_table():
    html = """
    <html><body><div id="page-content">
      <div class="anom-bar-container item-713 clear-2 safe none dark notice lang-cn">
        <div class="anom-bar">
          <div class="top-box">
            <div class="top-left-box"><span class="number">713</span></div>
            <div class="top-center-box"><div class="bar-one"></div><div class="bar-two"></div></div>
            <div class="top-right-box"><div class="level">等级2</div><div class="clearance"></div></div>
          </div>
          <div class="bottom-box">
            <div class="text-part">
              <div class="main-class"><div class="contain-class"><div class="class-text">Safe</div></div></div>
              <div class="disrupt-class"><div class="class-text">Dark</div></div>
              <div class="risk-class"><div class="class-text">待观察</div></div>
            </div>
            <div class="diamond-part"><div class="danger-diamond">
              <div class="top-icon"></div><div class="right-icon"></div>
              <div class="left-icon"></div><div class="bottom-icon"></div>
            </div></div>
          </div>
        </div>
      </div>
    </div></body></html>
    """

    result = transform_page(page_ref("scp-713"), html, BASE_URL)
    soup = soup_fragment(result.xhtml)
    container = soup.select_one(".anom-bar-container")

    assert container is not None
    assert container["data-epub-classification-family"] == "acs"
    assert container["data-epub-classification-status"] == "normalized"
    lower = container.select_one(".text-part > .anomaly-lower-row")
    assert lower is not None
    assert [tag.get("class", [""])[0] for tag in lower.find_all(recursive=False)] == [
        "disrupt-class",
        "risk-class",
    ]
    table = container.select_one("table.anomaly-diamond-layout")
    assert table is not None
    assert table.select_one("td.anomaly-diamond-top .top-icon .anomaly-diamond-icon")
    assert table.select_one("td.anomaly-diamond-left .left-icon .anomaly-diamond-icon")
    assert table.select_one("td.anomaly-diamond-right .right-icon .anomaly-diamond-icon")
```

Add a preservation test for an incomplete source component:

```python
def test_anomaly_bar_marks_unrecognized_shape_without_dropping_text():
    html = """
    <html><body><div id="page-content">
      <div class="anom-bar-container clear-2 safe">
        <div class="contain-class"><div class="class-text">Safe</div></div>
      </div>
    </div></body></html>
    """

    result = transform_page(page_ref("scp-999"), html, BASE_URL)
    soup = soup_fragment(result.xhtml)
    container = soup.select_one(".anom-bar-container")

    assert container is not None
    assert container["data-epub-classification-family"] == "acs"
    assert container["data-epub-classification-status"] == "unrecognized"
    assert container.get_text(" ", strip=True) == "Safe"
```

Add explicit clearance coverage, including the legitimate level-zero case used by SCP-7646:

```python
@pytest.mark.parametrize(
    ("level", "expected_label"),
    (
        (0, None),
        (1, "公开"),
        (2, "受限"),
        (3, "保密"),
        (4, "机密"),
        (5, "最高机密"),
        (6, "宇宙绝密"),
    ),
)
def test_anomaly_bar_materializes_clearance_levels_zero_through_six(
    level: int,
    expected_label: str | None,
):
    html = f"""
    <html><body><div id="page-content"><div class="anom-bar-container clear-{level}">
      <div class="top-box"><div class="top-left-box"></div><div class="top-center-box"></div>
        <div class="top-right-box"><div class="clearance"></div></div></div>
      <div class="bottom-box"><div class="text-part"><div class="main-class">
        <div class="contain-class"><div class="class-text">Safe</div></div></div></div>
        <div class="diamond-part"><div class="danger-diamond"></div></div></div>
    </div></div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)
    label = soup.select_one(".anomaly-clearance-label")

    assert (label.get_text(strip=True) if label else None) == expected_label
```

- [ ] **Step 2: Run the ACS tests and verify they fail**

Run:

```powershell
pytest -q tests/test_transform.py -k "canonical_lower_row or unrecognized_shape"
```

Expected: both new tests fail because the status attributes, lower wrapper, and diamond table do not exist.

- [ ] **Step 3: Implement canonical ACS helpers**

Add the shared marker constants near the existing anomaly constants:

```python
CLASSIFICATION_FAMILY_ATTRIBUTE = "data-epub-classification-family"
CLASSIFICATION_STATUS_ATTRIBUTE = "data-epub-classification-status"
ACS_REQUIRED_SELECTORS = (
    ".top-box",
    ".top-left-box",
    ".top-center-box",
    ".top-right-box",
    ".bottom-box",
    ".text-part",
    ".main-class",
    ".contain-class",
    ".diamond-part",
    ".danger-diamond",
)
```

Add these helpers before `_normalize_anomaly_classification_bars`:

```python
def _mark_classification_component(tag: Tag, family: str, status: str) -> None:
    tag[CLASSIFICATION_FAMILY_ATTRIBUTE] = family
    tag[CLASSIFICATION_STATUS_ATTRIBUTE] = status


def _has_required_descendants(component: Tag, selectors: tuple[str, ...]) -> bool:
    return all(component.select_one(selector) is not None for selector in selectors)


def _wrap_anomaly_lower_fields(soup: BeautifulSoup, container: Tag) -> None:
    text_part = container.select_one(".text-part")
    if text_part is None or text_part.select_one(":scope > .anomaly-lower-row") is not None:
        return
    fields = [
        field
        for selector in (":scope > .disrupt-class", ":scope > .risk-class")
        if (field := text_part.select_one(selector)) is not None
    ]
    if not fields:
        return
    lower = soup.new_tag("div", attrs={"class": "anomaly-lower-row"})
    for field in fields:
        lower.append(field.extract())
    text_part.append(lower)


def _build_anomaly_diamond_layout(soup: BeautifulSoup, container: Tag) -> None:
    diamond = container.select_one(".danger-diamond")
    if diamond is None or diamond.select_one(":scope > .anomaly-diamond-layout") is not None:
        return
    slots = {
        name: diamond.select_one(f":scope > .{name}-icon")
        for name in ("top", "left", "right", "bottom")
    }
    table = soup.new_tag(
        "table",
        attrs={"class": "anomaly-diamond-layout", "role": "presentation"},
    )
    tbody = soup.new_tag("tbody")
    table.append(tbody)
    for row_slots in ((None, "top", None), ("left", None, "right"), (None, "bottom", None)):
        row = soup.new_tag("tr")
        for slot_name in row_slots:
            class_name = f"anomaly-diamond-{slot_name or 'empty'}"
            cell = soup.new_tag("td", attrs={"class": class_name})
            if slot_name is not None and slots[slot_name] is not None:
                cell.append(slots[slot_name].extract())
            row.append(cell)
        tbody.append(row)
    diamond.append(table)
```

At the end of each live-container iteration in `_normalize_anomaly_classification_bars`, add:

```python
        if not _has_required_descendants(container, ACS_REQUIRED_SELECTORS):
            _mark_classification_component(container, "acs", "unrecognized")
            continue
        _wrap_anomaly_lower_fields(soup, container)
        _build_anomaly_diamond_layout(soup, container)
        _mark_classification_component(container, "acs", "normalized")
```

- [ ] **Step 4: Run focused and existing ACS transform tests**

Run:

```powershell
pytest -q tests/test_transform.py -k "anomaly"
```

Expected: all anomaly transform tests pass.

- [ ] **Step 5: Commit the ACS canonicalization**

```powershell
git add src/scp_epub/transform.py tests/test_transform.py
git commit -m "fix: canonicalize anomaly classification bars"
```

### Task 2: Canonicalize WOED Classified Bars

**Files:**
- Modify: `src/scp_epub/transform.py:320-370`
- Modify: `src/scp_epub/transform.py:1210-1345`
- Test: `tests/test_transform.py`

- [ ] **Step 1: Write failing parameterized tests for levels `lv0` through `lv6`**

```python
@pytest.mark.parametrize("level", range(7))
def test_woed_classified_bar_materializes_real_level_segments(level: int):
    bars = "".join(
        '<div class="classified-bar"><img src="/classified-bar.svg" alt=""/></div>'
        '<div class="image-space"></div>'
        for _ in range(6)
    )
    html = f"""
    <html><body><div id="page-content">
      <div class="scale CN-base Keter">
        <div class="class1"><div class="level-text">LEVEL {level}/1297</div><div class="class-text">CLASSIFIED</div></div>
        <div class="class1image" data-level="lv{level}">{bars}</div>
        <div class="item1 CN"><div class="itemnum CN">项目编号：SCP-1297</div>
          <div class="objclass CN"><div class="obj Keter"><div class="obj-text">Keter</div></div></div>
        </div>
      </div>
    </div></body></html>
    """

    result = transform_page(page_ref("scp-1297"), html, BASE_URL)
    soup = soup_fragment(result.xhtml)
    scale = soup.select_one(".scale")

    assert scale is not None
    assert scale["data-epub-classification-family"] == "woed"
    assert scale["data-epub-classification-status"] == "normalized"
    assert f"woed-level-{level}" in scale.get("class", [])
    assert "woed-class-keter" in scale.get("class", [])
    assert len(scale.select(".woed-level-segment")) == level
    assert scale.select_one(".classified-bar") is None
    assert "/classified-bar.svg" not in result.asset_urls
```

Add malformed-input coverage:

```python
def test_woed_classified_bar_preserves_unknown_level_as_unrecognized():
    html = """
    <html><body><div id="page-content">
      <div class="scale Keter"><div class="class1">CLASSIFIED</div>
        <div class="class1image" data-level="lv9"><div class="classified-bar">bar</div></div>
        <div class="item1"><div class="itemnum">SCP-999</div><div class="objclass"><div class="obj-text">Keter</div></div></div>
      </div>
    </div></body></html>
    """

    result = transform_page(page_ref("scp-999"), html, BASE_URL)
    soup = soup_fragment(result.xhtml)
    scale = soup.select_one(".scale")

    assert scale is not None
    assert scale["data-epub-classification-status"] == "unrecognized"
    assert "CLASSIFIED" in scale.get_text(" ", strip=True)
    assert "SCP-999" in scale.get_text(" ", strip=True)
```

- [ ] **Step 2: Run the WOED tests and verify they fail**

Run:

```powershell
pytest -q tests/test_transform.py -k "woed_classified_bar"
```

Expected: eight tests fail because no WOED canonicalizer or markers exist.

- [ ] **Step 3: Implement WOED normalization**

Add constants:

```python
WOED_LEVEL_RE = re.compile(r"lv([0-6])", re.IGNORECASE)
WOED_REQUIRED_SELECTORS = (
    ".class1",
    ".class1image",
    ".item1",
    ".itemnum",
    ".objclass",
    ".obj-text",
)
WOED_OBJECT_CLASS_NAMES = {
    "safe": "safe",
    "euclid": "euclid",
    "keter": "keter",
    "thaumiel": "thaumiel",
    "neutralized": "neutralized",
    "neutralised": "neutralized",
}
```

Add the canonicalizer:

```python
def _normalize_woed_classified_bars(soup: BeautifulSoup, page_content: Tag) -> None:
    for scale in list(page_content.select(".scale")):
        level_region = scale.select_one(":scope > .class1image")
        if level_region is None or level_region.select_one(".classified-bar") is None:
            continue
        level_match = WOED_LEVEL_RE.fullmatch(str(level_region.get("data-level", "")))
        if not _has_required_descendants(scale, WOED_REQUIRED_SELECTORS) or level_match is None:
            _mark_classification_component(scale, "woed", "unrecognized")
            continue
        level = int(level_match.group(1))
        object_text = scale.select_one(".obj-text")
        object_class = (
            WOED_OBJECT_CLASS_NAMES.get(object_text.get_text(" ", strip=True).casefold())
            if object_text is not None
            else None
        )
        _add_class_token(scale, f"woed-level-{level}")
        _add_class_token(scale, f"woed-class-{object_class or 'other'}")
        level_region.clear()
        _add_class_token(level_region, "woed-level-segments")
        for segment_number in range(1, level + 1):
            segment = soup.new_tag(
                "span",
                attrs={
                    "class": [
                        "woed-level-segment",
                        f"woed-level-segment-{segment_number}",
                    ],
                    "aria-hidden": "true",
                },
            )
            level_region.append(segment)
        _mark_classification_component(scale, "woed", "normalized")
```

Call it immediately after `_normalize_anomaly_classification_bars` in `transform_page`:

```python
    _normalize_anomaly_classification_bars(soup, page_content, anomaly_icon_urls)
    _normalize_woed_classified_bars(soup, page_content)
```

- [ ] **Step 4: Run focused and full transform tests**

Run:

```powershell
pytest -q tests/test_transform.py -k "woed_classified_bar"
pytest -q tests/test_transform.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit WOED normalization**

```powershell
git add src/scp_epub/transform.py tests/test_transform.py
git commit -m "fix: canonicalize classified bar components"
```

### Task 3: Add per-document classification inventory reporting

**Files:**
- Create: `src/scp_epub/classification.py`
- Create: `tests/test_classification.py`
- Modify: `src/scp_epub/epub.py:709-750`
- Modify: `tests/test_epub.py:600-700`

- [ ] **Step 1: Write failing inventory aggregation tests**

Create `tests/test_classification.py`:

```python
from scp_epub.classification import classification_component_inventory
from scp_epub.models import PageRef, ProcessedPage


def page(slug: str, title: str, xhtml: str) -> ProcessedPage:
    return ProcessedPage(
        entry=PageRef(title, f"https://example.test/{slug}", slug, 1, "scp"),
        xhtml=xhtml,
        asset_urls=(),
        internal_links=(),
        external_links=(),
    )


def test_inventory_aggregates_components_by_document_and_family():
    pages = [
        page(
            "scp-713",
            "SCP-713 - 哪里不会点哪里",
            '<div data-epub-classification-family="acs" data-epub-classification-status="normalized"></div>'
            '<div data-epub-classification-family="acs" data-epub-classification-status="normalized"></div>',
        ),
        page(
            "scp-1297",
            "SCP-1297 - 逆时指甲罐",
            '<div data-epub-classification-family="woed" data-epub-classification-status="unrecognized"></div>',
        ),
    ]

    records = classification_component_inventory(pages)

    assert [record.as_dict() for record in records] == [
        {
            "slug": "scp-713",
            "title": "SCP-713 - 哪里不会点哪里",
            "family": "acs",
            "component_count": 2,
            "status": "normalized",
        },
        {
            "slug": "scp-1297",
            "title": "SCP-1297 - 逆时指甲罐",
            "family": "woed",
            "component_count": 1,
            "status": "unrecognized",
        },
    ]
```

- [ ] **Step 2: Run the inventory test and verify it fails**

Run:

```powershell
pytest -q tests/test_classification.py
```

Expected: collection fails because `scp_epub.classification` does not exist.

- [ ] **Step 3: Implement the focused inventory module**

Create `src/scp_epub/classification.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from bs4 import BeautifulSoup

from .models import ProcessedPage


@dataclass(frozen=True)
class ClassificationComponentRecord:
    slug: str
    title: str
    family: str
    component_count: int
    status: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "slug": self.slug,
            "title": self.title,
            "family": self.family,
            "component_count": self.component_count,
            "status": self.status,
        }


def classification_component_inventory(
    pages: Sequence[ProcessedPage],
) -> list[ClassificationComponentRecord]:
    records: list[ClassificationComponentRecord] = []
    for page in pages:
        soup = BeautifulSoup(f"<root>{page.xhtml}</root>", "html.parser")
        families: dict[str, list[str]] = {}
        for component in soup.select("[data-epub-classification-family]"):
            family = str(component.get("data-epub-classification-family", "")).strip()
            status = str(component.get("data-epub-classification-status", "unrecognized")).strip()
            if family:
                families.setdefault(family, []).append(status)
        for family, statuses in families.items():
            records.append(
                ClassificationComponentRecord(
                    slug=page.entry.slug,
                    title=page.entry.title,
                    family=family,
                    component_count=len(statuses),
                    status=(
                        "normalized"
                        if all(status == "normalized" for status in statuses)
                        else "unrecognized"
                    ),
                )
            )
    return records
```

- [ ] **Step 4: Add failing build-report serialization coverage**

Extend `test_write_build_report_writes_utf8_json_with_page_assets_and_links` with a marked component on one page, then assert:

```python
    assert report["classification_components"] == [
        {
            "slug": "scp-001",
            "title": "第一章",
            "family": "acs",
            "component_count": 1,
            "status": "normalized",
        }
    ]
```

Add a separate test preserving report shape when no components exist:

```python
def test_write_build_report_omits_empty_classification_inventory(tmp_path: Path):
    report_path = tmp_path / "reports" / "build.json"

    write_build_report(
        report_path,
        pages=[_page("scp-001", "SCP-001", 1)],
        output_path=tmp_path / "book.epub",
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "classification_components" not in report
```

- [ ] **Step 5: Serialize non-empty inventories in `write_build_report`**

Import and add:

```python
from scp_epub.classification import classification_component_inventory
```

After the base report dictionary is created:

```python
    classification_components = classification_component_inventory(ordered_pages)
    if classification_components:
        report["classification_components"] = [
            component.as_dict() for component in classification_components
        ]
```

- [ ] **Step 6: Run inventory and report tests**

Run:

```powershell
pytest -q tests/test_classification.py tests/test_epub.py -k "classification or build_report"
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit inventory reporting**

```powershell
git add src/scp_epub/classification.py src/scp_epub/epub.py tests/test_classification.py tests/test_epub.py
git commit -m "feat: report classification component inventory"
```

### Task 4: Restore normal EPUB component styling

**Files:**
- Modify: `src/scp_epub/epub.py:250-615`
- Modify: `tests/test_epub.py:250-320`

- [ ] **Step 1: Write failing CSS assertions for both families**

Extend the ACS EPUB test:

```python
    compact_css = "".join(css.split())
    assert ".anom-bar-container{width:100%;margin:1.2em0;padding:0;border:0;background:transparent" in compact_css
    assert ".anomaly-lower-row" in css
    assert ".anomaly-diamond-layout" in css
```

Add a WOED CSS test:

```python
def test_write_epub_includes_book_styles_for_woed_classified_bar(tmp_path: Path):
    page = _page(
        "scp-1297",
        "SCP-1297",
        1,
        xhtml=(
            '<div class="scale woed-level-2 woed-class-keter" '
            'data-epub-classification-family="woed" data-epub-classification-status="normalized">'
            '<div class="class1"><div class="level-text">LEVEL 2/1297</div><div class="class-text">CLASSIFIED</div></div>'
            '<div class="class1image woed-level-segments"><span class="woed-level-segment woed-level-segment-1"></span>'
            '<span class="woed-level-segment woed-level-segment-2"></span></div>'
            '<div class="item1"><div class="itemnum">项目编号：SCP-1297</div>'
            '<div class="objclass"><div class="obj"><div class="obj-text">Keter</div></div></div></div></div>'
        ),
    )
    output_path = tmp_path / "woed.epub"

    write_epub([page], output_path, title="SCP", language="zh-CN", creator="SCP")

    with zipfile.ZipFile(output_path) as archive:
        css = archive.read("OEBPS/styles/book.css").decode("utf-8")
    assert ".scale[data-epub-classification-family=\"woed\"]" in css
    assert ".woed-level-segment-1" in css
    assert ".woed-class-keter .obj" in css
    assert ".woed-class-safe .obj" in css
    assert ".woed-class-euclid .obj" in css
    assert ".woed-class-thaumiel .obj" in css
    assert ".woed-class-neutralized .obj" in css
```

- [ ] **Step 2: Run the CSS tests and verify they fail**

Run:

```powershell
pytest -q tests/test_epub.py -k "anomaly_classification_bar or woed_classified_bar"
```

Expected: failures for the transparent ACS shell, lower-row/diamond selectors, and all WOED selectors.

- [ ] **Step 3: Replace the normal ACS shell and add stable lower/diamond rules**

In `BOOK_CSS`, change the component shell and add:

```css
.anom-bar-container {
  width: 100%;
  margin: 1.2em 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: #111;
  font-family: Arial, Helvetica, sans-serif;
  box-sizing: border-box;
}

.anom-bar-container .top-box {
  border: 0;
}

.anom-bar-container .anomaly-lower-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0.3em;
}

.anom-bar-container .anomaly-diamond-layout {
  width: 100%;
  height: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}

.anom-bar-container .anomaly-diamond-layout td {
  width: 33.333%;
  height: 33.333%;
  padding: 0;
  border: 0;
  text-align: center;
  vertical-align: middle;
}
```

Keep the established real clearance bars, ACS class-color rules, and real icon sizing. The six named `.bar-one` through `.bar-six` elements remain hidden by default and explicit `clear-1` through `clear-6` selectors reveal the correct count; `clear-0` reveals none. Remove the synthetic black top/bottom borders so the visible colored bars are the only level bars. Update the narrow media query so `.anomaly-lower-row` becomes one column only below 480px.

The base field style must be neutral (`border-left-color: #777; background: #ececec`) so unknown and esoteric class names remain visible without being falsely colored as Keter/critical. Known containment, disruption, and risk selectors continue to override the neutral base with their established ACS colors.

- [ ] **Step 4: Add complete normal WOED CSS**

Append this component block before the final media query:

```css
.scale[data-epub-classification-family="woed"] {
  display: grid;
  grid-template-columns: minmax(9em, 1.1fr) auto minmax(13em, 1.8fr);
  gap: 0.7em;
  align-items: center;
  max-width: 100%;
  margin: 1em auto;
  padding: 0.75em 0;
  color: #111;
  font-family: Arial, Helvetica, sans-serif;
}

.scale[data-epub-classification-family="woed"] .class1 {
  font-weight: 800;
  line-height: 0.95;
  text-transform: uppercase;
}

.scale[data-epub-classification-family="woed"] .level-text {
  font-size: 2em;
}

.scale[data-epub-classification-family="woed"] .class-text {
  font-size: 1.65em;
}

.scale[data-epub-classification-family="woed"] .woed-level-segments {
  white-space: nowrap;
}

.scale[data-epub-classification-family="woed"] .woed-level-segment {
  display: block;
  width: 1.05em;
  height: 4.6em;
  margin-right: 0.16em;
  float: left;
  background: #111;
}

.scale[data-epub-classification-family="woed"] .woed-level-segment-1 { background: #d9d9d9; }
.scale[data-epub-classification-family="woed"] .woed-level-segment-2 { background: #b5b5b5; }
.scale[data-epub-classification-family="woed"] .woed-level-segment-3 { background: #858585; }
.scale[data-epub-classification-family="woed"] .woed-level-segment-4 { background: #555; }
.scale[data-epub-classification-family="woed"] .woed-level-segment-5 { background: #111; }
.scale[data-epub-classification-family="woed"] .woed-level-segment-6 { background: #8c191a; }

.scale[data-epub-classification-family="woed"] .item1 { text-align: right; }
.scale[data-epub-classification-family="woed"] .itemnum { font-size: 1.7em; }
.scale[data-epub-classification-family="woed"] .obj { margin-top: 0.2em; padding: 0.12em 1em; border-radius: 2em; background: rgb(127, 127, 127); color: #fff; text-align: center; }
.scale[data-epub-classification-family="woed"] .obj-text { font-size: 2em; font-weight: 800; text-transform: uppercase; }
.scale.woed-class-safe .obj { background: rgb(35, 145, 70); }
.scale.woed-class-euclid .obj { background: rgb(225, 205, 35); color: #111; }
.scale.woed-class-keter .obj { background: rgb(180, 30, 35); }
.scale.woed-class-thaumiel .obj { background: rgb(40, 60, 150); }
.scale.woed-class-neutralized .obj { background: rgb(127, 127, 127); }
```

In the 480px media query, make the three regions stack and reset item alignment:

```css
  .scale[data-epub-classification-family="woed"] {
    grid-template-columns: 1fr;
  }

  .scale[data-epub-classification-family="woed"] .item1 {
    text-align: left;
  }
```

- [ ] **Step 5: Run EPUB tests**

Run:

```powershell
pytest -q tests/test_epub.py
```

Expected: all EPUB tests pass.

- [ ] **Step 6: Commit normal EPUB styling**

```powershell
git add src/scp_epub/epub.py tests/test_epub.py
git commit -m "fix: restore classification component styling"
```

### Task 5: Add Kindle-safe rendering for the canonical components

**Files:**
- Modify: `src/scp_epub/styles/kindle.css:160-470`
- Modify: `src/scp_epub/kindle.py:1039-1160`
- Modify: `tests/test_kindle.py:1060-1330`

- [ ] **Step 1: Write failing Kindle structure and CSS assertions**

Add a canonical-structure preservation test:

```python
def test_prepare_kindle_pages_preserves_canonical_classification_markup():
    xhtml = (
        '<div class="anom-bar-container clear-2" data-epub-classification-family="acs" '
        'data-epub-classification-status="normalized"><div class="top-right-box">'
        '<div class="clearance"><span class="anomaly-clearance-label">受限</span></div></div>'
        '<div class="anomaly-lower-row"><div class="disrupt-class">Dark</div>'
        '<div class="risk-class">待观察</div></div><table class="anomaly-diamond-layout">'
        '<tbody><tr><td class="anomaly-diamond-top"></td></tr></tbody></table></div>'
        '<div class="scale woed-level-2 woed-class-keter" data-epub-classification-family="woed" '
        'data-epub-classification-status="normalized"><div class="woed-level-segments">'
        '<span class="woed-level-segment woed-level-segment-1"></span>'
        '<span class="woed-level-segment woed-level-segment-2"></span></div></div>'
    )

    [prepared] = prepare_kindle_pages([_page(xhtml)])

    assert '<span class="kindle-clearance-label">RESTRICTED</span>' in prepared.xhtml
    assert 'class="anomaly-lower-row"' in prepared.xhtml
    assert 'class="anomaly-diamond-layout"' in prepared.xhtml
    assert 'class="woed-level-segment woed-level-segment-2"' in prepared.xhtml
```

Extend `test_kindle_css_uses_kf8_fallbacks_and_preserves_scp_components`:

```python
    assert ".anomaly-lower-row" in css
    assert ".anomaly-diamond-layout" in css
    assert '.scale[data-epub-classification-family="woed"]' in css
    assert ".woed-level-segment-6" in css
    assert ".woed-class-keter .obj" in css
    assert ".woed-class-safe .obj" in css
    assert ".woed-class-euclid .obj" in css
    assert ".woed-class-thaumiel .obj" in css
    assert ".woed-class-neutralized .obj" in css
```

Extend the existing clearance mapping test with a `clear-0` page and assert that it receives no generated Kindle label while levels 1–6 retain `PUBLIC` through `COSMIC TOP SECRET`.

- [ ] **Step 2: Run Kindle tests and verify CSS assertions fail**

Run:

```powershell
pytest -q tests/test_kindle.py -k "canonical_classification or kf8_fallbacks"
```

Expected: the structure test may pass except for label replacement; CSS assertions fail until the stylesheet is updated.

- [ ] **Step 3: Replace the Kindle ACS shell and pair the lower fields**

Change the Kindle shell to:

```css
.anom-bar-container {
  width: 100%;
  margin: 1.2em 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: #111;
  font-family: Arial, Helvetica, sans-serif;
}

.anom-bar-container .anomaly-lower-row {
  display: table;
  width: 100%;
  border-collapse: separate;
  border-spacing: 0.3em;
}

.anom-bar-container .anomaly-lower-row .disrupt-class,
.anom-bar-container .anomaly-lower-row .risk-class {
  display: table-cell;
  width: 50%;
  vertical-align: middle;
}

.anom-bar-container .anomaly-diamond-layout {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}

.anom-bar-container .anomaly-diamond-layout td {
  width: 33%;
  height: 2.2em;
  padding: 0;
  border: 0;
  text-align: center;
  vertical-align: middle;
}
```

Add real clearance-bar rules rather than the current black border approximation:

```css
.anom-bar-container .top-center-box {
  border: 0;
}

.anom-bar-container .top-center-box .bar-one,
.anom-bar-container .top-center-box .bar-two,
.anom-bar-container .top-center-box .bar-three,
.anom-bar-container .top-center-box .bar-four,
.anom-bar-container .top-center-box .bar-five,
.anom-bar-container .top-center-box .bar-six {
  display: none;
  height: 0.45em;
  margin: 0.18em 0;
}

.anom-bar-container.clear-1 .top-center-box .bar-one,
.anom-bar-container.clear-2 .top-center-box .bar-one,
.anom-bar-container.clear-2 .top-center-box .bar-two,
.anom-bar-container.clear-3 .top-center-box .bar-one,
.anom-bar-container.clear-3 .top-center-box .bar-two,
.anom-bar-container.clear-3 .top-center-box .bar-three,
.anom-bar-container.clear-4 .top-center-box .bar-one,
.anom-bar-container.clear-4 .top-center-box .bar-two,
.anom-bar-container.clear-4 .top-center-box .bar-three,
.anom-bar-container.clear-4 .top-center-box .bar-four,
.anom-bar-container.clear-5 .top-center-box .bar-one,
.anom-bar-container.clear-5 .top-center-box .bar-two,
.anom-bar-container.clear-5 .top-center-box .bar-three,
.anom-bar-container.clear-5 .top-center-box .bar-four,
.anom-bar-container.clear-5 .top-center-box .bar-five,
.anom-bar-container.clear-6 .top-center-box .bar-one,
.anom-bar-container.clear-6 .top-center-box .bar-two,
.anom-bar-container.clear-6 .top-center-box .bar-three,
.anom-bar-container.clear-6 .top-center-box .bar-four,
.anom-bar-container.clear-6 .top-center-box .bar-five,
.anom-bar-container.clear-6 .top-center-box .bar-six {
  display: block;
}

.anom-bar-container.clear-1 .top-center-box div { background: #009f6b; }
.anom-bar-container.clear-2 .top-center-box div { background: #0087bd; }
.anom-bar-container.clear-3 .top-center-box div { background: #ffd300; }
.anom-bar-container.clear-4 .top-center-box div { background: #ff6d00; }
.anom-bar-container.clear-5 .top-center-box div { background: #c40233; }
.anom-bar-container.clear-6 .top-center-box div { background: #111; }
```

Keep all class colors, field backgrounds, real icons, and the existing real English Kindle clearance label. Remove the old red outer border, gray panel, and black top-center border approximation. `clear-0` intentionally displays no colored bar and no Kindle clearance label.

As in normal EPUB CSS, use a neutral base field color for unknown/esoteric values and allow only explicit known-class selectors to apply semantic ACS colors.

- [ ] **Step 4: Add Kindle-safe WOED rules**

Append rules using only table/block/inline-block/float primitives:

```css
.scale[data-epub-classification-family="woed"] {
  display: table;
  width: 100%;
  margin: 1em 0;
  padding: 0.75em 0;
  color: #111;
  font-family: Arial, Helvetica, sans-serif;
  table-layout: fixed;
}

.scale[data-epub-classification-family="woed"] .class1,
.scale[data-epub-classification-family="woed"] .class1image,
.scale[data-epub-classification-family="woed"] .item1 {
  display: table-cell;
  vertical-align: middle;
}

.scale[data-epub-classification-family="woed"] .class1 { width: 30%; font-weight: bold; text-transform: uppercase; }
.scale[data-epub-classification-family="woed"] .class1image { width: 22%; white-space: nowrap; }
.scale[data-epub-classification-family="woed"] .item1 { width: 48%; text-align: right; }
.scale[data-epub-classification-family="woed"] .level-text { font-size: 1.6em; line-height: 1; }
.scale[data-epub-classification-family="woed"] .class-text { font-size: 1.35em; line-height: 1; }
.scale[data-epub-classification-family="woed"] .woed-level-segment { display: inline-block; width: 0.75em; height: 4em; margin-right: 0.12em; background: #111; }
.scale[data-epub-classification-family="woed"] .woed-level-segment-1 { background: #d9d9d9; }
.scale[data-epub-classification-family="woed"] .woed-level-segment-2 { background: #b5b5b5; }
.scale[data-epub-classification-family="woed"] .woed-level-segment-3 { background: #858585; }
.scale[data-epub-classification-family="woed"] .woed-level-segment-4 { background: #555; }
.scale[data-epub-classification-family="woed"] .woed-level-segment-5 { background: #111; }
.scale[data-epub-classification-family="woed"] .woed-level-segment-6 { background: #8c191a; }
.scale[data-epub-classification-family="woed"] .obj { margin-top: 0.2em; padding: 0.12em 0.8em; border-radius: 2em; background: rgb(127, 127, 127); color: #fff; text-align: center; }
.scale[data-epub-classification-family="woed"] .obj-text { font-size: 1.7em; font-weight: bold; text-transform: uppercase; }
.scale.woed-class-safe .obj { background: rgb(35, 145, 70); }
.scale.woed-class-euclid .obj { background: rgb(225, 205, 35); color: #111; }
.scale.woed-class-keter .obj { background: rgb(180, 30, 35); }
.scale.woed-class-thaumiel .obj { background: rgb(40, 60, 150); }
.scale.woed-class-neutralized .obj { background: rgb(127, 127, 127); }
```

At the existing 600px media query, stack the three WOED regions and the ACS lower fields with block layout.

- [ ] **Step 5: Verify the Kindle CSS restriction test remains strict**

Run:

```powershell
pytest -q tests/test_kindle.py -k "prepare_kindle_pages or kindle_css"
```

Expected: all selected tests pass and the stylesheet contains none of the forbidden constructs already enumerated by `test_kindle_css_uses_kf8_fallbacks_and_preserves_scp_components`.

- [ ] **Step 6: Commit Kindle rendering**

```powershell
git add src/scp_epub/kindle.py src/scp_epub/styles/kindle.css tests/test_kindle.py
git commit -m "fix: render classification bars on Kindle"
```

### Task 6: Verify pipeline integration and full 69-document inventory

**Files:**
- Modify: `tests/test_pipeline.py:2080-2150`
- Read: `output/reports/SCP基金会档案精选-report.json`
- Read: `output/reports/SCP基金会档案精选-Kindle-report.json`

- [ ] **Step 1: Add pipeline assertions for inventory and canonical XHTML**

Extend the Kindle pipeline test fixture with a complete minimal ACS shape and assert:

```python
    assert 'data-epub-classification-family="acs"' in chapter
    assert 'data-epub-classification-status="normalized"' in chapter
    assert 'class="anomaly-lower-row"' in chapter
    assert report["classification_components"] == [
        {
            "slug": "scp-001",
            "title": "SCP-001",
            "family": "acs",
            "component_count": 1,
            "status": "normalized",
        }
    ]
```

Also assert the processed XHTML has canonical structure but no Kindle-only label:

```python
    assert 'data-epub-classification-family="acs"' in processed_xhtml
    assert 'class="anomaly-lower-row"' in processed_xhtml
    assert "kindle-clearance-label" not in processed_xhtml
```

- [ ] **Step 2: Run pipeline and full unit tests**

Run:

```powershell
pytest -q tests/test_pipeline.py -k "kindles_pages_css_report"
pytest -q
```

Expected: the focused test passes, then the full suite passes with no regressions.

- [ ] **Step 3: Build the normal Featured EPUB**

Run:

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured
```

Expected outputs:

```text
output/epub/SCP基金会档案精选.epub
output/reports/SCP基金会档案精选-report.json
```

- [ ] **Step 4: Build the Kindle EPUB and AZW3**

Run:

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle
```

Expected outputs:

```text
output/epub/SCP基金会档案精选-Kindle.epub
output/azw3/SCP基金会档案精选-Kindle.azw3
output/reports/SCP基金会档案精选-Kindle-report.json
```

- [ ] **Step 5: Validate both reports contain the exact document inventory**

Run:

```powershell
@'
import json
from pathlib import Path

for name in ("SCP基金会档案精选-report.json", "SCP基金会档案精选-Kindle-report.json"):
    path = Path("output/reports") / name
    report = json.loads(path.read_text(encoding="utf-8"))
    records = report["classification_components"]
    acs = [record for record in records if record["family"] == "acs"]
    woed = [record for record in records if record["family"] == "woed"]
    assert len(records) == 69, (name, len(records))
    assert len(acs) == 58, (name, len(acs))
    assert len(woed) == 11, (name, len(woed))
    assert all(record["status"] == "normalized" for record in records), name
    assert {record["slug"] for record in records} >= {"scp-713", "scp-186", "scp-1297"}
    print(name, len(acs), len(woed), "all normalized")
'@ | python -
```

Expected:

```text
SCP基金会档案精选-report.json 58 11 all normalized
SCP基金会档案精选-Kindle-report.json 58 11 all normalized
```

- [ ] **Step 6: Commit pipeline coverage**

```powershell
git add tests/test_pipeline.py
git commit -m "test: cover classification inventory pipeline"
```

Generated EPUB, AZW3, processed pages, and reports remain untracked and must not be committed.

### Task 7: Render and visually review representative chapters

**Files:**
- Read: `output/epub/SCP基金会档案精选.epub`
- Read: `output/epub/SCP基金会档案精选-Kindle.epub`
- Create temporarily outside Git: `output/visual-checks/classification-components/`

- [ ] **Step 1: Extract the three representative chapters and book CSS from both EPUBs**

Use a short read-only extraction script that finds chapter filenames containing `scp-713`, `scp-186`, and `scp-1297`, writes standalone HTML wrappers under `output/visual-checks/classification-components/<edition>/`, and copies the corresponding `book.css` beside them.

Run:

```powershell
@'
from pathlib import Path
from zipfile import ZipFile

slugs = ("scp-713", "scp-186", "scp-1297")
books = {
    "normal": Path("output/epub/SCP基金会档案精选.epub"),
    "kindle": Path("output/epub/SCP基金会档案精选-Kindle.epub"),
}
root = Path("output/visual-checks/classification-components")
for edition, book in books.items():
    target = root / edition
    target.mkdir(parents=True, exist_ok=True)
    with ZipFile(book) as archive:
        css = archive.read("OEBPS/styles/book.css").decode("utf-8")
        (target / "book.css").write_text(css, encoding="utf-8")
        names = archive.namelist()
        for slug in slugs:
            chapter = next(name for name in names if name.endswith(f"-{slug}.xhtml"))
            xhtml = archive.read(chapter).decode("utf-8")
            xhtml = xhtml.replace('../styles/book.css', 'book.css')
            (target / f"{slug}.html").write_text(xhtml, encoding="utf-8")
            print(edition, slug, chapter)
'@ | python -
```

Expected: six HTML files and two CSS files are created outside tracked source paths.

- [ ] **Step 2: Capture desktop and narrow screenshots with Playwright**

For each of the six HTML files, capture one screenshot at 1200px width and one at 600px width. Save them beside the extracted files with `-desktop.png` and `-narrow.png` suffixes.

Acceptance criteria:

- SCP-713: blue level-2 bars, green Safe/Dark fields, blue risk field, real icons, containment full width, disruption/risk paired at desktop width.
- SCP-186: red level-5 bars, Euclid yellow field, Amida and critical red fields, real icons and hazard layout.
- SCP-1297: large `LEVEL 2/1297 CLASSIFIED`, two real level segments, item number, and red Keter pill.
- Both editions: no artificial gray ACS panel or red outer frame.
- Narrow captures: no horizontal clipping; paired/three-region layouts may stack.

- [ ] **Step 3: Inspect the AZW3 conversion result**

Run:

```powershell
Get-Item 'output/azw3/SCP基金会档案精选-Kindle.azw3' | Select-Object FullName,Length,LastWriteTime
```

Expected: a non-empty AZW3 newer than the Kindle EPUB build start time.

- [ ] **Step 4: Run final repository checks**

Run:

```powershell
pytest -q
git diff --check
git status --short --branch
```

Expected: all tests pass; no whitespace errors; only ignored/generated output files are outside Git status; tracked source is clean after the task commits.

- [ ] **Step 5: Perform local code review before completion**

Review the complete change set with:

```powershell
git log --oneline 8997181..HEAD
git diff 8997181..HEAD -- src/scp_epub tests
```

Check specifically for dropped semantic text, unsafe source CSS copying, Kindle-forbidden selectors, report duplication, and changes unrelated to the two approved component families. Fix any actionable issue, rerun affected tests, and commit the correction with a focused `fix:` message.
