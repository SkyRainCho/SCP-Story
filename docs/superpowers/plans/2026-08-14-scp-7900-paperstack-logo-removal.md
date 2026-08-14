# SCP-7900 Paperstack Logo Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Paperstack theme decoration logo from SCP-7900 only, while preserving all ordinary article images and synchronizing Featured, Kindle Scribe, and Series 8 outputs.

**Architecture:** Add an opt-in boolean page override that is enabled for `scp-7900` in the Featured and Series 8 configs. Propagate it into page transformation, where one narrowly fingerprinted cleanup helper removes only a `div.logo` containing the exact Paperstack `lgtrans.png` resource before asset collection.

**Tech Stack:** Python 3.11+, dataclasses, BeautifulSoup, PyYAML-backed configuration, pytest, existing SCP EPUB pipeline and EPUB ZIP inspection.

---

## File map

- Modify `src/scp_epub/models.py`: add the page-level configuration field.
- Modify `src/scp_epub/config.py`: accept and validate the new boolean field.
- Modify `src/scp_epub/transform.py`: add the transform option and exact Paperstack logo cleanup.
- Modify `src/scp_epub/pipeline.py`: propagate the page override into transformation.
- Modify `config/featured-scp.yaml`: enable the option for Featured SCP-7900.
- Modify `config/series-8.yaml`: enable the option for Series 8 SCP-7900.
- Modify `tests/test_config.py`: cover parsing, invalid values, and both production configs.
- Modify `tests/test_transform.py`: cover exact removal and preservation cases.
- Modify `tests/test_pipeline.py`: prove the configured value reaches the real build path.

### Task 1: Add and configure the explicit page override

**Files:**
- Modify: `src/scp_epub/models.py`
- Modify: `src/scp_epub/config.py`
- Modify: `config/featured-scp.yaml`
- Modify: `config/series-8.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing parser and production-config tests**

Extend `test_load_config_parses_page_overrides_and_inline_documents` so its YAML contains:

```yaml
  scp-1234:
    remove_paperstack_theme_logo: true
```

and assert:

```python
assert override.remove_paperstack_theme_logo is True
```

Add this case to `test_load_config_rejects_invalid_page_overrides`:

```python
(
    """\
  scp-7900:
    remove_paperstack_theme_logo: enabled
""",
    "page_overrides.scp-7900.remove_paperstack_theme_logo must be a boolean",
),
```

Add a production-config test:

```python
@pytest.mark.parametrize(
    "config_path",
    ["config/featured-scp.yaml", "config/series-8.yaml"],
)
def test_production_configs_remove_scp7900_paperstack_theme_logo(config_path: str):
    config = load_config(Path(config_path))

    assert config.page_overrides["scp-7900"].remove_paperstack_theme_logo is True
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py -k "paperstack_theme_logo or parses_page_overrides" -q
```

Expected: FAIL because the unknown configuration key is rejected and `PageOverride` has no `remove_paperstack_theme_logo` field.

- [ ] **Step 3: Add the model and strict parser field**

In `PageOverride` in `src/scp_epub/models.py`, add:

```python
remove_paperstack_theme_logo: bool = False
```

In `_load_page_overrides` in `src/scp_epub/config.py`, add the key to `_reject_unknown_keys` and construct the field with:

```python
remove_paperstack_theme_logo=_optional_bool(
    override.get("remove_paperstack_theme_logo", False),
    f"{override_name}.remove_paperstack_theme_logo",
),
```

- [ ] **Step 4: Enable the field only for SCP-7900 in both production configs**

Under `page_overrides` in both YAML files, add:

```yaml
  scp-7900:
    remove_paperstack_theme_logo: true
```

`config/series-8.yaml` currently has no `page_overrides`, so insert that mapping before `volumes`. In the dirty `config/featured-scp.yaml`, preserve the pre-existing user-owned `scp-455` change and stage only the new SCP-7900 hunk.

- [ ] **Step 5: Run the complete config test module**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py -q
```

Expected: all tests in `tests/test_config.py` PASS.

- [ ] **Step 6: Commit Task 1**

Stage `src/scp_epub/models.py`, `src/scp_epub/config.py`, `config/series-8.yaml`, and `tests/test_config.py`. Stage only the SCP-7900 hunk from `config/featured-scp.yaml` using `git add -p`.

