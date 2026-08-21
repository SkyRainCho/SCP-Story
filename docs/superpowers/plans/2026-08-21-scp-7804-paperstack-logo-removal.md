# SCP-7804 Paperstack Logo Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Paperstack theme logo from SCP-7804 in Featured, Kindle Scribe, and Series 8 outputs while preserving the article image and body.

**Architecture:** Reuse the existing exact-slug `PageOverride.remove_paperstack_theme_logo` path already used by SCP-7900. Add SCP-7804 to the Featured and Series 8 production configurations; transformer and pipeline code remain unchanged.

**Tech Stack:** Python 3.11+, PyYAML configuration, pytest, BeautifulSoup XHTML transformation, EPUB ZIP inspection, Calibre `ebook-convert`.

---

## File map

- Modify `tests/test_config.py`: assert both production configurations enable the option for SCP-7804 and SCP-7900.
- Modify `config/featured-scp.yaml`: enable the existing option for Featured SCP-7804.
- Modify `config/series-8.yaml`: enable the existing option for Series 8 SCP-7804.
- Generate ignored outputs under `output/`: rebuild Featured ordinary/Scribe and Series 8 第9册.

### Task 1: Configure SCP-7804 in both production editions

**Files:**
- Modify: `tests/test_config.py`
- Modify: `config/featured-scp.yaml`
- Modify: `config/series-8.yaml`

- [ ] **Step 1: Write the failing production configuration test**

Replace the SCP-7900-only assertion with:

```python
@pytest.mark.parametrize(
    "config_path",
    ["config/featured-scp.yaml", "config/series-8.yaml"],
)
def test_production_configs_remove_paperstack_theme_logos(config_path: str):
    config = load_config(Path(config_path))

    assert {
        slug
        for slug, override in config.page_overrides.items()
        if override.remove_paperstack_theme_logo
    } == {"scp-7804", "scp-7900"}
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py::test_production_configs_remove_paperstack_theme_logos -q
```

Expected: two failures because each actual set contains only `scp-7900`.

- [ ] **Step 3: Add the minimal Featured override**

Add alongside the existing SCP-7900 override in `config/featured-scp.yaml`:

```yaml
  scp-7804:
    remove_paperstack_theme_logo: true
```

- [ ] **Step 4: Add the minimal Series 8 override**

Add alongside the existing SCP-7900 override in `config/series-8.yaml`:

```yaml
  scp-7804:
    remove_paperstack_theme_logo: true
```

- [ ] **Step 5: Run focused configuration and transformation tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py::test_production_configs_remove_paperstack_theme_logos tests/test_transform.py::test_removes_configured_paperstack_theme_logo_and_preserves_article_image tests/test_transform.py::test_paperstack_logo_cleanup_preserves_unconfigured_or_different_images -q
```

Expected: all focused cases pass.

- [ ] **Step 6: Commit only SCP-7804 hunks**

Use interactive staging for `config/featured-scp.yaml` because it contains pre-existing user changes:

```powershell
git diff --check -- tests/test_config.py config/featured-scp.yaml config/series-8.yaml
git add -p -- config/featured-scp.yaml
git add -- config/series-8.yaml tests/test_config.py
git diff --cached --check
git commit -m "fix: remove SCP-7804 theme logo"
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

### Task 3: Build and verify ordinary Featured EPUB

**Files:**
- Generate: `output/epub/SCP基金会档案精选.epub`
- Generate: `output/reports/SCP基金会档案精选-report.json`

- [ ] **Step 1: Build ordinary Featured**

Run:

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
```

Expected: exit code 0 and the Featured EPUB write message.

- [ ] **Step 2: Inspect the SCP-7804 chapter**

Use the report `slugs` list to calculate the actual chapter member. Assert:

```python
assert zip_file.testzip() is None
assert "lgtrans.png" not in markup
assert "theme%3Apaperstack" not in markup
assert soup.find("img", alt="radiomast") is not None
assert "SCP-7804是一发射塔式天线" in soup.get_text(" ", strip=True)
```

### Task 4: Build and verify Kindle Scribe outputs

**Files:**
- Generate: `output/epub/SCP基金会档案精选-Kindle-Scribe.epub`
- Generate: `output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3`
- Generate: `output/reports/SCP基金会档案精选-Kindle-Scribe-report.json`

- [ ] **Step 1: Build Kindle Scribe Featured**

Run:

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

Expected: exit code 0 and both Scribe EPUB/AZW3 write messages.

- [ ] **Step 2: Inspect Scribe chapter and AZW3**

Repeat the SCP-7804 chapter assertions from Task 3, then assert:

```python
raw = azw3_path.read_bytes()
assert len(raw) > 1024
assert raw[60:68] == b"BOOKMOBI"
```

### Task 5: Build and verify Series 8 第9册

**Files:**
- Generate: `output/epub/SCP基金会档案-故事系列-第8卷-第9册.epub`
- Generate: `output/reports/SCP基金会档案-故事系列-第8卷-第9册-report.json`

- [ ] **Step 1: Build the `7800-7899` volume**

Run:

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/series-8.yaml build --volume 7800-7899
```

Expected: exit code 0 and the Series 8 第9册 EPUB write message.

- [ ] **Step 2: Inspect Series 8 SCP-7804**

Repeat Task 3's EPUB ZIP, theme logo absence, `radiomast`, and body-text assertions against the Series 8 report and EPUB.

### Task 6: Final verification and handoff

**Files:**
- Verify: Git state and all four generated ebook files

- [ ] **Step 1: Run fresh complete tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 2: Verify task commit boundaries**

Run:

```powershell
git status --short
git show --stat --oneline HEAD
```

Expected: the implementation commit contains only SCP-7804 configuration/test changes; pre-existing user modifications remain unstaged.

- [ ] **Step 3: Report results**

Provide clickable absolute links to Featured EPUB, Scribe EPUB/AZW3, Series 8 第9册 EPUB, and reports. State that only SCP-7804 is newly affected, `radiomast` remains, the theme logo is absent in all three EPUBs, AZW3 is valid, and include the fresh test count.
