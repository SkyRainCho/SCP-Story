# Style Processing Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove duplicated CSS scans and skip provably irrelevant CSS blocks during page transformation without changing output semantics.

**Architecture:** Transform code will build anomaly icon and quadrant metadata in one rule traversal. The general page-style matcher gains a conservative prefilter based on its existing targeting contract: `#page-content`, classes, and ids in page content. A match still uses the existing CSS parser and selector normalization.

**Tech Stack:** Python, BeautifulSoup, regex, pytest.

---

## File structure

- `src/scp_epub/transform.py`: combine anomaly style metadata extraction and add the conservative page-style prefilter.
- `tests/test_transform.py`: regression tests for style relevance, anomaly icons, wildcard/template selectors, and custom-property colors.

### Task 1: Prove page-style relevance behavior

**Files:**

- Modify: `tests/test_transform.py`

- [ ] **Step 1: Write a failing irrelevant-style test**

Use a page with `<div class="kept">正文</div>` and an inline style containing thousands of irrelevant `.unused-N { color: red; }` rules plus one relevant `.kept { color: blue; }` rule. Call `transform_page` and assert its leading `<style>` contains the blue rule but not an unused rule.

```python
def test_transform_page_keeps_only_relevant_page_style_rules():
    html = (
        '<style>.unused { color: red; } .kept { color: blue; }</style>'
        '<div id="page-content"><div class="kept">正文</div></div>'
    )
    page = transform_page(_entry(), html, "https://example.test")

    assert ".kept {color: blue;}" in page.xhtml
    assert ".unused" not in page.xhtml
```

- [ ] **Step 2: Write failing id and root-selector tests**

```python
def test_transform_page_keeps_id_and_page_content_style_rules():
    html = (
        '<style>#target { color: red; } #page-content > p { margin: 0; }</style>'
        '<div id="page-content"><p id="target">正文</p></div>'
    )
    page = transform_page(_entry(), html, "https://example.test")

    assert "#target {color: red;}" in page.xhtml
    assert "> p {margin: 0;}" in page.xhtml
```

- [ ] **Step 3: Run focused transform tests before implementation**

Run: `pytest tests/test_transform.py -k "page_style" -q`

Expected: existing coverage passes; add a monkeypatched assertion against the new prefilter helper so the newly added test fails until the helper exists.

### Task 2: Add the conservative page-style prefilter

**Files:**

- Modify: `src/scp_epub/transform.py`
- Test: `tests/test_transform.py`

- [ ] **Step 1: Add a helper matching the existing targeting contract**

```python
def _style_block_may_target_page_content(
    css_text: str,
    targets: tuple[set[str], set[str]],
) -> bool:
    page_classes, page_ids = targets
    lowered = css_text.casefold()
    if "#page-content" in lowered:
        return True
    return any(
        f".{class_name}" in lowered for class_name in page_classes
    ) or any(f"#{identifier}" in lowered for identifier in page_ids)
```

- [ ] **Step 2: Gate the existing matcher without changing it**

In `_applicable_page_styles`, compute `css_text` as today. Skip calling `_matching_css_rules` only when `_style_block_may_target_page_content(css_text, targets)` is false; otherwise preserve the current matcher, deduplication, and output ordering.

- [ ] **Step 3: Run focused tests**