```powershell
git diff --cached --check
git commit -m "feat: configure SCP-7900 theme logo removal"
```

### Task 2: Remove only the exact Paperstack decoration during transformation

**Files:**
- Modify: `src/scp_epub/transform.py`
- Test: `tests/test_transform.py`

- [ ] **Step 1: Write the failing exact-removal test**

Add this test to `tests/test_transform.py`:

```python
def test_removes_configured_paperstack_theme_logo_and_preserves_article_image():
    html = """
    <html><body><div id="page-content">
      <div class="logo">
        <img src="https://scp-wiki.wdfiles.com/local--files/theme%3Apaperstack/lgtrans.png"
             alt="lgtrans.png" class="image">
      </div>
      <div class="scp-image-block">
        <img src="https://scp-wiki.wdfiles.com/local--files/scp-7900/whaleskin"
             alt="whaleskin" class="image">
      </div>
      <p>正文</p>
    </div></body></html>
    """

    result = transform_page(
        PageRef("SCP-7900", BASE_URL, "scp-7900", 1, "scp"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_paperstack_theme_logo=True),
    )

    soup = BeautifulSoup(result.xhtml, "html.parser")
    assert soup.select_one("div.logo") is None
    assert soup.find("img", alt="lgtrans.png") is None
    assert soup.find("img", alt="whaleskin") is not None
    assert "https://scp-wiki.wdfiles.com/local--files/theme%3Apaperstack/lgtrans.png" not in result.asset_urls
    assert "https://scp-wiki.wdfiles.com/local--files/scp-7900/whaleskin" in result.asset_urls
```

- [ ] **Step 2: Add preservation tests**

Add one parametrized test proving the cleanup is opt-in and fingerprinted:

```python
@pytest.mark.parametrize(
    ("enabled", "source"),
    [
        (
            False,
            "https://scp-wiki.wdfiles.com/local--files/theme%3Apaperstack/lgtrans.png",
        ),
        (True, "https://example.test/article-logo.png"),
    ],
)
def test_paperstack_logo_cleanup_preserves_unconfigured_or_different_images(
    enabled: bool,
    source: str,
):
    html = f"""
    <html><body><div id="page-content">
      <div class="logo"><img src="{source}" alt="kept-logo"></div>
    </div></body></html>
    """

    result = transform_page(
        PageRef("SCP-7900", BASE_URL, "scp-7900", 1, "scp"),
        html,
        BASE_URL,
        page_options=PageTransformOptions(remove_paperstack_theme_logo=enabled),
    )

    assert BeautifulSoup(result.xhtml, "html.parser").find("img", alt="kept-logo") is not None
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_transform.py -k paperstack -q
```

Expected: FAIL because `PageTransformOptions` does not accept `remove_paperstack_theme_logo`.

- [ ] **Step 4: Implement the minimal transform option and exact matcher**

Add this field to `PageTransformOptions`:

```python
remove_paperstack_theme_logo: bool = False
```

Add this constant and helper in `src/scp_epub/transform.py`:

```python
PAPERSTACK_THEME_LOGO_PATH = "/local--files/theme%3apaperstack/lgtrans.png"


def _remove_paperstack_theme_logo(page_content: Tag) -> None:
    for container in list(page_content.select("div.logo")):
        image = container.find("img")
        if not isinstance(image, Tag):
            continue
        source = image.get("src")
        if not isinstance(source, str):
            continue
        if urlparse(source.strip()).path.casefold() == PAPERSTACK_THEME_LOGO_PATH:
            container.decompose()
```

Call it from `_apply_page_cleanup_options` before layout-profile handling:

```python
if options.remove_paperstack_theme_logo:
    _remove_paperstack_theme_logo(page_content)
```

This intentionally does not gate on `entry.slug`; the explicit page override supplies the scope, while the resource fingerprint supplies deletion safety.

- [ ] **Step 5: Run focused and complete transform tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_transform.py -k paperstack -q
.\.venv\Scripts\python.exe -m pytest tests/test_transform.py -q
```

Expected: all focused and complete transform tests PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add src/scp_epub/transform.py tests/test_transform.py
git diff --cached --check
git commit -m "fix: remove configured Paperstack theme logo"
```

