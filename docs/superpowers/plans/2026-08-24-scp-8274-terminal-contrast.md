# SCP-8274 Terminal Contrast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give SCP-8274 terminal diary boxes an explicit high-contrast light-background/dark-text color pair without affecting other content.

**Architecture:** Add one `scp-8274` entry to the existing `PAGE_EPUB_STYLE_RULES` map. Verify the generated page CSS and cross-page isolation through `transform_page`, then rebuild both Featured formats.

**Tech Stack:** Python 3.11+, BeautifulSoup, pytest, existing SCP EPUB build CLI.

---

### Task 1: Add regression tests

**Files:**
- Test: `tests/test_transform.py`

- [ ] **Step 1: Add a minimal terminal diary fixture and target-page test**

```python
def _scp8274_terminal_diary_html() -> str:
    return """
    <html><body><div id="page-content">
      <div class="terminal"><div class="terminal-content"><div class="terminal-text">
        <div class="blockquote"><p>日记条目#1：保留的正文。</p></div>
      </div></div></div>
    </div></body></html>
    """


def test_scp8274_sets_high_contrast_terminal_diary_colors():
    result = transform_page(page_ref("scp-8274"), _scp8274_terminal_diary_html(), BASE_URL)
    assert ".terminal .blockquote {background: #f2f2f2; color: #1a1a1a; border: 1px dashed #777;}" in result.xhtml
```

- [ ] **Step 2: Add a cross-page isolation test**

```python
def test_scp8274_terminal_diary_colors_do_not_affect_other_pages():
    result = transform_page(page_ref("scp-8273"), _scp8274_terminal_diary_html(), BASE_URL)
    assert "background: #f2f2f2; color: #1a1a1a" not in result.xhtml
```

- [ ] **Step 3: Run tests and verify the target test fails**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_transform.py -k "scp8274"`

Expected: target-page test fails because the page-specific color pair is absent; isolation test passes.

### Task 2: Add the page style

**Files:**
- Modify: `src/scp_epub/transform.py`
- Test: `tests/test_transform.py`

- [ ] **Step 1: Add the exact rule to `PAGE_EPUB_STYLE_RULES`**

```python
"scp-8274": (
    ".terminal .blockquote {background: #f2f2f2; color: #1a1a1a; "
    "border: 1px dashed #777;}"
),
```

- [ ] **Step 2: Run the target tests**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_transform.py -k "scp8274"`

Expected: both tests pass.

### Task 3: Verify, rebuild, and commit

**Files:**
- No tracked generated files.

- [ ] **Step 1: Transform the real SCP-8274 snapshot**

Expected: every `.terminal .blockquote` remains present and the exact high-contrast rule is emitted once.

- [ ] **Step 2: Run the full test suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Rebuild Featured outputs**

```powershell
.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

- [ ] **Step 4: Inspect both EPUB chapters**

Expected: each SCP-8274 XHTML contains the diary boxes and the exact high-contrast page rule.

- [ ] **Step 5: Commit only this task's files**

```powershell
git add -- src/scp_epub/transform.py tests/test_transform.py docs/superpowers/specs/2026-08-24-scp-8274-terminal-contrast-design.md docs/superpowers/plans/2026-08-24-scp-8274-terminal-contrast.md
git commit -m "fix: improve SCP-8274 diary contrast"
```
