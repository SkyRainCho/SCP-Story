# Featured Facilities Body Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the full `基金会设施` appendix body, retain its facility dossier children, and include only the `设施种类定义` Wikidot tab in Featured EPUB and Kindle builds.

**Architecture:** Keep the existing `secure-facilities-locations--appendix-group` manifest node for compatibility, but resolve that specific `facility-links` group to its original source `FetchResult` instead of generated title-only HTML. Reuse the existing appendix tab-filter configuration by mapping generated group slugs back to their `AppendixSection` during page processing.

**Tech Stack:** Python 3.11+, pytest, BeautifulSoup, PyYAML, existing `scp_epub.pipeline` and `scp_epub.transform` APIs.

---

## File Map

- Modify `config/featured-scp.yaml`: declare the one included facilities tab and unwrap it.
- Modify `src/scp_epub/pipeline.py`: resolve content-bearing `facility-links` groups to source HTML and apply their appendix processing options.
- Modify `tests/test_config.py`: lock the Featured configuration contract.
- Modify `tests/test_pipeline.py`: cover source fetching, prefetched-result reuse, tab filtering, body retention, and child navigation.
- Verify generated files only under ignored `data/processed/` and `output/`; do not commit them.

### Task 1: Declare the facilities tab-selection contract

**Files:**
- Modify: `tests/test_config.py:260-290`
- Modify: `config/featured-scp.yaml:135-145`

- [ ] **Step 1: Write the failing configuration test**

Add these assertions to `test_featured_scp_config_uses_archive_mode_and_title_indexes` after the existing `page_tab_includes` assertion:

```python
    facilities = next(
        section
        for section in config.appendix.sections
        if section.slug == "secure-facilities-locations"
    )
    assert facilities.mode == "facility-links"
    assert facilities.include_tabs == ("设施种类定义",)
    assert facilities.unwrap_single_tab is True
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_config.py::test_featured_scp_config_uses_archive_mode_and_title_indexes -q
```

Expected: FAIL because the facilities section currently has empty `include_tabs` and `unwrap_single_tab == False`.

- [ ] **Step 3: Add the minimal configuration**

Change the facilities section in `config/featured-scp.yaml` to:

```yaml
    - title: 基金会设施
      url: /secure-facilities-locations
      mode: facility-links
      include_tabs:
        - 设施种类定义
      unwrap_single_tab: true
```

- [ ] **Step 4: Run the test and verify GREEN**

Run the same targeted command. Expected: `1 passed`.

- [ ] **Step 5: Prepare a focused commit without staging unrelated work**

```powershell
git add -- config/featured-scp.yaml tests/test_config.py
git diff --cached --check
git diff --cached --name-only
git commit -m "fix: configure featured facilities tab"
```

Expected staged files: only `config/featured-scp.yaml` and `tests/test_config.py`.

### Task 2: Use source HTML for facility-link group pages

**Files:**
- Modify: `tests/test_pipeline.py:920-1030`
- Modify: `src/scp_epub/pipeline.py:650-715`

- [ ] **Step 1: Write the failing source-fetch test**

Add this test near the other appendix fetch tests:

```python
def test_fetch_manifest_pages_uses_facility_source_for_generated_group(tmp_path: Path):
    source_url = f"{BASE_URL}/secure-facilities-locations"
    config = app_config(
        tmp_path,
        appendix=AppendixSpec(
            title="附录",
            slug="appendix",
            sections=(
                AppendixSection(
                    "基金会设施",
                    source_url,
                    "secure-facilities-locations",
                    mode="facility-links",
                ),
            ),
        ),
    )
    manifest = [
        PageRef(
            "基金会设施",
            source_url,
            "secure-facilities-locations--appendix-group",
            2,
            "appendix-group",
            parent_slug="appendix",
            order=1,
        )
    ]
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {"secure-facilities-locations": simple_page("设施源正文。")},
    )

    results = fetch_manifest_pages(config, manifest, fetcher=fetcher)

    assert [slug for slug, _url, _force in fetcher.calls] == [
        "secure-facilities-locations"
    ]
    assert "设施源正文。" in results[0].path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_pipeline.py::test_fetch_manifest_pages_uses_facility_source_for_generated_group -q
```

Expected: FAIL because the group is currently materialized with `appendix_group_html` and the source fetcher is not called.

- [ ] **Step 3: Implement facility-group source resolution**

Add this helper near `_tab_source_key`:

```python
def _appendix_group_source_key(
    config: AppConfig,
    entry: PageRef,
) -> tuple[str, str] | None:
    if entry.role != APPENDIX_GROUP_ROLE or config.appendix is None:
        return None
    for section in config.appendix.sections:
        if (
            section.mode == "facility-links"
            and entry.slug == _appendix_group_slug(section.slug)
        ):
            return section.slug, section.url
    return None
```

Update the first loop in `_fetch_manifest_results` so a content-bearing group is fetched while other groups remain generated:

