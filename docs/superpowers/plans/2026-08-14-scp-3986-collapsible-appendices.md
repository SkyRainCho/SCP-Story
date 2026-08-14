# SCP-3986 Collapsible Appendices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract seven configured SCP-3986 collapsible blocks into ordered “原文附属文档” child pages while leaving link-free titles in the owner page and preserving each child’s footnotes.

**Architecture:** Add a reusable, explicit `collapsible_appendices` page override and a focused HTML extraction module. After ordinary and external linked pages have been fetched, expand the in-memory manifest/fetch-result pairs with processed-directory synthetic sources; this reuses the existing EPUB navigation roles without network fetches and leaves page cleaning, asset localization, Kindle preparation, and EPUB writing unchanged.

**Tech Stack:** Python 3.11+, dataclasses, BeautifulSoup, PyYAML-backed configuration, pytest, existing SCP EPUB pipeline and EPUB ZIP inspection.

---

## File map

- Create `src/scp_epub/collapsible_appendices.py`: exact collapsible matching, owner replacement, content extraction, and per-child footnote transfer.
- Modify `src/scp_epub/models.py`: define `CollapsibleAppendixSpec` and attach an ordered tuple to `PageOverride`.
- Modify `src/scp_epub/config.py`: parse and validate `collapsible_appendices` entries.
- Modify `src/scp_epub/pipeline.py`: write derived source HTML under `data/processed/`, merge one linked-appendix group into the in-memory manifest, and avoid child network fetches.
- Modify `config/featured-scp.yaml`: configure the seven SCP-3986 entries for Featured builds.
- Modify `config/series-4.yaml`: configure the same entries for Series 4 `3900-3999`.
- Create `tests/test_collapsible_appendices.py`: unit coverage for matching, extraction, title replacement, footnotes, exclusions, and failures.
- Modify `tests/test_config.py`: parser validation and both production-config assertions.
- Modify `tests/test_pipeline.py`: manifest/result expansion, group merging, no-fetch integration, ordering, and serial/process-pool equivalence.
- Modify `tests/test_epub.py`: final navigation hierarchy and link-free owner XHTML assertion.
- Modify `tests/test_kindle.py` and `tests/test_kindle_stable.py`: synthetic linked child pages survive both Kindle preparation paths.

### Task 1: Add the configuration model and strict parser

**Files:**
- Modify: `src/scp_epub/models.py`
- Modify: `src/scp_epub/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing parser tests**

Add imports/assertions using the existing `write_config_with_page_overrides` helper:

```python
def test_load_config_parses_collapsible_appendices_in_order(tmp_path: Path):
    config_path = tmp_path / "series.yaml"
    write_config_with_page_overrides(
        config_path,
        """  scp-3986:
    collapsible_appendices:
      - title: 《金册》
        slug: scp-3986-golden-register
        match_text: 《金册》
      - title: 《上都演义》
        slug: scp-3986-shangdu-romance
        match_text: 《上都演义》
""",
    )

    specs = load_config(config_path).page_overrides["scp-3986"].collapsible_appendices

    assert [(spec.title, spec.slug, spec.match_text) for spec in specs] == [
        ("《金册》", "scp-3986-golden-register", "《金册》"),
        ("《上都演义》", "scp-3986-shangdu-romance", "《上都演义》"),
    ]
```

Add a parametrized test that rejects: a non-list value, an unknown field, an empty title, an empty slug, an empty `match_text`, a duplicate normalized slug, and a duplicate normalized `match_text`. Assert the message contains the precise `page_overrides.scp-3986.collapsible_appendices` field path.

- [ ] **Step 2: Run the parser tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py -k collapsible_appendices -q
```

Expected: FAIL because `PageOverride` has no `collapsible_appendices` attribute and the parser rejects the unknown key.

- [ ] **Step 3: Add the data model**

In `src/scp_epub/models.py`, add:

```python
@dataclass(frozen=True)
class CollapsibleAppendixSpec:
    title: str
    slug: str
    match_text: str
```

Extend `PageOverride` with:

```python
collapsible_appendices: tuple[CollapsibleAppendixSpec, ...] = ()
```

- [ ] **Step 4: Implement strict configuration loading**

Import `CollapsibleAppendixSpec`, allow the `collapsible_appendices` override key, and assign the result of `_load_collapsible_appendices`. Implement the loader with these exact rules:

