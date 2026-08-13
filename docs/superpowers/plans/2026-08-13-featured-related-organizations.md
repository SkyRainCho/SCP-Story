# Featured Related Organizations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically include every current organization hub linked from Featured’s `groups-of-interest` page as level-3 children under `相关组织`, using Chinese short titles and cached/force-refresh behavior.

**Architecture:** Add a dedicated `organization-links` appendix mode. The parser will inspect only direct organization cards and their heading links; the Featured pipeline will fetch the index once, append real organization pages beneath the existing section, and leave all other appendix modes unchanged.

**Tech Stack:** Python 3.11+, BeautifulSoup, dataclasses, YAML, pytest, existing EPUB/Kindle Scribe pipeline.

---

## File map and dirty-worktree boundary

- Modify `src/scp_epub/appendix.py`: add `APPENDIX_ORGANIZATION_ROLE` and `extract_organization_children`.
- Modify `src/scp_epub/config.py`: accept `organization-links` and update validation text.
- Modify `src/scp_epub/pipeline.py`: import the parser and add organization children during Featured manifest construction.
- Modify `config/featured-scp.yaml`: set the `相关组织` section mode.
- Modify `tests/test_appendix.py`: parser filtering, ordering, deduplication, and no-card cases.
- Modify `tests/test_config.py`: concrete Featured mode assertion and invalid-mode message update.
- Modify `tests/test_pipeline.py`: Featured manifest hierarchy, one-level behavior, and fetch failure handling.

The worktree already contains unrelated uncommitted changes in `config/featured-scp.yaml`, `src/scp_epub/fetcher.py`, `src/scp_epub/pipeline.py`, `tests/test_config.py`, `tests/test_fetcher.py`, and `tests/test_pipeline.py`. Preserve them. Use patch-specific staging for mixed files and inspect `git diff --cached` before committing.

### Task 1: Add parser tests and implement organization-card extraction

**Files:**
- Modify: `tests/test_appendix.py`
- Modify: `src/scp_epub/appendix.py`

- [ ] **Step 1: Write the failing parser test**

Add a test with two `div.content-panel.standalone.series` cards plus noise:

```python
def test_extract_organization_children_selects_heading_hubs_only_and_deduplicates():
    parent = page_ref("groups-of-interest", title="相关组织")
    html = """
    <div id="page-content">
      <div class="content-panel standalone series">
        <h1><a href="/alexylva-university-hub?source=index#top">Alexylva大学</a>（Alexylva University）</h1>
        <p><a href="/wayward">田纳西州</a><a href="/scp-123">SCP-123</a></p>
      </div>
      <div class="content-panel standalone series">
        <h1><a href="https://SCP-WIKI-CN.WIKIDOT.COM/ambrose-restaurant-hub">安布罗斯餐厅</a>（Ambrose Restaurants）</h1>
        <p><a href="/ambrose-london-prix-fixe">普通正文链接</a></p>
      </div>
      <div class="content-panel standalone series"><h1>没有链接</h1></div>
      <a href="https://example.test/not-an-organization">站外噪声</a>
    </div>
    """

    children = extract_organization_children(parent, html, BASE_URL)

    assert [(entry.title, entry.slug, entry.url) for entry in children] == [
        ("Alexylva大学", "alexylva-university-hub", f"{BASE_URL}/alexylva-university-hub"),
        ("安布罗斯餐厅", "ambrose-restaurant-hub", f"{BASE_URL}/ambrose-restaurant-hub"),
    ]
    assert [(entry.level, entry.parent_slug, entry.role) for entry in children] == [
        (3, parent.slug, "appendix-organization"),
        (3, parent.slug, "appendix-organization"),
    ]
```

Also add a no-card test asserting `extract_organization_children(parent, '<div id="page-content"><p>正文</p></div>', BASE_URL) == []`.

- [ ] **Step 2: Run parser tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_appendix.py -k organization
```

Expected: collection fails because `extract_organization_children` is not defined.

- [ ] **Step 3: Implement the minimal parser**

In `src/scp_epub/appendix.py`, add:

```python
APPENDIX_ORGANIZATION_ROLE = "appendix-organization"


def extract_organization_children(parent: PageRef, html: str, base_url: str) -> list[PageRef]:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#page-content") or soup
    children: list[PageRef] = []
    seen_slugs: set[str] = set()
    for card in content.select("div.content-panel.standalone.series"):
        heading = card.find("h1", recursive=False)
        anchor = heading.find("a", href=True, recursive=False) if heading else None
        if anchor is None:
            continue
        title = " ".join(anchor.get_text(" ", strip=True).split())
        url = _same_site_page_url(anchor.get("href", ""), base_url)
        if not title or url is None:
            continue
        slug = slug_from_url(url)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        children.append(
            PageRef(
                title=title,
                url=url,
                slug=slug,
                level=parent.level + 1,
                role=APPENDIX_ORGANIZATION_ROLE,
                parent_slug=parent.slug,
                source=parent.source,
            )
        )
    return children