```python
        if entry.role == APPENDIX_GROUP_ROLE:
            source_key = _appendix_group_source_key(config, entry)
            if source_key is not None and provided.get(source_key) is None:
                fetch_source[index] = source_key
            continue
```

Update the result-resolution loop:

```python
        if entry.role == APPENDIX_GROUP_ROLE:
            source_key = _appendix_group_source_key(config, entry)
            if source_key is not None:
                results.append(provided.get(source_key) or fetched[index])
                continue
            try:
                results.append(_write_appendix_group_fetch_result(cache, entry))
            except Exception as exc:
                results.append(exc)
            continue
```

- [ ] **Step 4: Run the targeted test and verify GREEN**

Run the Task 2 targeted command. Expected: `1 passed`.

- [ ] **Step 5: Add a failing prefetched-result reuse test**

Add:

```python
def test_fetch_manifest_pages_reuses_prefetched_facility_source_for_group(tmp_path: Path):
    source_url = f"{BASE_URL}/secure-facilities-locations"
    config = app_config(
        tmp_path,
        appendix=AppendixSpec(
            title="附录",
            slug="appendix",
            sections=(
                AppendixSection(
                    "基金会设施",
                    source_url,
                    "secure-facilities-locations",
                    mode="facility-links",
                ),
            ),
        ),
    )
    manifest = [
        PageRef(
            "基金会设施",
            source_url,
            "secure-facilities-locations--appendix-group",
            2,
            "appendix-group",
            parent_slug="appendix",
            order=1,
        )
    ]
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {"secure-facilities-locations": simple_page("预抓取设施正文。")},
    )
    prefetched = fetcher.fetch_page("secure-facilities-locations", source_url)
    fetcher.calls.clear()

    results = fetch_manifest_pages(
        config,
        manifest,
        fetcher=fetcher,
        appendix_fetch_results={
            ("secure-facilities-locations", source_url): prefetched
        },
    )

    assert fetcher.calls == []
    assert results == [prefetched]
```

- [ ] **Step 6: Run both tests**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_pipeline.py -k "facility_source_for_generated_group or prefetched_facility_source_for_group" -q
```

Expected: both pass with the Task 2 implementation.

- [ ] **Step 7: Commit only this task's hunks**

Because `src/scp_epub/pipeline.py` already contains unrelated uncommitted worker-limit changes, use interactive staging and inspect the staged patch:

```powershell
git add -- tests/test_pipeline.py
git add -p -- src/scp_epub/pipeline.py
git diff --cached --check
git diff --cached -- src/scp_epub/pipeline.py tests/test_pipeline.py
git commit -m "fix: retain facility source for appendix group"
```

Stage only hunks involving `_appendix_group_source_key` and `_fetch_manifest_results`.

### Task 3: Apply appendix tab options to the generated facility group

**Files:**
- Modify: `tests/test_pipeline.py:820-920`
- Modify: `src/scp_epub/pipeline.py:1255-1295`

- [ ] **Step 1: Write the failing build-level regression test**

Add near `test_build_volume_materializes_appendix_groups_and_unwraps_tab_children`:

```python
def test_build_volume_restores_facility_body_and_keeps_only_configured_tab(tmp_path: Path):
    source_url = f"{BASE_URL}/secure-facilities-locations"
    appendix = AppendixSpec(
        title="附录",
        slug="appendix",
        sections=(
            AppendixSection(
                "基金会设施",
                source_url,
                "secure-facilities-locations",
                mode="facility-links",
                include_tabs=("设施种类定义",),
                unwrap_single_tab=True,
            ),
        ),
    )
    config = app_config(tmp_path, include_linked_appendices=False, appendix=appendix)
    manifest = [
        PageRef("附录", f"{BASE_URL}/appendix", "appendix", 1, "appendix-group", order=1),
        PageRef(
            "基金会设施",
            source_url,
            "secure-facilities-locations--appendix-group",
            2,
            "appendix-group",
            parent_slug="appendix",
            order=2,
        ),
        PageRef(
            "安保设施档案：Site-19",
            f"{BASE_URL}/site-19",
            "site-19",
            3,
            "appendix-facility",
            parent_slug="secure-facilities-locations--appendix-group",
            order=3,
        ),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    facilities_html = """
      <div id="page-content">
        <p>设施简介正文。</p>
        <div class="site-grid"><p>站点列表正文。</p></div>
        <div class="site-grid"><p>区域列表正文。</p></div>
        <div class="yui-navset">
          <ul class="yui-nav">
            <li>进一步阅读</li><li>设施种类定义</li><li>关于此页面</li>
          </ul>
          <div class="yui-content">
            <div><p>进一步阅读正文。</p></div>
            <div><h2>设施种类</h2><p>站点与区域的定义。</p></div>
            <div><p>关于此页面正文。</p></div>
          </div>
        </div>
      </div>
    """
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "secure-facilities-locations": facilities_html,
            "site-19": simple_page("Site-19 档案正文。"),
        },
    )

    build_volume(config, "001-099", fetcher=fetcher)

    parent_path = (
        config.processed_dir
        / "test-volume"
        / "0002-secure-facilities-locations--appendix-group.xhtml"
    )
    parent = parent_path.read_text(encoding="utf-8")
    assert "设施简介正文。" in parent
    assert "站点列表正文。" in parent
    assert "区域列表正文。" in parent
    assert "设施种类" in parent
    assert "站点与区域的定义。" in parent
    assert "进一步阅读正文。" not in parent
    assert "关于此页面正文。" not in parent
    assert "tabview-epub" not in parent
    assert "标签：设施种类定义" not in parent
    assert manifest[2].parent_slug == "secure-facilities-locations--appendix-group"
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_pipeline.py::test_build_volume_restores_facility_body_and_keeps_only_configured_tab -q
```

Expected: FAIL because the generated group slug is not currently associated with the facilities `AppendixSection`, so all tab panels are expanded.

- [ ] **Step 3: Map section options to generated group slugs**

Replace the single appendix mapping in `_process_pages` with:

```python
    appendix_sections_by_entry_slug = {}
    if config.appendix is not None:
        for section in config.appendix.sections:
            entry_slug = (
                section.slug
                if section.mode == "page"
                else _appendix_group_slug(section.slug)
            )
            appendix_sections_by_entry_slug[entry_slug] = section