Run: `pytest tests/test_transform.py -k "page_style" -q`

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add src/scp_epub/transform.py tests/test_transform.py
git commit -m "perf: skip irrelevant page style blocks"
```

### Task 3: Combine anomaly style metadata extraction

**Files:**

- Modify: `tests/test_transform.py`
- Modify: `src/scp_epub/transform.py`

- [ ] **Step 1: Write a transform-level regression fixture**

Create a page containing an `.anom-bar-container`, a style rule assigning an icon URL through a template-compatible containment selector, and rules assigning a CSS custom property and a top quadrant background. Assert the transformed output still includes the normalized icon URL and the expected SVG quadrant fill.

- [ ] **Step 2: Run the new focused test to establish its current behavior**

Run: `pytest tests/test_transform.py -k "anomaly and style" -q`

Expected: PASS before refactoring; record it as characterization coverage for output preservation.

- [ ] **Step 3: Replace the two traversals with one helper**

```python
def _anomaly_style_metadata(
    soup: BeautifulSoup,
    base_url: str,
) -> tuple[
    dict[tuple[str, str], str],
    dict[tuple[str, str], tuple[str, str]],
]:
    icon_urls: dict[tuple[str, str], str] = {}
    colors: dict[tuple[str, str], tuple[str, str]] = {}
    custom_properties = _numeric_css_custom_properties(soup)
    for style in soup.find_all("style"):
        for rule in CSS_RULE_RE.finditer(style.get_text("\n", strip=True)):
            selectors = rule.group("selectors").split(",")
            url_match = CSS_BACKGROUND_IMAGE_URL_RE.search(rule.group("body"))
            raw_url = (
                next(
                    (value for value in (
                        url_match.group("double"), url_match.group("single"),
                        url_match.group("bare"),
                    ) if value),
                    None,
                ) if url_match is not None else None
            )
            if raw_url and not WIKIDOT_TEMPLATE_PLACEHOLDER_RE.search(raw_url):
                normalized_url = normalize_url(base_url, raw_url)
                if normalized_url != ACS_ANOMALY_ICON_PLACEHOLDER_URL:
                    for selector in selectors:
                        field_class = _anomaly_field_class_for_selector(selector)
                        if field_class is None:
                            continue
                        normalized_selector = selector.replace("\\", "").casefold()
                        placeholders = {
                            "contain-class": ("container-class", "containment-class"),
                            "second-class": ("secondary-class",),
                            "disrupt-class": ("disruption-class",),
                            "risk-class": ("risk-class",),
                        }[field_class]
                        if any("{$" + name + "}" in normalized_selector for name in placeholders):
                            icon_urls[("*", field_class)] = normalized_url
                        elif not WIKIDOT_TEMPLATE_PLACEHOLDER_RE.search(selector):
                            for class_name in re.findall(
                                r"\\.anom-bar-container\\.([^\\s.:#>+~,\\[\\](){}]+)", selector
                            ):
                                icon_urls[(class_name.casefold(), field_class)] = normalized_url
            color = _last_resolved_background_color(rule.group("body"), custom_properties)
            if color is None:
                continue
            for selector in selectors:
                quadrants = set(re.findall(r"\\.(top|right|left|bottom)-quad\\b", selector, re.IGNORECASE))
                if not quadrants and re.search(r"\\.quadrants\\s*>\\s*div\\b", selector, re.IGNORECASE):
                    quadrants = {"top", "right", "left", "bottom"}
                class_names = re.findall(
                    r"\\.anom-bar-container\\.([^\\s.:#>+~,\\[\\](){}]+)", selector
                )
                for quadrant in quadrants:
                    modifiers = re.findall(
                        rf"\\.{quadrant}-quad\\.([^\\s.:#>+~,\\[\\](){{}}]+)", selector, re.IGNORECASE
                    )
                    for class_name in class_names or modifiers or ["*"]:
                        colors[(class_name.replace("\\", "").casefold(), quadrant)] = color
    return icon_urls, colors
```

Call it once in `transform_page` only when an anomaly bar exists, then pass both returned mappings into `_normalize_anomaly_classification_bars`. Delete the two superseded helpers after moving their exact logic into the combined traversal.

- [ ] **Step 4: Run anomaly and full transform tests**

Run: `pytest tests/test_transform.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/scp_epub/transform.py tests/test_transform.py
git commit -m "perf: combine anomaly style scans"
```

### Task 4: Verify speed and outputs

**Files:**

- No source changes expected.

- [ ] **Step 1: Run the full automated suite**

Run: `$env:PYTHONPATH = "src"; pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Profile and time cached Featured**

Run the existing cached Featured CLI build with `cProfile`, then inspect cumulative time for `_process_pages`, `_matching_css_rules`, and anomaly style metadata extraction. Also record unprofiled wall time.

Expected: the two anomaly style scans no longer appear separately; relevant-style output remains covered by tests; conversion time is materially lower.

- [ ] **Step 3: Build every configured non-Kindle volume from the existing cache**

Use the source tree under test with the master workspace configuration/cache paths. Load each `config/*.yaml`, iterate its `config.volumes`, call `build_volume`, and stop on the first exception.

Expected: every configured non-Kindle EPUB build succeeds.

- [ ] **Step 4: Run the Featured Kindle integration build if Calibre is installed**

Run `python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle` when `ebook-convert` is available; otherwise record the skip.

Expected: Kindle EPUB and AZW3 succeed, or the unavailable converter skip is reported.

- [ ] **Step 5: Final review and commit check**

```powershell
git diff --check
git status --short
git log --oneline master..HEAD
```

Expected: only planned source, tests, and design/plan documents are committed; generated output and cache files remain untracked.