### Task 3: Propagate the configured value through the build pipeline

**Files:**
- Modify: `src/scp_epub/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing build-path regression test**

Add a test using the existing `app_config`, `FakeFetcher`, and `write_manifest` helpers:

```python
def test_build_volume_applies_paperstack_theme_logo_override(tmp_path: Path):
    config = app_config(
        tmp_path,
        include_linked_appendices=False,
        page_overrides={
            "scp-7900": PageOverride(remove_paperstack_theme_logo=True),
        },
    )
    from scp_epub.manifest import write_manifest

    write_manifest(
        [
            PageRef(
                "SCP-7900",
                f"{BASE_URL}/scp-7900",
                "scp-7900",
                1,
                "scp",
                order=1,
            )
        ],
        config.manifest_dir / "test-volume.json",
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-7900": """
              <html><body><div id="page-content">
                <div class="logo"><img
                  src="https://scp-wiki.wdfiles.com/local--files/theme%3Apaperstack/lgtrans.png"
                  alt="lgtrans.png"></div>
                <p>正文</p>
              </div></body></html>
            """,
        },
    )

    build_volume(config, "001-099", fetcher=fetcher)

    chapter = (
        config.processed_dir / "test-volume" / "0001-scp-7900.xhtml"
    ).read_text(encoding="utf-8")
    assert "lgtrans.png" not in chapter
    assert "正文" in chapter
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -k paperstack_theme_logo_override -q
```

Expected: FAIL because `_page_transform_options` does not copy the configured boolean into `PageTransformOptions`, leaving the logo in processed XHTML.

- [ ] **Step 3: Add the one-field propagation**

In `_page_transform_options` in `src/scp_epub/pipeline.py`, add:

```python
remove_paperstack_theme_logo=bool(
    override and override.remove_paperstack_theme_logo
),
```

- [ ] **Step 4: Run focused and complete pipeline tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -k paperstack_theme_logo_override -q
.\.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -q
```

Expected: the focused test and every pipeline test PASS.

- [ ] **Step 5: Commit Task 3 without staging user-owned changes**

Both `src/scp_epub/pipeline.py` and `tests/test_pipeline.py` already contain unrelated user-owned working-tree changes. Stage only the new propagation and regression-test hunks with `git add -p` or an exact cached patch.

```powershell
git diff --cached --check
git commit -m "fix: apply SCP-7900 logo override in builds"
```

### Task 4: Run full verification and rebuild every affected output

**Files:**
- Generated only: `output/epub/`, `output/azw3/`, `output/reports/`

- [ ] **Step 1: Run the full test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Build the Featured ordinary EPUB**

Run:

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
```

Expected: `output/epub/SCP基金会档案精选.epub` is freshly written.

- [ ] **Step 3: Build the Featured Kindle Scribe EPUB and AZW3**

Run:

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

Expected outputs:

```text
output/epub/SCP基金会档案精选-Kindle-Scribe.epub
output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3
```

- [ ] **Step 4: Build Series 8 volume 7900-7999**

Run:

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/series-8.yaml build --volume 7900-7999
```

Expected: `output/epub/SCP基金会档案-故事系列-第8卷-第10册.epub` is freshly written.

- [ ] **Step 5: Inspect the three EPUBs and the AZW3**

For each EPUB:

1. Run `ZipFile.testzip()` and require `None`.
2. Resolve the SCP-7900 chapter filename from the matching report's `slugs` order.
3. Parse the chapter with BeautifulSoup.
4. Assert `div.logo` and `img[src*="theme%3Apaperstack/lgtrans.png"]` are absent.
5. Assert the ordinary article images `whaleskin`, `NotreDame`, `cave1`, `grotto`, and `seacave` remain.

For the AZW3, require a non-trivial file size and `BOOKMOBI` at bytes 60–67.

- [ ] **Step 6: Verify repository boundaries**

Run:

```powershell
git status --short
git diff --check
git log -5 --oneline
```

Expected: generated outputs remain ignored, the SCP-7900 commits are present, and the pre-existing unrelated edits in `config/featured-scp.yaml`, `src/scp_epub/fetcher.py`, `src/scp_epub/pipeline.py`, `tests/test_fetcher.py`, and `tests/test_pipeline.py` remain unstaged unless they were already committed separately by the user.
