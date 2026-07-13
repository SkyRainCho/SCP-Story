# Include SCP-001 Proposals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Include SCP-001 proposal pages missing from the Tales index while preserving the SCP-001 hub list order and navigation hierarchy.

**Architecture:** `parse_scp001_proposals` already extracts proposal links from the SCP-001 hub with `level=2` and `parent_slug="scp-001"`. `merge_manifest` will be changed so SCP-001 child proposal ordering is driven by the SCP-001 hub list: indexed proposal entries keep their metadata, missing proposal entries are inserted, and duplicate indexed proposal entries are removed from their old positions. Series 1 enables this path through `include_scp001_proposals: true`.

**Tech Stack:** Python 3.12, BeautifulSoup, pytest, existing `PageRef` manifest model.

---

### Task 1: Manifest Merge Ordering

**Files:**
- Modify: `tests/test_manifest.py`
- Modify: `src/scp_epub/manifest.py`

- [ ] **Step 1: Write the failing test**

Add a test showing that the SCP-001 hub proposal list controls order, while indexed proposal metadata wins.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_manifest.py::test_merge_reorders_scp001_children_to_match_hub_proposal_order -q`

Expected: FAIL because the current merge keeps indexed SCP-001 proposal entries in Tales index order.

- [ ] **Step 3: Write minimal implementation**

Change `merge_manifest` to build a proposal replacement block after `scp-001`. Use indexed entries for proposal slugs that already exist in the index, use hub entries for missing slugs, skip those proposal slugs at their old positions, and dedupe/renumber at the end.

- [ ] **Step 4: Run manifest tests**

Run: `python -m pytest tests/test_manifest.py -q`

Expected: all manifest tests pass.

### Task 2: Pipeline Config Coverage

**Files:**
- Modify: `config/series-1.yaml`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

Add or update a pipeline test that builds an `001-099` manifest with SCP-001 proposals enabled and asserts the manifest order follows the SCP-001 hub order even when the Tales index lists those proposal links differently.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py -q`

Expected: FAIL before the merge implementation or config assertion is complete.

- [ ] **Step 3: Enable Series 1 proposal inclusion**

Set `include_scp001_proposals: true` in `config/series-1.yaml`.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_manifest.py tests/test_pipeline.py tests/test_scp001.py -q`

Expected: all focused tests pass.

### Task 3: Final Verification

**Files:**
- No additional source files.

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Inspect git diff**

Run: `git diff -- config/series-1.yaml src/scp_epub/manifest.py tests/test_manifest.py tests/test_pipeline.py`

Expected: diff only includes the planned behavior and tests.
