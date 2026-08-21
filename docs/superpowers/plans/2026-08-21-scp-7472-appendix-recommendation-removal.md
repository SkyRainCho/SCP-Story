# SCP-7472 Appendix Recommendation Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the expanded recommendation panel from both SCP-7472 appendix chapters in the Featured EPUB and Kindle Scribe outputs without changing other pages.

**Architecture:** Reuse the existing exact-slug `PageOverride.remove_recommendation_panel` path. Add overrides for the two configured appendix slugs; no transformer or pipeline behavior changes are required because both already apply page-specific options to linked appendices.

**Tech Stack:** Python 3.11+, PyYAML configuration, pytest, BeautifulSoup-based XHTML transformation, EPUB ZIP inspection, Calibre `ebook-convert`.

---

## File map

- Modify `tests/test_config.py`: lock the production Featured configuration to all three SCP-7472 page slugs.
- Modify `config/featured-scp.yaml`: enable the existing cleanup option for the two appendix slugs.
- Generate ignored artifacts under `output/`: rebuild ordinary Featured EPUB and Kindle Scribe EPUB/AZW3.

### Task 1: Configure both SCP-7472 appendices

**Files:**
- Modify: `tests/test_config.py`
- Modify: `config/featured-scp.yaml`

- [ ] **Step 1: Strengthen the production configuration test**

Replace the single main-page assertion in `test_featured_config_loads_featured_archive_mode` with an exact set assertion:

```python
    assert {
        slug
        for slug, override in config.page_overrides.items()
        if override.remove_recommendation_panel
    } == {
        "scp-7472",
        "scp-7472/offset/1",
        "scp-7472/offset/2",
    }
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py::test_featured_config_loads_featured_archive_mode -q
```

Expected: FAIL because the actual set contains only `scp-7472`.

- [ ] **Step 3: Add exact appendix overrides**

Extend `page_overrides` in `config/featured-scp.yaml`:

```yaml
  scp-7472:
    remove_recommendation_panel: true
  scp-7472/offset/1:
    remove_recommendation_panel: true
  scp-7472/offset/2:
    remove_recommendation_panel: true
```

Keep all existing unrelated configuration intact.

- [ ] **Step 4: Run focused configuration and transformation tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py::test_featured_config_loads_featured_archive_mode tests/test_transform.py::test_removes_scp7472_recommendation_panel_without_removing_article_content -q
```

Expected: `2 passed`.

- [ ] **Step 5: Run the existing SCP-7472 build integration test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pipeline.py::test_build_volume_cleans_scp7472_recommendations_and_adds_offsets -q
```

Expected: `1 passed`, proving explicit attachments still enter the expected navigation group and page cleanup remains wired into the build.

- [ ] **Step 6: Commit only the configuration regression change**

Stage the exact `tests/test_config.py` and `config/featured-scp.yaml` hunks for this task, preserving pre-existing user changes in the same configuration file:

```powershell
git diff --check -- tests/test_config.py config/featured-scp.yaml
git add -p -- tests/test_config.py config/featured-scp.yaml
git diff --cached --check
git commit -m "fix: clean SCP-7472 appendix recommendations"
```

### Task 2: Run full regression tests

**Files:**
- Verify: all tracked source and tests

- [ ] **Step 1: Run the complete test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass with zero failures.

### Task 3: Rebuild and verify the ordinary Featured EPUB

**Files:**
- Generate: `output/epub/SCP基金会档案精选.epub`
- Generate: `output/reports/SCP基金会档案精选-report.json`

- [ ] **Step 1: Build the ordinary Featured edition**

Run:

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
```

Expected: exit code 0 and `Wrote ...\output\epub\SCP基金会档案精选.epub`.

- [ ] **Step 2: Inspect both appendix chapters**

Read `slugs` from the build report to calculate each chapter filename, run `ZipFile.testzip()`, and parse both XHTML chapters with BeautifulSoup. Assert for each chapter:

```python
assert "您可能也会喜欢" not in markup
assert "可以随便在这里添加你自己的文章" not in markup
assert "SCP-3790-J" not in markup
assert "SCP-6222" not in markup
assert "SCP-6247" not in markup
assert expected_body_text in soup.get_text(" ", strip=True)
```

Use these normal-body excerpts for the real chapters:

```python
expected_body_text_by_slug = {
    "scp-7472/offset/1": "SCP-7472是一栋位于波兰，波兹南的八层公寓大楼",
    "scp-7472/offset/2": "吱吱经济学的核心原则是稀缺性",
}
```

Expected: EPUB ZIP is valid, both recommendation panels are absent, and both normal article bodies remain.

### Task 4: Rebuild and verify the Kindle Scribe outputs

**Files:**
- Generate: `output/epub/SCP基金会档案精选-Kindle-Scribe.epub`
- Generate: `output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3`
- Generate: `output/reports/SCP基金会档案精选-Kindle-Scribe-report.json`

- [ ] **Step 1: Build the Kindle Scribe edition**

Run:

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

Expected: exit code 0 and both Scribe EPUB and AZW3 `Wrote` messages.

- [ ] **Step 2: Inspect both Scribe appendix chapters and the AZW3 header**

Repeat the ordinary EPUB chapter assertions for both appendix slugs, then verify:

```python
raw = azw3_path.read_bytes()
assert len(raw) > 1024
assert raw[60:68] == b"BOOKMOBI"
```

Expected: both Scribe chapters omit the recommendation content, retain normal body text, the EPUB ZIP is valid, and the AZW3 header is valid.

### Task 5: Final verification and handoff

**Files:**
- Verify: Git working tree and the three generated ebook files

- [ ] **Step 1: Re-run the full test suite immediately before completion**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 2: Confirm commit and dirty-worktree boundaries**

Run:

```powershell
git status --short
git show --stat --oneline HEAD
```

Expected: the task commit contains only the SCP-7472 test/config hunks; pre-existing user changes remain unstaged and unmodified by the task.

- [ ] **Step 3: Report affected documents and outputs**

List exactly these affected chapters:

- `SCP-7472 Offset 1` (`scp-7472/offset/1`)
- `SCP-7472 Offset 2` (`scp-7472/offset/2`)

Provide clickable absolute paths to the ordinary Featured EPUB, Scribe EPUB, Scribe AZW3, and their reports. State the fresh full-test count and the per-chapter inspection results.
