# SCP-7646 Scene Break Size Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the four SCP-7646 Unreality Department scene-break emblems to the original page's 40×40-pixel visual size in every EPUB variant.

**Architecture:** Add a slug-gated normalization function to the shared HTML transformer. It writes EPUB-safe inline dimensions to the semantic `.asterisk` containers and their direct SVG images, so Series 8 and Featured builds share one implementation while other pages remain unchanged.

**Tech Stack:** Python 3.11+, BeautifulSoup, pytest, existing EPUB and Kindle Scribe pipeline.

**Status:** Completed on 2026-08-24; all implementation and verification steps below were executed successfully.

---

### Task 1: Reproduce the missing imported-theme sizing

**Files:**
- Modify: `tests/test_transform.py`

- [ ] **Step 1: Add a failing SCP-7646 transformation test**

Use inline HTML containing four `.asterisk` containers with `Unreality Header Logo.svg` images and one unrelated article image. Transform it with `page_ref("scp-7646")` and assert that every target container has `width: 50px`, `height: 50px`, `max-width: 80px`, `max-height: 80px`, and `margin: 10px auto`; assert each target image has `width: 40px`, `height: 40px`, and `max-width: 100%`.

- [ ] **Step 2: Assert slug isolation**

Transform the same HTML as `scp-7645` and assert that no target receives the `layout-profile-scp-7646-scene-break` class or inline sizing.

- [ ] **Step 3: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_transform.py -k scp7646`

Expected: failure because no SCP-7646 normalization exists.

### Task 2: Implement the page-specific normalization

**Files:**
- Modify: `src/scp_epub/transform.py`

- [ ] **Step 1: Add `_normalize_scp_7646_scene_breaks`**

Select `.asterisk` containers, require a direct `img`, add `layout-profile-scp-7646-scene-break`, and append the exact container and image size declarations derived from the original theme.

- [ ] **Step 2: Gate the call by slug**

Call the helper from `transform_page` only when `entry.slug == "scp-7646"`, before asset normalization and attribute sanitization.

- [ ] **Step 3: Verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_transform.py -k scp7646`

Expected: both target behavior and isolation assertions pass.

### Task 3: Verify regressions and rebuild synchronized outputs

**Files:**
- Generated (ignored): `output/epub/SCP基金会档案-故事系列-第8卷-第7册.epub`
- Generated (ignored): `output/epub/SCP基金会档案精选.epub`
- Generated (ignored): `output/epub/SCP基金会档案精选-Kindle-Scribe.epub`
- Generated (ignored): `output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3`

- [ ] **Step 1: Run the full test suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: zero failures.

- [ ] **Step 2: Build Series 8 volume 7600-7699**

Run: `.venv\Scripts\python.exe -m scp_epub --config config/series-8.yaml build --volume 7600-7699`

Expected: exit code 0 and refreshed Series 8 volume/report.

- [ ] **Step 3: Build ordinary Featured EPUB**

Run: `.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured`

Expected: exit code 0 and refreshed Featured EPUB/report.

- [ ] **Step 4: Build Kindle Scribe stable outputs**

Run: `.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable`

Expected: exit code 0 and refreshed Scribe EPUB, AZW3, and report.

- [ ] **Step 5: Inspect packaged chapters**

For each EPUB, require ZIP integrity, exactly one `-scp-7646.xhtml`, exactly four `layout-profile-scp-7646-scene-break` containers, and exact 50/40-pixel inline dimensions. Verify the AZW3 with `ebook-meta`.

- [ ] **Step 6: Commit only task-owned files**

Stage the design, plan, transformer, and transformer test. Leave existing `config/featured-scp.yaml`, fetcher, pipeline, and their tests untouched.