```python
def _load_collapsible_appendices(
    value: Any,
    name: str,
) -> tuple[CollapsibleAppendixSpec, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list of collapsible appendix mappings")

    specs: list[CollapsibleAppendixSpec] = []
    seen_slugs: set[str] = set()
    seen_matches: set[str] = set()
    for index, raw_spec in enumerate(value):
        spec_name = f"{name}[{index}]"
        spec = _mapping(raw_spec, spec_name)
        _reject_unknown_keys(spec, {"title", "slug", "match_text"}, spec_name)
        title = _required_string(spec.get("title"), f"{spec_name}.title").strip()
        slug = _required_string(spec.get("slug"), f"{spec_name}.slug").strip().lower()
        match_text = _required_string(
            spec.get("match_text"), f"{spec_name}.match_text"
        ).strip()
        if not title:
            raise ValueError(f"{spec_name}.title must not be empty")
        if not slug:
            raise ValueError(f"{spec_name}.slug must not be empty")
        if not match_text:
            raise ValueError(f"{spec_name}.match_text must not be empty")
        normalized_match = " ".join(match_text.split())
        if slug in seen_slugs:
            raise ValueError(f"{name} contains duplicate slug: {slug}")
        if normalized_match in seen_matches:
            raise ValueError(f"{name} contains duplicate match_text: {match_text}")
        seen_slugs.add(slug)
        seen_matches.add(normalized_match)
        specs.append(
            CollapsibleAppendixSpec(
                title=title,
                slug=slug,
                match_text=match_text,
            )
        )
    return tuple(specs)
```

- [ ] **Step 5: Run focused and complete config tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py -q
```

Expected: all `tests/test_config.py` tests PASS.

- [ ] **Step 6: Commit Task 1**

```powershell
git add src/scp_epub/models.py src/scp_epub/config.py tests/test_config.py
git commit -m "feat: configure collapsible appendices"
```

### Task 2: Extract configured blocks and transfer their footnotes

**Files:**
- Create: `src/scp_epub/collapsible_appendices.py`
- Create: `tests/test_collapsible_appendices.py`

- [ ] **Step 1: Write the successful extraction test**

Create a minimal fixture directly in the test. It must contain “管理专用”, two selected book blocks, “文件”, footnote references `footnoteref-1` and `footnoteref-2`, and matching footer items `footnote-1` and `footnote-2`.

```python
def test_extracts_selected_blocks_and_leaves_plain_titles_with_owned_footnotes():
    specs = (
        CollapsibleAppendixSpec("《金册》", "scp-3986-golden-register", "《金册》"),
        CollapsibleAppendixSpec("《上都演义》", "scp-3986-shangdu-romance", "《上都演义》"),
    )

    result = extract_collapsible_appendices(SCP_3986_SAMPLE, specs)

    owner = BeautifulSoup(result.owner_html, "html.parser")
    titles = owner.select(".collapsible-appendix-title")
    assert [title.get_text(strip=True) for title in titles] == ["《金册》", "《上都演义》"]
    assert all(title.name == "p" and title.find("a") is None for title in titles)
    assert "金册正文" not in owner.get_text(" ", strip=True)
    assert owner.find(string=lambda value: value and "管理专用" in value) is not None
    assert owner.find(string=lambda value: value and "+文件" in value) is not None
    assert owner.find(id="footnote-1") is None
    assert owner.find(id="footnote-2") is None

    assert [item.spec.slug for item in result.appendices] == [
        "scp-3986-golden-register",
        "scp-3986-shangdu-romance",
    ]
    golden = BeautifulSoup(result.appendices[0].html, "html.parser")
    shangdu = BeautifulSoup(result.appendices[1].html, "html.parser")
    assert golden.find(id="footnote-1") is not None
    assert golden.find(id="footnote-2") is None
    assert shangdu.find(id="footnote-2") is not None
    assert shangdu.find(id="footnote-1") is None
```

Add a second success test showing an appendix with no footnote does not receive an empty `.footnotes-footer`.

- [ ] **Step 2: Write failure tests**

Add parametrized cases and assert `CollapsibleAppendixExtractionError` messages identify the spec title/slug:

- configured title is absent;
- two folded labels normalize to the same configured `match_text`;
- matched block lacks `.collapsible-block-content`;
- a referenced `footnoteref-N` has no `footnote-N`;
- two footer elements use the same `footnote-N` id.

- [ ] **Step 3: Run the new test module and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_collapsible_appendices.py -q
```

Expected: collection FAIL because `scp_epub.collapsible_appendices` does not exist.

- [ ] **Step 4: Implement the focused extraction module**

Create these public structures:

