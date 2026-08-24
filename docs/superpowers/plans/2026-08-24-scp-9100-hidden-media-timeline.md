# SCP-9100 Hidden Media and Static Timeline Divider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove SCP-9100's web-only thumbnail and reproduce every relative-time separator as a stable horizontal-line divider without affecting other pages.

**Architecture:** Add one slug-gated DOM normalization helper to the existing transform pipeline. The helper removes the hidden thumbnail before asset collection and replaces each Flexbox/pseudo-element time separator with a real three-cell XHTML table containing two rule elements and the original label.

**Tech Stack:** Python 3.11+, BeautifulSoup, pytest, existing SCP EPUB build CLI.

---

### Task 1: Add regression coverage

**Files:**
- Test: `tests/test_transform.py`

- [ ] **Step 1: Add a minimal SCP-9100 fixture and target-page test**

```python
def _scp9100_web_only_elements_html() -> str:
    return """
    <html><body><div id="page-content">
      <img class="crom-thumbnail" src="/local--files/scp-9100/Daydream.png"
           style="display: none" />
      <div class="event"><p>2014年4月2日：保留的事件。</p></div>
      <div class="relativetime"><p>[+2天]</p></div>
      <div class="event"><p>2014年4月4日：保留的事件。</p></div>
      <div class="relativetime"><p>[+5天]</p></div>
    </div></body></html>
    """


def test_scp9100_removes_web_only_thumbnail_and_staticizes_time_separators():
    result = transform_page(page_ref("scp-9100"), _scp9100_web_only_elements_html(), BASE_URL)
    soup = soup_fragment(result.xhtml)
    assert soup.select(".crom-thumbnail, .relativetime") == []
    dividers = soup.select(".layout-profile-scp-9100-relative-time")
    assert len(dividers) == 2
    assert [divider.get_text(" ", strip=True) for divider in dividers] == ["[+2天]", "[+5天]"]
    assert all(len(divider.select(".layout-profile-scp-9100-relative-time-rule")) == 2 for divider in dividers)
    assert "Daydream.png" not in result.xhtml
    assert "Daydream.png" not in " ".join(result.asset_urls)
    assert "2014年4月2日" in soup.get_text(" ", strip=True)
    assert "2014年4月4日" in soup.get_text(" ", strip=True)
```

- [ ] **Step 2: Add a cross-page isolation test**

```python
def test_scp9100_web_only_cleanup_does_not_affect_other_pages():
    result = transform_page(page_ref("scp-9099"), _scp9100_web_only_elements_html(), BASE_URL)
    soup = soup_fragment(result.xhtml)
    assert soup.select_one(".crom-thumbnail") is not None
    assert len(soup.select(".relativetime")) == 2
```

- [ ] **Step 3: Run the tests and verify the target test fails before implementation**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_transform.py -k "scp9100"`

Expected: target-page test fails because no static dividers are generated; isolation test passes.

### Task 2: Implement the page-specific normalization

**Files:**
- Modify: `src/scp_epub/transform.py`
- Test: `tests/test_transform.py`

- [ ] **Step 1: Add the slug-gated transform call**

```python
if entry.slug == "scp-9100":
    _normalize_scp_9100_web_only_elements(soup, page_content)
```

- [ ] **Step 2: Add the DOM normalization helper**

```python
def _normalize_scp_9100_web_only_elements(soup: BeautifulSoup, page_content: Tag) -> None:
    for thumbnail in list(page_content.select(".crom-thumbnail")):
        thumbnail.decompose()

    for relative_time in list(page_content.select(".relativetime")):
        label_text = relative_time.get_text(" ", strip=True)
        divider = soup.new_tag("table")
        divider["class"] = ["layout-profile-scp-9100-relative-time"]
        _append_style_declaration(divider, "width", "100%")
        _append_style_declaration(divider, "border", "none")
        _append_style_declaration(divider, "border-collapse", "collapse")
        _append_style_declaration(divider, "margin", "2em 0")
        body = soup.new_tag("tbody")
        row = soup.new_tag("tr")
        for side in ("left", "right"):
            rule_cell = soup.new_tag("td")
            rule_cell["class"] = [
                "layout-profile-scp-9100-relative-time-rule-cell",
                f"layout-profile-scp-9100-relative-time-rule-cell-{side}",
            ]
            _append_style_declaration(rule_cell, "width", "50%")
            _append_style_declaration(rule_cell, "padding", "0")
            _append_style_declaration(rule_cell, "border", "none")
            rule = soup.new_tag("div")
            rule["class"] = ["layout-profile-scp-9100-relative-time-rule"]
            _append_style_declaration(rule, "height", "0")
            _append_style_declaration(rule, "border", "none")
            _append_style_declaration(rule, "border-top", "1px solid #babdbf")
            rule_cell.append(rule)
            row.append(rule_cell)
        label_cell = soup.new_tag("td")
        label_cell["class"] = ["layout-profile-scp-9100-relative-time-label"]
        _append_style_declaration(label_cell, "width", "1%")
        _append_style_declaration(label_cell, "padding", "0 1em")
        _append_style_declaration(label_cell, "border", "none")
        _append_style_declaration(label_cell, "text-align", "center")
        label_cell.string = label_text
        row.insert(1, label_cell)
        body.append(row)
        divider.append(body)
        relative_time.replace_with(divider)
```

- [ ] **Step 3: Add SCP-9100-only non-wrapping label CSS**

```python
"scp-9100": (
    ".layout-profile-scp-9100-relative-time {page-break-inside: avoid;}"
    "\n.layout-profile-scp-9100-relative-time-label {white-space: nowrap; "
    "font-family: monospace;}"
),
```

- [ ] **Step 4: Run the target tests and verify they pass**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_transform.py -k "scp9100"`

Expected: both SCP-9100 tests pass.

### Task 3: Verify and rebuild

**Files:**
- No tracked generated files.

- [ ] **Step 1: Transform the real cached page and inspect counts**

Expected: `crom-thumbnail=0`, `Daydream.png=0`, `relativetime=0`, static dividers=92; all divider labels and event content remain.

- [ ] **Step 2: Run the full test suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Rebuild Featured outputs**

```powershell
.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

- [ ] **Step 4: Inspect both EPUB chapters**

Expected: each SCP-9100 XHTML contains no `.crom-thumbnail`, `Daydream.png`, or raw `.relativetime`; each contains 92 static dividers with two real rule elements and preserved labels, while event content remains.

- [ ] **Step 5: Commit only this task's source, tests, design, and plan**

```powershell
git add -- src/scp_epub/transform.py tests/test_transform.py docs/superpowers/specs/2026-08-24-scp-9100-hidden-media-timeline-design.md docs/superpowers/plans/2026-08-24-scp-9100-hidden-media-timeline.md
git commit -m "fix: restore SCP-9100 timeline dividers"
```