```

Then change:

```python
        appendix_section = appendix_sections_by_slug.get(entry.slug)
```

to:

```python
        appendix_section = appendix_sections_by_entry_slug.get(entry.slug)
```

- [ ] **Step 4: Run the regression test and verify GREEN**

Run the Task 3 command. Expected: `1 passed`.

- [ ] **Step 5: Run all appendix and pipeline target tests**

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_appendix.py tests/test_config.py tests/test_pipeline.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit only the Task 3 hunks**

```powershell
git add -- tests/test_pipeline.py
git add -p -- src/scp_epub/pipeline.py
git diff --cached --check
git diff --cached -- src/scp_epub/pipeline.py tests/test_pipeline.py
git commit -m "fix: apply tab options to facility group"
```

Stage only the `_process_pages` appendix-section mapping hunk from `pipeline.py`.

### Task 4: Full verification and Kindle rebuild

**Files:**
- Verify: `tests/`
- Generate: `data/processed/SCP基金会档案精选/`
- Generate: `output/epub/SCP基金会档案精选-Kindle.epub`
- Generate: `output/azw3/SCP基金会档案精选-Kindle.azw3`
- Generate: `output/reports/SCP基金会档案精选-Kindle-report.json`

- [ ] **Step 1: Run the full test suite**

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Rebuild the Featured Kindle edition**

```powershell
$env:PYTHONUNBUFFERED = '1'
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle
```

Expected output includes both:

```text
Wrote ...\output\epub\SCP基金会档案精选-Kindle.epub
Wrote ...\output\azw3\SCP基金会档案精选-Kindle.azw3
```

- [ ] **Step 3: Inspect the generated facilities XHTML inside the EPUB**

Use Python to locate the facilities group entry and assert required/excluded text:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import zipfile; p=r'output/epub/SCP基金会档案精选-Kindle.epub'; z=zipfile.ZipFile(p); n=next(x for x in z.namelist() if x.endswith('secure-facilities-locations--appendix-group.xhtml')); t=z.read(n).decode('utf-8'); required=['站点列表','区域列表','设施种类']; excluded=['进一步阅读正文','关于此页面正文','标签：设施种类定义']; assert all(x in t for x in required), [x for x in required if x not in t]; assert all(x not in t for x in excluded), [x for x in excluded if x in t]; assert z.testzip() is None; print(n, len(t), 'verified')"
```

Expected: the XHTML path, a substantial character count, and `verified`.

- [ ] **Step 4: Validate report and AZW3 metadata**

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import json,pathlib; d=json.loads(pathlib.Path(r'output/reports/SCP基金会档案精选-Kindle-report.json').read_text(encoding='utf-8')); assert not d.get('missing_pages'); print('pages', d['page_count'], 'missing_assets', len(d.get('missing_assets', [])))"
& 'C:\Program Files\Calibre2\ebook-meta.exe' 'output\azw3\SCP基金会档案精选-Kindle.azw3'
```

Expected: no missing pages; Calibre reports title `SCP基金会档案精选`, author `SCP基金会`, and language `zho`.

- [ ] **Step 5: Confirm unrelated worktree changes remain intact**

```powershell
git status --short --branch
git diff -- src/scp_epub/fetcher.py tests/test_fetcher.py
```

Expected: the pre-existing fetcher/test changes remain present and were not included in this feature's commits. Generated EPUB, AZW3, reports, caches, and processed XHTML remain ignored.