```python
@dataclass(frozen=True)
class ExtractedCollapsibleAppendix:
    spec: CollapsibleAppendixSpec
    html: str


@dataclass(frozen=True)
class CollapsibleAppendixExtraction:
    owner_html: str
    appendices: tuple[ExtractedCollapsibleAppendix, ...]


class CollapsibleAppendixExtractionError(ValueError):
    pass
```

Implement `extract_collapsible_appendices(html, specs)` with this data flow:

```python
def extract_collapsible_appendices(
    html: str,
    specs: tuple[CollapsibleAppendixSpec, ...],
) -> CollapsibleAppendixExtraction:
    soup = BeautifulSoup(html, "html.parser")
    page_content = soup.select_one("#page-content")
    if page_content is None:
        raise CollapsibleAppendixExtractionError("page is missing #page-content")

    matched = _match_blocks(page_content, specs)
    extracted: list[ExtractedCollapsibleAppendix] = []
    for spec, block in matched:
        content = block.select_one(".collapsible-block-content")
        if content is None:
            raise CollapsibleAppendixExtractionError(
                f"{spec.slug} ({spec.title}) is missing .collapsible-block-content"
            )
        footnotes = _take_referenced_footnotes(soup, content, spec)
        fragment_html = _fragment_html(soup, content, footnotes)
        replacement = soup.new_tag("p", attrs={"class": "collapsible-appendix-title"})
        replacement.string = spec.title
        block.replace_with(replacement)
        extracted.append(ExtractedCollapsibleAppendix(spec=spec, html=fragment_html))

    _remove_empty_footnotes_container(soup)
    return CollapsibleAppendixExtraction(
        owner_html=str(soup),
        appendices=tuple(extracted),
    )
```

Helper requirements:

- `_match_blocks` only inspects a direct `.collapsible-block-folded` label for each block; normalize whitespace and remove one leading `+` or `-` before exact comparison.
- `_take_referenced_footnotes` only uses anchors whose id matches `footnoteref-(\d+)`, preserves first-reference order, requires exactly one matching `#footnote-N`, serializes it into the fragment, and decomposes it from the owner.
- `_fragment_html` copies all source `<style>` elements, wraps the extracted child nodes in `<div id="page-content">`, and adds a `.footnotes-footer` block only when footnotes exist.
- `_remove_empty_footnotes_container` removes the outer footer and its adjacent “脚注” title only when no direct footer item with an id matching `footnote-\d+` remains.

- [ ] **Step 5: Run extraction tests GREEN and transform regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_collapsible_appendices.py tests/test_transform.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add src/scp_epub/collapsible_appendices.py tests/test_collapsible_appendices.py
git commit -m "feat: extract collapsible appendix content"
```

### Task 3: Expand fetched pages with synthetic linked-appendix sources

**Files:**
- Modify: `src/scp_epub/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the manifest/result expansion test**

Import `CollapsibleAppendixSpec`, `include_collapsible_appendices`, and existing linked-appendix role constants. Build a one-page manifest and a `FetchResult` pointing to the sample source, then assert:

```python
expanded_manifest, expanded_results = include_collapsible_appendices(
    config,
    volume,
    [owner],
    [owner_result],
)

assert [(entry.slug, entry.role, entry.parent_slug) for entry in expanded_manifest] == [
    ("scp-3986", "scp", None),
    ("scp-3986--linked-appendices", LINKED_APPENDIX_GROUP_ROLE, "scp-3986"),
    (
        "scp-3986-golden-register",
        LINKED_APPENDIX_ROLE,
        "scp-3986--linked-appendices",
    ),
    (
        "scp-3986-shangdu-romance",
        LINKED_APPENDIX_ROLE,
        "scp-3986--linked-appendices",
    ),
]
assert len(expanded_results) == len(expanded_manifest)
assert "金册正文" not in expanded_results[0].path.read_text(encoding="utf-8")
assert "金册正文" in expanded_results[2].path.read_text(encoding="utf-8")
assert all("collapsible-sources" in result.path.parts for result in expanded_results)
```

- [ ] **Step 2: Write merging, collision, and no-network integration tests**

Add tests proving:

1. If an existing external linked-appendix group and child are already present, the function reuses that group and orders extracted children before the external child.
2. The regenerated group page contains links to all extracted and external children.
3. A configured synthetic slug colliding with any manifest slug raises `ValueError` with owner and child slugs.
4. A `build_volume` using `FakeFetcher` only records a network page call for `scp-3986`; it does not record calls for the group or seven synthetic child slugs.
5. With `SCP_EPUB_WORKERS=1` and `SCP_EPUB_WORKERS=2`, processed page slug order and XHTML are identical for the owner, group, and children.

