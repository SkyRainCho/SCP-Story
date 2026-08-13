# Safe Inline-Block Layout Preservation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve safe inline `display: inline-block` declarations so SCP-3934 and other affected documents retain their intended shrink-to-content centered layouts in EPUB output.

**Architecture:** Keep the existing property whitelist conservative and add a dedicated value-level exception in `_sanitize_style_value`: `display` is emitted only when its normalized value is `inline-block`. All other display values remain absent. Tests cover the general sanitizer contract and the exact SCP-3934 collapsible-title structure before the Featured EPUB and Kindle Scribe outputs are rebuilt and inspected.

**Tech Stack:** Python 3.11+, BeautifulSoup, pytest, existing SCP EPUB pipeline, Calibre `ebook-convert`.

---

### Task 1: Preserve only safe inline-block display values

**Files:**
- Modify: `tests/test_transform.py`
- Modify: `src/scp_epub/transform.py:45-80,3039-3055`

- [ ] **Step 1: Write the failing sanitizer test**

Add this test beside `test_strips_event_handlers_and_sanitizes_inline_styles_but_keeps_harmless_attributes`:

```python
def test_preserves_only_inline_block_display_value():
    html = """
    <html><body><div id="page-content">
      <div id="safe" style="display: inline-block; border: 1px solid black">安全卡片</div>
      <div id="hidden" style="display: none; color: red">隐藏模板</div>
      <div id="block" style="display: block; color: blue">普通块</div>
      <div id="flex" style="display: flex; color: green">弹性布局</div>
    </div></body></html>
    """

    result = transform_page(page_ref(), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    assert soup.find(id="safe")["style"] == "display: inline-block; border: 1px solid black"
    assert soup.find(id="hidden")["style"] == "color: red"
    assert soup.find(id="block")["style"] == "color: blue"
    assert soup.find(id="flex")["style"] == "color: green"
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_transform.py -k preserves_only_inline_block_display_value
```

Expected: FAIL because the `safe` element lacks `display: inline-block`.

- [ ] **Step 3: Implement the minimal value-level exception**

Do not add `display` to `SAFE_STYLE_PROPERTIES`. Add a narrowly scoped helper and use it from `_sanitize_style_value`:

```python
SAFE_DISPLAY_VALUES = {"inline-block"}


def _is_safe_style_declaration(property_name: str, value: str) -> bool:
    if property_name == "display":
        return value.casefold() in SAFE_DISPLAY_VALUES
    return property_name in SAFE_STYLE_PROPERTIES
```

Then replace the current property check with:

```python
        if not _is_safe_style_declaration(normalized_property, value):
            continue
```

Keep the existing unsafe-value check after this condition.

- [ ] **Step 4: Run the target test and sanitizer regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_transform.py -k "preserves_only_inline_block_display_value or sanitizes_inline_styles or hidden"
```

Expected: all selected tests PASS; hidden templates remain absent where existing tests require removal.

- [ ] **Step 5: Commit the sanitizer behavior**

Stage only the two files and commit:

```powershell
git add src/scp_epub/transform.py tests/test_transform.py
git commit -m "fix: preserve safe inline-block layouts"
```

### Task 2: Add the SCP-3934 structural regression

**Files:**
- Modify: `tests/test_transform.py`

- [ ] **Step 1: Write the SCP-3934 regression test**

Add a focused test using the real structural pattern:

```python
def test_scp3934_keeps_centered_inline_block_appendix_card():
    html = """
    <html><head><style>
      #page-content .collapsible-block { text-align: center; }
      .collapsible-block-content p { text-align: left; }
    </style></head><body><div id="page-content">
      <div class="collapsible-block">
        <div class="collapsible-block-folded"><a class="collapsible-block-link">附录：发现</a></div>
        <div class="collapsible-block-unfolded" style="display:none">
          <div class="collapsible-block-content">
            <div id="department-card" style="border: 1px solid black; background-color: white; display: inline-block; padding-left: 20px; padding-right: 20px">
              <div class="image-container aligncenter"><img src="/ecd.png" alt="ecd.png" width="50" height="50"/></div>
              <h2><span>外务部制备</span></h2>
            </div>
            <p><strong>主题：</strong>SCP-3934-1的发现与回收</p>
          </div>
        </div>
      </div>
    </div></body></html>
    """

    result = transform_page(page_ref("scp-3934"), html, BASE_URL)
    soup = soup_fragment(result.xhtml)

    card = soup.find(id="department-card")
    assert "display: inline-block" in card["style"]
    assert "text-align: center" in soup.find("style").get_text()
    assert "主题：" in soup.get_text(" ", strip=True)
```

- [ ] **Step 2: Prove the regression test detects the old behavior**

Temporarily remove or locally revert the Task 1 value-level exception, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_transform.py -k scp3934_keeps_centered_inline_block_appendix_card
```

Expected: FAIL because `display: inline-block` is absent. Restore the Task 1 implementation immediately.

- [ ] **Step 3: Run the regression test GREEN**

Run the same command after restoring the implementation.

Expected: PASS.

- [ ] **Step 4: Run the complete transform test file**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_transform.py
```

Expected: all transform tests PASS.

- [ ] **Step 5: Commit the SCP-3934 regression**

```powershell
git add tests/test_transform.py
git commit -m "test: cover SCP-3934 centered appendix card"
```

### Task 3: Verify scope and rebuild Featured outputs

**Files:**
- Read: `output/reports/inline-block-affected-pages.json`
- Generate (ignored): `data/processed/SCP基金会档案精选/*.xhtml`
- Generate (ignored): `output/epub/SCP基金会档案精选.epub`
- Generate (ignored): `output/epub/SCP基金会档案精选-Kindle-Scribe.epub`
- Generate (ignored): `output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3`
- Generate (ignored): `output/reports/SCP基金会档案精选-report.json`
- Generate (ignored): `output/reports/SCP基金会档案精选-Kindle-Scribe-report.json`

- [ ] **Step 1: Run the full automated test suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Rebuild the normal Featured EPUB**

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
```

Expected: writes `output/epub/SCP基金会档案精选.epub` and its report.

- [ ] **Step 3: Rebuild the Kindle Scribe stable outputs**

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

Expected: writes the Scribe EPUB, AZW3, and independent report.

- [ ] **Step 4: Inspect generated XHTML structurally**

Run a Python verification script that opens the newest processed SCP-3934 XHTML for both modes, locates the element containing `外务部制备`, and asserts its ancestor style contains `display: inline-block`. The script must also check both EPUB ZIP files with `ZipFile.testzip() is None`.

Expected: both modes retain the declaration and both archives pass ZIP integrity.

- [ ] **Step 5: Perform visual verification**

Render or open the SCP-3934 section from the rebuilt normal EPUB and Scribe EPUB. Confirm the title card is shrink-to-content and centered, while the following topic/report paragraphs remain left-aligned. Also inspect these high-impact Featured pages:

- `scp-4793` (14 affected nodes)
- `scp-6183` (32 affected nodes)

Expected: their inline-block components retain intended inline sizing without hidden templates becoming visible or obvious overlap/reflow regressions.

- [ ] **Step 6: Record final evidence**

Report:

- full test count and exit code;
- 252 documents / 1115 nodes in the global scanned scope;
- 13 documents / 64 nodes in Featured;
- SCP-3934 declaration present in both generated modes;
- normal EPUB and Scribe EPUB ZIP integrity results;
- Scribe AZW3 existence and byte size.

No generated EPUB, cache, processed XHTML, scan report, or `.superpowers/` session file is committed.
