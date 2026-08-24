# SCP-9100 Hidden Media and Timeline Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove SCP-9100's web-only thumbnail and all EPUB-incompatible relative-time separators without affecting other pages.

**Architecture:** Add one slug-gated DOM cleanup helper to the existing transform pipeline. The helper removes nodes by their page-native semantic classes before asset collection, so hidden media cannot enter the EPUB manifest.

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


def test_scp9100_removes_web_only_thumbnail_and_relative_time_separators():
    result = transform_page(page_ref("scp-9100"), _scp9100_web_only_elements_html(), BASE_URL)
    soup = soup_fragment(result.xhtml)
    assert soup.select(".crom-thumbnail, .relativetime") == []
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

Expected: target-page test fails because the thumbnail and separators remain; isolation test passes.

### Task 2: Implement the page-specific cleanup

**Files:**
- Modify: `src/scp_epub/transform.py`
- Test: `tests/test_transform.py`

- [ ] **Step 1: Add the slug-gated transform call**

```python
if entry.slug == "scp-9100":
    _remove_scp_9100_web_only_elements(page_content)
```

- [ ] **Step 2: Add the minimal DOM cleanup helper**

```python
def _remove_scp_9100_web_only_elements(page_content: Tag) -> None:
    for element in list(page_content.select(".crom-thumbnail, .relativetime")):
        element.decompose()
```

- [ ] **Step 3: Run the target tests and verify they pass**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_transform.py -k "scp9100"`

Expected: both SCP-9100 tests pass.

### Task 3: Verify and rebuild

**Files:**
- No tracked generated files.

- [ ] **Step 1: Transform the real cached page and inspect counts**

Expected: `crom-thumbnail=0`, `Daydream.png=0`, `relativetime=0`; event content remains.

- [ ] **Step 2: Run the full test suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Rebuild Featured outputs**

```powershell
.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

- [ ] **Step 4: Inspect both EPUB chapters**

Expected: each SCP-9100 XHTML contains no `.crom-thumbnail`, `Daydream.png`, or `.relativetime`, while event content remains.

- [ ] **Step 5: Commit only this task's source, tests, design, and plan**

```powershell
git add -- src/scp_epub/transform.py tests/test_transform.py docs/superpowers/specs/2026-08-24-scp-9100-hidden-media-timeline-design.md docs/superpowers/plans/2026-08-24-scp-9100-hidden-media-timeline.md
git commit -m "fix: remove SCP-9100 web-only elements"
```
