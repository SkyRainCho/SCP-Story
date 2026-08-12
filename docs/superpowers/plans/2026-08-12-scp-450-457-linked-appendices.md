# SCP-450 and SCP-457 Linked Appendices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Include the requested story once beneath SCP-450 and include SCP-1689 followed by SCP-124 once beneath SCP-457 in both Featured and Series 1 builds.

**Architecture:** Reuse `explicit_linked_appendices` in both YAML configurations and the existing grouping, fetch, slug-deduplication, and one-level inclusion pipeline. No production Python or global scanning-rule change is planned.

**Tech Stack:** YAML configuration, Python 3.11+, pytest, existing SCP EPUB pipeline.

---

## File map and dirty-worktree boundary

- Modify `config/featured-scp.yaml`: add the SCP-450 and SCP-457 relationships without disturbing the user's existing uncommitted SCP-455 declaration.
- Modify `config/series-1.yaml`: add the same relationships.
- Modify `tests/test_config.py`: assert exact titles, URLs, slugs, and order in both configurations without disturbing the existing uncommitted SCP-455 assertion.
- Modify `tests/test_pipeline.py`: exercise both groups, deterministic order, deduplication, and one-level behavior without disturbing the existing uncommitted SCP-455 test.

The worktree also contains unrelated edits in `src/scp_epub/fetcher.py`, `src/scp_epub/pipeline.py`, and `tests/test_fetcher.py`. Preserve all existing edits. Use patch-specific staging for mixed files and inspect the staged diff before committing.

### Task 1: Drive both configuration declarations with failing tests

**Files:**
- Modify: `tests/test_config.py`
- Modify: `config/featured-scp.yaml`
- Modify: `config/series-1.yaml`

- [ ] **Step 1: Write exact-declaration tests before changing YAML**

Add a helper and two tests near the existing SCP-517 configuration tests:

```python
def assert_scp_450_457_appendices(config_path: str) -> None:
    config = load_config(Path(config_path))

    assert [
        (link.title, link.url, link.slug)
        for link in config.explicit_linked_appendices["scp-450"]
    ] == [
        (
            "在恐惧中永世逃亡",
            "https://scp-wiki-cn.wikidot.com/but-when-they-opened-it-they-turned-and-swift",
            "but-when-they-opened-it-they-turned-and-swift",
        )
    ]
    assert [
        (link.title, link.url, link.slug)
        for link in config.explicit_linked_appendices["scp-457"]
    ] == [
        ("SCP-1689", "https://scp-wiki-cn.wikidot.com/scp-1689", "scp-1689"),
        ("SCP-124", "https://scp-wiki-cn.wikidot.com/scp-124", "scp-124"),
    ]


def test_featured_scp_config_includes_scp_450_457_appendices():
    assert_scp_450_457_appendices("config/featured-scp.yaml")


def test_series_1_config_includes_scp_450_457_appendices():
    assert_scp_450_457_appendices("config/series-1.yaml")
```

- [ ] **Step 2: Run the two tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_config.py -k scp_450_457_appendices
```

Expected: both tests fail with `KeyError: 'scp-450'` because neither configuration declares the new relationships yet.

- [ ] **Step 3: Add the minimal declarations to Featured**

Under `explicit_linked_appendices` in `config/featured-scp.yaml`, add:

```yaml
  scp-450:
    - title: 在恐惧中永世逃亡
      url: https://scp-wiki-cn.wikidot.com/but-when-they-opened-it-they-turned-and-swift
  scp-457:
    - title: SCP-1689
      url: https://scp-wiki-cn.wikidot.com/scp-1689
    - title: SCP-124
      url: https://scp-wiki-cn.wikidot.com/scp-124
```

- [ ] **Step 4: Add the same declarations to Series 1**

Under `explicit_linked_appendices` in `config/series-1.yaml`, add the identical `scp-450` and `scp-457` blocks after the existing `scp-517` block.

- [ ] **Step 5: Run configuration tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_config.py -k "scp_450_457_appendices or scp_517_incident_appendix"
```

Expected: all selected tests pass and the existing SCP-517 declaration remains intact.

### Task 2: Prove grouping, order, deduplication, and one-level inclusion

**Files:**
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Add an end-to-end pipeline regression**

Create one configuration with `scp-450` mapped to the story and `scp-457` mapped to SCP-1689 then SCP-124. Write a manifest containing SCP-450 and SCP-457, and provide `FakeFetcher` pages where each main page links to its configured attachment and each attachment links to `/unrelated-followup`.

Assert the report's `slugs` are exactly:

```python
[
    "scp-450",
    "scp-450--linked-appendices",
    "but-when-they-opened-it-they-turned-and-swift",
    "scp-457",
    "scp-457--linked-appendices",
    "scp-1689",
    "scp-124",
]
```

Also assert each attachment slug occurs once in `fetcher.calls`, `unrelated-followup` is never fetched, and the three processed XHTML files contain distinct body markers.

- [ ] **Step 2: Run the pipeline regression**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_pipeline.py::test_build_volume_groups_configured_scp_450_457_appendices_once_without_recursion
```

Expected: PASS because the production pipeline already implements the approved general behavior. Task 1 supplies the mandatory RED phase for the product configuration change. If this test exposes an existing ordering or deduplication defect, stop and use `superpowers:systematic-debugging` before changing production Python.

- [ ] **Step 3: Run linked-appendix regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_linked_appendices.py tests/test_pipeline.py -k "linked_appendix or linked_appendices or scp_450 or scp_457"
```

Expected: all selected tests pass.

### Task 3: Verify real Featured and Series 1 outputs

**Files:**
- Verification only; generated outputs remain ignored.

- [ ] **Step 1: Run focused and complete tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_config.py tests/test_pipeline.py tests/test_linked_appendices.py
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: both commands finish with zero failures.

- [ ] **Step 2: Build Featured and Series 1 volume 400-499**

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
.\.venv\Scripts\python.exe -m scp_epub --config config/series-1.yaml build --volume 400-499
```

Expected outputs:

- `output/epub/SCP基金会档案精选.epub`
- `output/epub/SCP基金会档案-故事系列-第1卷-第5册.epub`

- [ ] **Step 3: Inspect reports and EPUBs programmatically**

For both reports, assert the SCP-450 subsequence is main, group, story; assert the SCP-457 subsequence is main, group, SCP-1689, SCP-124; assert every attachment occurs once and none is in `missing_pages`.

Open both EPUBs with `zipfile`, assert `testzip() is None`, locate exactly one XHTML file for each attachment, and verify these source markers:

```python
markers = {
    "but-when-they-opened-it-they-turned-and-swift": "在恐惧中永世逃亡",
    "scp-1689": "SCP-1689",
    "scp-124": "SCP-124",
}
```

### Task 4: Commit only this feature and preserve existing dirty work

**Files:**
- Review the four modified config/test files.

- [ ] **Step 1: Stage only the new appendix hunks**

Use a temporary zero-context patch derived from `git diff -U0` or interactive hunk staging for mixed files. Do not stage the pre-existing SCP-455, worker, fetcher, or appendix-ordering changes.

- [ ] **Step 2: Inspect and commit**

```powershell
git diff --cached --check
git diff --cached --name-only
git diff --cached
git commit -m "feat: attach SCP-450 and SCP-457 appendices"
```

Expected: the commit contains only both configurations and their SCP-450/SCP-457 tests.

- [ ] **Step 3: Confirm the dirty-worktree boundary**

```powershell
git status --short
```

Expected: the user's pre-existing unrelated modifications remain unstaged, and generated cache/output files remain ignored.