- [ ] **Step 3: Run focused pipeline tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -k "collapsible_append" -q
```

Expected: FAIL because `include_collapsible_appendices` is not defined.

- [ ] **Step 4: Implement derived source writing and ordered expansion**

In `src/scp_epub/pipeline.py`:

1. Import `extract_collapsible_appendices` and `CollapsibleAppendixSpec`.
2. Add `include_collapsible_appendices(config, volume, manifest, fetch_results)`.
3. Build `result_by_slug` from the strict manifest/result zip.
4. For each manifest owner with configured specs, extract from its fetched HTML and write the modified owner and child source HTML to:

```text
<processed_dir>/<output_slug>/collapsible-sources/<slug>.html
```

5. Write a matching JSON metadata file beside each derived HTML containing the synthetic URL, status 200, content type `text/html`, and SHA-256 of the HTML.
6. Return a `FetchResult` pointing to each derived HTML; never call `PageFetcher` for synthetic entries.
7. Create entries with:

```python
PageRef(
    title=spec.title,
    url=f"{owner.url}#{spec.slug}",
    slug=spec.slug,
    level=owner.level + 2,
    role=LINKED_APPENDIX_ROLE,
    parent_slug=linked_appendix_group_slug(owner.slug),
    source="configured-collapsible-appendix",
)
```

8. Reuse an existing group whose slug is `linked_appendix_group_slug(owner.slug)`; otherwise synthesize one at `owner.level + 1` with `LINKED_APPENDIX_GROUP_TITLE` and `LINKED_APPENDIX_GROUP_ROLE`.
9. Insert extracted children directly after the group and before any existing children.
10. Regenerate the group source page from all immediate child entries so its body list and EPUB navigation agree.
11. Preserve every unrelated manifest/result pair in original order.

- [ ] **Step 5: Wire expansion into the build before page processing**

In `build_volume`, after external linked appendices and their report are handled, add:

```python
available_manifest, fetch_results = include_collapsible_appendices(
    config,
    volume,
    available_manifest,
    fetch_results,
)
```

Keep `fetch_inline_document_results` and `_process_pages` after this call. This makes the existing process-pool cleaner consume a fully ordered manifest/result list without changing its concurrency contract.

- [ ] **Step 6: Run pipeline tests GREEN and the full pipeline suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -q
```

Expected: all `tests/test_pipeline.py` tests PASS.

- [ ] **Step 7: Commit Task 3**

Because `tests/test_pipeline.py` has user-owned pre-existing changes, stage only the new collapsible-appendix hunks with `git apply --cached` or interactive patching; do not stage the whole file.

```powershell
git add src/scp_epub/pipeline.py
git diff --cached --check
git commit -m "feat: build collapsible appendix pages"
```

### Task 4: Add Featured and Series 4 production configuration

**Files:**
- Modify: `config/featured-scp.yaml`
- Modify: `config/series-4.yaml`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing production-config assertions**

Add a shared expected list and assert both configs parse it exactly:

```python
EXPECTED_SCP3986_COLLAPSIBLE_APPENDICES = [
    ("《金册》", "scp-3986-golden-register", "《金册》"),
    ("《蒙古诸部志略》", "scp-3986-mongol-tribes", "《蒙古诸部志略》"),
    ("《阿夫沙尔诗集》", "scp-3986-afshar-poems", "《阿夫沙尔诗集》"),
    ("《罗乞湿密·罗乌如是说》", "scp-3986-lakshmidhara", "《罗乞湿密·罗乌如是说》"),
    ("《上都演义》", "scp-3986-shangdu-romance", "《上都演义》"),
    (
        "《Nikolai Karensky致Katerina Karenskaya的信》",
        "scp-3986-karensky-letter",
        "《Nikolai Karensky致Katerina Karenskaya的信》",
    ),
    (
        "《俄罗斯及突厥斯坦记行》",
        "scp-3986-russia-turkestan-travels",
        "《俄罗斯及突厥斯坦记行》",
    ),
]
```

Run the two assertions and confirm they fail because the production configs do not yet contain `scp-3986.collapsible_appendices`.

- [ ] **Step 2: Add the exact seven entries to both YAML files**

Under `page_overrides.scp-3986`, add the seven `title`, `slug`, and `match_text` mappings in the expected order. In `config/featured-scp.yaml`, preserve the already-present user-owned `scp-455` and other unrelated changes; stage only the SCP-3986 hunk.

