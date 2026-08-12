# SCP-517 Incident Appendix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Include `事件517-1997-M` exactly once beneath SCP-517's “原文附属文档” group in both Featured and Series 1 builds.

**Architecture:** Reuse the existing `explicit_linked_appendices` configuration and linked-appendix merge pipeline without changing discovery code. Both configuration files declare the same title and URL; existing slug-based merging provides deterministic deduplication if scanning later discovers the same page.

**Tech Stack:** YAML configuration, Python 3.11+, pytest, existing EPUB pipeline.

---

## File map and dirty-worktree boundary

- Modify `config/featured-scp.yaml`: declare the SCP-517 incident page for Featured.
- Modify `config/series-1.yaml`: declare the same incident page for Series 1.
- Modify `tests/test_config.py`: verify both concrete configurations.
- Modify `tests/test_pipeline.py`: verify grouping, one-level inclusion, and duplicate elimination.

The current worktree has unrelated edits in `config/featured-scp.yaml`, `src/scp_epub/fetcher.py`, `src/scp_epub/pipeline.py`, `tests/test_config.py`, `tests/test_fetcher.py`, and `tests/test_pipeline.py`. Preserve them. Use interactive hunk staging for mixed files and inspect `git diff --cached`; never stage an entire mixed file.

### Task 1: Declare the incident in both configurations

**Files:**
- Modify: `tests/test_config.py`
- Modify: `config/featured-scp.yaml`
- Modify: `config/series-1.yaml`

- [ ] **Step 1: Write failing exact-declaration tests**

Add this helper near the concrete configuration tests:

```python
def assert_scp_517_incident_appendix(config_path: str) -> None:
    config = load_config(Path(config_path))

    assert [
        (link.title, link.url, link.slug)
        for link in config.explicit_linked_appendices["scp-517"]
    ] == [
        (
            "事件517-1997-M",
            "https://scp-wiki-cn.wikidot.com/incident-517-1997-m",
            "incident-517-1997-m",
        )
    ]


def test_featured_scp_config_includes_scp_517_incident_appendix():
    assert_scp_517_incident_appendix("config/featured-scp.yaml")


def test_series_1_config_includes_scp_517_incident_appendix():
    assert_scp_517_incident_appendix("config/series-1.yaml")
```

- [ ] **Step 2: Run both tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_config.py -k scp_517_incident_appendix
```

Expected: both tests fail with `KeyError: 'scp-517'`.

- [ ] **Step 3: Add the Featured declaration**

Under `explicit_linked_appendices` in `config/featured-scp.yaml`, add:

```yaml
  scp-517:
    - title: 事件517-1997-M
      url: https://scp-wiki-cn.wikidot.com/incident-517-1997-m
```

- [ ] **Step 4: Add the Series 1 declaration**

Add this block after `include_scp001_proposals: true` and before `volumes:` in `config/series-1.yaml`:

```yaml
explicit_linked_appendices:
  scp-517:
    - title: 事件517-1997-M
      url: https://scp-wiki-cn.wikidot.com/incident-517-1997-m
```

- [ ] **Step 5: Run configuration tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_config.py
```

Expected: all configuration tests pass.

### Task 2: Prove grouping, deduplication, and one-level behavior

**Files:**
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write a failing end-to-end pipeline test**

Add:

```python
def test_build_volume_includes_configured_scp_517_incident_once_without_recursion(
    tmp_path: Path,
):
    incident = ConfiguredLink(
        title="事件517-1997-M",
        url=f"{BASE_URL}/incident-517-1997-m",
        slug="incident-517-1997-m",
    )
    config = app_config(
        tmp_path,
        explicit_linked_appendices={"scp-517": (incident,)},
    )
    from scp_epub.manifest import write_manifest

    write_manifest(
        [PageRef("SCP-517 - 自动预言机", f"{BASE_URL}/scp-517", "scp-517", 1, "scp", order=1)],
        config.manifest_dir / "test-volume.json",
    )
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-517": simple_page(
                "SCP-517 - 自动预言机",
                '<a href="/incident-517-1997-m">事件517-1997-M</a>',
            ),
            "incident-517-1997-m": simple_page(
                "事件517-1997-M",
                '<p>事件记录正文。</p><a href="/unrelated-followup">不得递归收录</a>',
            ),
        },
    )

    build_volume(config, "001-099", fetcher=fetcher)

    report = json.loads(
        (config.output_dir / "reports" / "test-volume-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["slugs"] == [
        "scp-517",
        "scp-517--linked-appendices",
        "incident-517-1997-m",
    ]
    assert [slug for slug, _url, _force in fetcher.calls].count(
        "incident-517-1997-m"
    ) == 1
    assert "unrelated-followup" not in [slug for slug, _url, _force in fetcher.calls]

    incident_xhtml = (
        config.processed_dir / "test-volume" / "0003-incident-517-1997-m.xhtml"
    ).read_text(encoding="utf-8")
    assert "事件记录正文" in incident_xhtml
```