```

- [ ] **Step 4: Run parser tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_appendix.py -k organization
```

Expected: all organization parser tests pass; existing appendix parser tests remain green.

### Task 2: Enable the mode in configuration and Featured pipeline

**Files:**
- Modify: `src/scp_epub/config.py`
- Modify: `src/scp_epub/pipeline.py`
- Modify: `config/featured-scp.yaml`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add the failing concrete configuration assertion**

Extend `test_featured_scp_config_declares_appendix_structure`:

```python
assert sections_by_title["相关组织"].mode == "organization-links"
```

Update the invalid-mode parameter’s expected message to include `organization-links` while leaving the invalid input unchanged. Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_config.py -k "appendix_structure or invalid_appendix_section_options"
```

Expected: the new concrete assertion fails because YAML still has default `page`, and invalid-mode text still rejects the new value.

- [ ] **Step 2: Add configuration support**

Change `_optional_appendix_mode` to accept all four values and report:

```python
if mode not in {"page", "facility-links", "tabs-as-pages", "organization-links"}:
    raise ValueError(
        f"{name} must be 'page', 'facility-links', 'tabs-as-pages', or 'organization-links'"
    )
```

Add `mode: organization-links` under `相关组织` in `config/featured-scp.yaml`.

- [ ] **Step 3: Extend Featured manifest construction**

Import `extract_organization_children` and `APPENDIX_ORGANIZATION_ROLE` as needed. In `_featured_appendix_entries`, after fetching the section page and constructing `source_entry`, add:

```python
if section.mode == "organization-links":
    entries.extend(
        _with_parent_slug(
            extract_organization_children(source_entry, html, config.base_url),
            entry.slug,
        )
    )
```

Keep the existing `facility-links` and `tabs-as-pages` branches unchanged. The section itself remains `entry.slug == section.slug` and continues through normal page processing, so its overview text is preserved.

- [ ] **Step 4: Run configuration tests and appendix regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_config.py -k "appendix_structure or invalid_appendix_section_options"
.\.venv\Scripts\python.exe -m pytest -q tests/test_appendix.py
```

Expected: all selected tests pass.

### Task 3: Add Featured manifest and failure-path regressions

**Files:**
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Add a focused manifest test**

Build a minimal Featured config whose `相关组织` section uses `organization-links`, with a fake index page containing two cards and an organization page containing a link to `scp-should-not-follow`. Assert manifest slugs are:

```python
[
    "appendix",
    "groups-of-interest",
    "alexylva-university-hub",
    "ambrose-restaurant-hub",
]
```

Assert child titles are the Chinese short names, all children have level 3 and parent `groups-of-interest`, and only the index plus the two organization pages were fetched. The organization page’s nested link must not be fetched.

- [ ] **Step 2: Add a missing-organization failure test**

Use one valid and one `FakeFetcher`-failed organization slug. Run `build_volume` and assert the report keeps the overview and valid organization, adds exactly one `missing_pages` record for the failed slug, and does not remove the valid child.

- [ ] **Step 3: Run pipeline tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_pipeline.py -k "organization or featured_manifest"
```

Expected: all new and existing Featured manifest tests pass.

### Task 4: Run full regression and real builds

**Files:**
- Verification only.

- [ ] **Step 1: Run focused and complete tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_appendix.py tests/test_config.py tests/test_pipeline.py
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Build ordinary Featured EPUB**

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
```

- [ ] **Step 3: Build Kindle Scribe Featured output**

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

- [ ] **Step 4: Verify reports and archives**

Read both reports and assert `groups-of-interest` is followed by exactly 46 current organization child slugs, with first two titles/slugs `Alexylva大学`/`alexylva-university-hub` and `安布罗斯餐厅`/`ambrose-restaurant-hub`, each child occurring once and absent from `missing_pages`.

Open ordinary Featured EPUB and Scribe EPUB with `zipfile`, assert `testzip() is None`, find each organization XHTML once, and check at least the first two bodies contain their organization headings. Confirm Scribe AZW3 exists and has nonzero size.

### Task 5: Commit only this feature

**Files:**
- Review all modified feature files.

- [ ] **Step 1: Stage only organization mode hunks**

Use patch-specific staging for mixed `config/featured-scp.yaml`, `src/scp_epub/pipeline.py`, and `tests/test_pipeline.py`; do not stage the existing user edits related to SCP-455, fetcher workers, or process workers.

- [ ] **Step 2: Inspect and commit**

```powershell
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "feat: add Featured organization appendix children"
```

- [ ] **Step 3: Confirm preserved dirty work**

```powershell
git status --short
```

Expected: only the user’s pre-existing six modified files remain unstaged; generated output/cache files remain ignored.