- [ ] **Step 3: Run config and focused build tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_pipeline.py -k "scp3986 or collapsible_append" -q
```

Expected: all selected tests PASS.

- [ ] **Step 4: Commit Task 4**

Stage `config/series-4.yaml` and the new `tests/test_config.py` changes normally. Stage only the SCP-3986 hunk from dirty `config/featured-scp.yaml`.

```powershell
git diff --cached --check
git commit -m "feat: configure SCP-3986 appendices"
```

### Task 5: Lock EPUB navigation and Kindle preservation

**Files:**
- Modify: `tests/test_epub.py`
- Modify: `tests/test_kindle.py`
- Modify: `tests/test_kindle_stable.py`

- [ ] **Step 1: Add an EPUB hierarchy regression test**

Build a minimal `ProcessedPage` list containing the owner, group, seven configured linked children, and a following unrelated page. Write an EPUB and assert `nav.xhtml` has one nested group whose seven links use the configured order. Parse the owner XHTML and assert every `.collapsible-appendix-title` is a `<p>` without an `<a>` descendant.

- [ ] **Step 2: Add Kindle pass-through tests**

For `prepare_kindle_pages`, pass an owner, group, and child page and assert the three entry slugs, roles, `parent_slug` values, and child XHTML are unchanged. For `prepare_stable_kindle_assets`, use pages with no assets and assert the same navigation metadata and XHTML survive stable preparation.

- [ ] **Step 3: Verify RED if any existing Kindle/EPUB stage drops metadata**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_epub.py -k scp3986 -q
.\.venv\Scripts\python.exe -m pytest tests/test_kindle.py tests/test_kindle_stable.py -k collapsible_append -q
```

Expected: the EPUB test initially FAILS until its test fixture uses the new expansion API; Kindle tests may PASS as characterization. If Kindle tests PASS immediately, keep them as regression coverage and do not add production code.

- [ ] **Step 4: Make only required production adjustments**

If the focused tests reveal lost `parent_slug`, role, or XHTML, fix the exact pass-through location with the smallest change and rerun the failing test. Do not change Kindle CSS or image planning when characterization already passes.

- [ ] **Step 5: Run all output-mode suites**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_epub.py tests/test_kindle.py tests/test_kindle_stable.py tests/test_cli.py -q
```

Expected: all selected suites PASS.

- [ ] **Step 6: Commit Task 5**

```powershell
git add tests/test_epub.py tests/test_kindle.py tests/test_kindle_stable.py
git commit -m "test: preserve collapsible appendix navigation"
```

### Task 6: Full verification and synchronized production builds

**Files:**
- Verify only: repository tests and ignored generated outputs

- [ ] **Step 1: Run the complete test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Rebuild Featured ordinary EPUB**

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
```

Expected output: `output/epub/SCP基金会档案精选.epub` and its report.

- [ ] **Step 3: Rebuild Featured Kindle Scribe EPUB/AZW3**

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

Expected outputs: `output/epub/SCP基金会档案精选-Kindle-Scribe.epub`, `output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3`, and the Scribe report.

- [ ] **Step 4: Rebuild Series 4 `3900-3999`**

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/series-4.yaml build --volume 3900-3999
```

Expected output: `output/epub/SCP基金会档案-故事系列-第4卷-第10册.epub` and its report.

- [ ] **Step 5: Verify EPUB integrity and content structure**

Run `python -m zipfile -t` on all three EPUB files. For each EPUB, inspect `nav.xhtml` and the SCP-3986-related XHTML files and assert:

- exactly one `原文附属文档` group under SCP-3986;
- exactly seven configured child links in order;
- owner contains seven `.collapsible-appendix-title` elements with no anchors;
- owner does not contain the seven extracted content bodies;
- “管理专用” and “文件” remain;
- child documents contain their expected bodies;
- footnotes 1–10 appear only in their owning child pages;
- 《上都演义》 has no empty footnote section.

- [ ] **Step 6: Inspect build reports**

Confirm the three reports contain the owner/group/seven child page slugs in order, no SCP-3986-derived page is missing, and no child URL appears in fetcher/network failure records. Record unrelated `missing_assets` separately rather than attributing them to this change.

- [ ] **Step 7: Run fresh completion verification**

Run the complete test suite again after production builds, then run:

```powershell
git diff --check
git diff --cached --name-only
git status --short
```

Expected: tests pass; no staged changes remain; only the five pre-task user-owned modified files remain outside the commits unless the user changed the workspace during execution.