This test intentionally places the configured URL in the main page too. If the conservative scanner recognizes it now or in the future, configured/scanned merging must still fetch and include one copy.

- [ ] **Step 2: Run the test and interpret the result**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_pipeline.py::test_build_volume_includes_configured_scp_517_incident_once_without_recursion
```

Expected with the test's explicit configuration: PASS, because the production pipeline already implements the approved behavior. This is a configuration-only exception to the usual RED implementation cycle; Task 1's concrete-config tests provide the failing test that drives the actual product change.

- [ ] **Step 3: Add a direct merge regression only if Step 2 reveals duplicate behavior**

If the test fails because the incident is duplicated, add a focused test that supplies one configured and one scanned `LinkedAppendixDocument` with the same `incident-517-1997-m` slug and asserts `_merge_linked_appendix_documents` returns one candidate, then fix only that deduplication defect. If Step 2 passes, do not add production code or an unnecessary lower-level test.

- [ ] **Step 4: Run linked-appendix regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_linked_appendices.py tests/test_pipeline.py -k "linked_appendix or linked_appendices or scp_517"
```

Expected: all selected tests pass.

### Task 3: Verify both real builds

**Files:**
- Verification only.

- [ ] **Step 1: Run focused and full tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_config.py tests/test_pipeline.py tests/test_linked_appendices.py
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Build Featured**

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
```

Expected: writes `output/epub/SCP基金会档案精选.epub` and its report.

- [ ] **Step 3: Build Series 1 volume 500-599**

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/series-1.yaml build --volume 500-599
```

Expected: writes `output/epub/SCP基金会档案-故事系列-第1卷-第6册.epub` and its report.

- [ ] **Step 4: Verify both reports and EPUBs**

Run a Python script that, for each output slug below, asserts the report order and exactly one incident XHTML page:

```python
outputs = (
    "SCP基金会档案精选",
    "SCP基金会档案-故事系列-第1卷-第6册",
)
```

For each report:

```python
slugs = report["slugs"]
main = slugs.index("scp-517")
assert slugs[main : main + 3] == [
    "scp-517",
    "scp-517--linked-appendices",
    "incident-517-1997-m",
]
assert slugs.count("incident-517-1997-m") == 1
assert "incident-517-1997-m" not in {
    item["slug"] for item in report.get("missing_pages", [])
}
```

Open each EPUB with `zipfile`, assert `testzip() is None`, find exactly one XHTML path containing `incident-517-1997-m`, and assert its text contains `事件517-1997-M` and `涉及SCP`.

### Task 4: Commit and final review

**Files:**
- Review all four modified files.

- [ ] **Step 1: Stage only SCP-517 hunks**

Stage `config/series-1.yaml` normally if it was clean before this task. Use `git add -p` for `config/featured-scp.yaml`, `tests/test_config.py`, and `tests/test_pipeline.py`. Reject the pre-existing SCP-455, worker-cap, fetcher, and appendix-ordering hunks.

- [ ] **Step 2: Inspect and commit**

```powershell
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "feat: attach incident 517 to SCP-517"
```

Expected: the commit contains only both SCP-517 configuration declarations and their tests.

- [ ] **Step 3: Confirm preserved dirty work**

```powershell
git status --short
```

Expected: the user's unrelated pre-existing modifications remain present and unstaged; generated cache/output files remain ignored.
