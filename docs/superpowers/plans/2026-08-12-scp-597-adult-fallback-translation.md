# Featured SCP-597 Adult Fallback Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Featured collection's Chinese SCP-597 adult gate with a reproducible full Chinese translation of the public English article while automatically preferring a future complete official Chinese page.

**Architecture:** Extend the existing typed `PageFallback` with one optional primary-page rejection mode. A focused DOM predicate recognizes only a configured same-slug adult gate; the manifest-resolution loop loads the already validated translation snapshot when that predicate matches, and otherwise preserves the existing primary-page-first behavior. The translation remains a committed, structure-signed HTML snapshot shared by normal EPUB, Kindle, and Kindle Scribe builds.

**Tech Stack:** Python 3.11+, dataclasses, BeautifulSoup, PyYAML, pytest, existing EPUB/Kindle pipeline.

---

## File map and worktree constraints

- Modify `src/scp_epub/models.py`: add the optional `primary_page_rejection` field to `PageFallback`.
- Modify `src/scp_epub/config.py`: parse and validate the one supported rejection mode.
- Modify `src/scp_epub/page_fallbacks.py`: detect a same-slug Chinese adult gate from parsed HTML.
- Modify `src/scp_epub/pipeline.py`: reject a successful gate result and load the existing fallback snapshot.
- Create `translations/featured/scp-597.zh-CN.html`: complete Chinese translation snapshot sourced from the public English page.
- Modify `config/featured-scp.yaml`: declare the SCP-597 translation and gate rejection mode.
- Modify `tests/test_page_fallbacks.py`: isolated strict gate-detection tests.
- Modify `tests/test_config.py`: typed configuration and Featured declaration tests.
- Modify `tests/test_pipeline.py`: successful-primary gate fallback, future official translation priority, and invalid-snapshot behavior.
- Modify `tests/test_transform.py`: real snapshot structure, content, language, and transform regression checks.

The worktree already contains unrelated user changes in `config/featured-scp.yaml`, `src/scp_epub/pipeline.py`, `tests/test_config.py`, and `tests/test_pipeline.py`. Preserve them. Before every commit, inspect `git diff --cached`; never stage an entire pre-modified file. New files may be staged normally. For mixed files, create `$env:TEMP\scp597-index.patch` containing only this feature's zero-context hunks and apply it with `git apply --cached --unidiff-zero $env:TEMP\scp597-index.patch`, then verify the cached diff. If clean hunk-only staging cannot be proven, leave those changes uncommitted and report that fact rather than capturing unrelated work.

### Task 1: Add the typed rejection mode

**Files:**
- Modify: `src/scp_epub/models.py:54-60`
- Modify: `src/scp_epub/config.py:319-370`
- Test: `tests/test_config.py:80-220`

- [ ] **Step 1: Extend the parsing test first**

In `test_load_config_parses_page_fallbacks`, add the YAML property:

```yaml
    primary_page_rejection: adult-gate-only
```

and the assertion:

```python
assert fallback.primary_page_rejection == "adult-gate-only"
```

Add a separate default-compatibility test:

```python
def test_load_config_defaults_page_fallback_primary_rejection_to_none(tmp_path: Path):
    snapshot = tmp_path / "translations" / "featured" / "scp-4846.zh-CN.html"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text('<div id="page-content"><p>译文</p></div>', encoding="utf-8")
    config_path = tmp_path / "series.yaml"
    write_config_with_page_fallbacks(
        config_path,
        """  scp-4846:
    source_url: https://scp-wiki.wikidot.com/scp-4846
    source_language: en
    translated_title: SCP-4846 - 友善化石
    snapshot_path: translations/featured/scp-4846.zh-CN.html
    layout_signature: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
""",
    )

    assert load_config(config_path).page_fallbacks["scp-4846"].primary_page_rejection is None
```

Add an invalid-enum case to the existing parametrized rejection test:

```yaml
  scp-4846:
    source_url: https://scp-wiki.wikidot.com/scp-4846
    source_language: en
    translated_title: SCP-4846 - 友善化石
    snapshot_path: translations/featured/scp-4846.zh-CN.html
    layout_signature: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
    primary_page_rejection: any-short-page
```

with expected message:

```text
page_fallbacks.scp-4846.primary_page_rejection must be one of: adult-gate-only
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
pytest -q tests/test_config.py::test_load_config_parses_page_fallbacks tests/test_config.py::test_load_config_defaults_page_fallback_primary_rejection_to_none tests/test_config.py::test_load_config_rejects_invalid_page_fallbacks
```

Expected: parsing fails because `primary_page_rejection` is unknown, and the dataclass has no matching attribute.

- [ ] **Step 3: Add the minimal data-model field**

Change `PageFallback` to:

```python
@dataclass(frozen=True)
class PageFallback:
    source_url: str
    source_language: str
    translated_title: str
    snapshot_path: Path
    layout_signature: str
    primary_page_rejection: str | None = None
```

- [ ] **Step 4: Parse the validated enum**

Add the constant near the configuration validation constants:

```python
_PRIMARY_PAGE_REJECTION_MODES = frozenset({"adult-gate-only"})
```

Add this helper near `_layout_signature`:

```python
def _optional_primary_page_rejection(value: Any, name: str) -> str | None:
    if value is None:
        return None
    mode = _required_string(value, name).strip()
    if mode not in _PRIMARY_PAGE_REJECTION_MODES:
        allowed = ", ".join(sorted(_PRIMARY_PAGE_REJECTION_MODES))
        raise ValueError(f"{name} must be one of: {allowed}")
    return mode
```

Add `"primary_page_rejection"` to `_load_page_fallbacks`' accepted keys and pass this final constructor argument:

```python
primary_page_rejection=_optional_primary_page_rejection(
    fallback.get("primary_page_rejection"),
    f"{fallback_name}.primary_page_rejection",
),
```

- [ ] **Step 5: Run configuration tests and verify GREEN**

Run:

```powershell
pytest -q tests/test_config.py
```

Expected: all configuration tests pass.

- [ ] **Step 6: Commit only clean model/config/test hunks if separable**

Use commit message:

```text
feat: configure primary page rejection
```

Before committing, confirm the cached diff contains no existing SCP-455 configuration or unrelated modifications.

### Task 2: Detect only a same-slug adult gate

**Files:**
- Modify: `src/scp_epub/page_fallbacks.py:1-75`
- Test: `tests/test_page_fallbacks.py`

- [ ] **Step 1: Write strict predicate tests**

Import `primary_page_should_fallback` and add a helper:

```python
def primary_page(body: str) -> str:
    return f'<html><body><div id="page-content">{body}</div></body></html>'
```

Add these tests:

```python
def test_primary_page_should_fallback_recognizes_same_slug_chinese_adult_gate():
    html = primary_page(
        '<p>本文包含成人内容，可能并不适合所有读者。'
        '如果你已年满 18 周岁并愿意阅读相关内容，'
        '<a href="/adult:scp-597/noredirect/true">点击这里继续</a>。</p>'
    )

    assert primary_page_should_fallback(html, "scp-597", "adult-gate-only") is True


@pytest.mark.parametrize(
    "body",
    [
        (
            '<p>本文包含成人内容。如果你已年满 18 周岁，'
            '<a href="/adult:scp-598/noredirect/true">点击这里继续</a>。</p>'
        ),
        '<p>本文包含成人内容。如果你已年满 18 周岁，请谨慎阅读。</p>',
        '<p><a href="/adult:scp-597/noredirect/true">点击这里继续</a>。</p>',
        (
            '<p>本文包含成人内容。如果你已年满 18 周岁，'
            '<a href="/adult:scp-597/noredirect/true">点击这里继续</a>。</p>'
            '<p><strong>项目编号：</strong>SCP-597</p>'
            '<p><strong>特殊收容措施：</strong>完整正文。</p>'
        ),
    ],
)
def test_primary_page_should_fallback_rejects_ambiguous_or_complete_pages(body: str):
    assert primary_page_should_fallback(
        primary_page(body), "scp-597", "adult-gate-only"
    ) is False


def test_primary_page_should_fallback_requires_exactly_one_page_content():
    html = (
        '<div id="page-content"><p>本文包含成人内容，已满 18 周岁'
        '<a href="/adult:scp-597/noredirect/true">继续</a></p></div>'
        '<div id="page-content"></div>'
    )

    assert primary_page_should_fallback(html, "scp-597", "adult-gate-only") is False


def test_primary_page_should_fallback_returns_false_without_configured_mode():
    html = primary_page(
        '<p>本文包含成人内容，已满 18 周岁'
        '<a href="/adult:scp-597/noredirect/true">继续</a></p>'
    )

    assert primary_page_should_fallback(html, "scp-597", None) is False
```

- [ ] **Step 2: Run predicate tests and verify RED**

Run:

```powershell
pytest -q tests/test_page_fallbacks.py -k primary_page_should_fallback
```

Expected: collection fails because `primary_page_should_fallback` does not exist.

- [ ] **Step 3: Implement the conservative DOM predicate**

Add:

```python
_ADULT_GATE_TEXT_MARKERS = (
    "成人内容",
    "18周岁",
)
_ARTICLE_BODY_MARKERS = (
    "项目编号",
    "项目等级",
    "特殊收容措施",
    "描述",
    "objectclass",
    "specialcontainmentprocedures",
    "description",
)


def primary_page_should_fallback(
    html: str,
    slug: str,
    mode: str | None,
) -> bool:
    """Return whether a successful primary page is only a configured gate."""
    if mode != "adult-gate-only":
        return False

    soup = BeautifulSoup(html, "html.parser")
    page_contents = soup.select("#page-content")
    if len(page_contents) != 1:
        return False
    page_content = page_contents[0]
    normalized_text = re.sub(r"\s+", "", page_content.get_text(" ", strip=True)).lower()
    if not all(marker in normalized_text for marker in _ADULT_GATE_TEXT_MARKERS):
        return False
    if any(marker in normalized_text for marker in _ARTICLE_BODY_MARKERS):
        return False

    expected_path = f"/adult:{slug.lower()}/noredirect/true"
    return any(
        (link.get("href") or "").split("?", 1)[0].rstrip("/").lower()
        == expected_path
        for link in page_content.find_all("a", href=True)
    )
```

Note that whitespace is removed before checking `18周岁`, so both `18 周岁` and `18周岁` match. The expected path retains its leading slash and drops only an optional query string/trailing slash; links to other slugs do not match.

- [ ] **Step 4: Run isolated and complete fallback tests**

Run:

```powershell
pytest -q tests/test_page_fallbacks.py
```

Expected: all fallback tests pass.

- [ ] **Step 5: Commit the focused predicate**

Commit:

```text
feat: detect configured adult page gates
```

### Task 3: Route a successful gate through the validated snapshot

**Files:**
- Modify: `src/scp_epub/pipeline.py:622-689`
- Test: `tests/test_pipeline.py:1224-1385`

- [ ] **Step 1: Add a FetchResult helper to the pipeline tests if one is not already present**

Use the existing `FakeFetcher` and cached files; no HTTP mock is needed. The primary result must be a normal successful `FetchResult` whose file contains the gate HTML.

- [ ] **Step 2: Write the gate-fallback pipeline test**

```python
def test_fetch_build_pages_uses_fallback_when_successful_primary_is_adult_gate(
    tmp_path: Path,
):
    snapshot = tmp_path / "translations" / "scp-597.zh-CN.html"
    snapshot.parent.mkdir()
    translated_html = simple_page(
        "SCP-597 - 万物之母",
        "<p><strong>项目编号：</strong>SCP-597</p><p>完整中文正文。</p>",
    )
    snapshot.write_text(translated_html, encoding="utf-8")
    fallback = PageFallback(
        source_url="https://scp-wiki.wikidot.com/scp-597",
        source_language="en",
        translated_title="SCP-597 - 万物之母",
        snapshot_path=snapshot,
        layout_signature=snapshot_layout_signature(translated_html),
        primary_page_rejection="adult-gate-only",
    )
    config = app_config(tmp_path, page_fallbacks={"scp-597": fallback})
    manifest = [
        PageRef(
            "SCP-597 - 万物之母",
            f"{BASE_URL}/scp-597",
            "scp-597",
            1,
            "scp",
            order=1,
        )
    ]
    fetcher = FakeFetcher(
        tmp_path / "fetcher",
        {
            "scp-597": simple_page(
                "SCP-597",
                '<p>本文包含成人内容，可能并不适合所有读者。'
                '如果你已年满 18 周岁并愿意阅读相关内容，'
                '<a href="/adult:scp-597/noredirect/true">点击这里继续</a>。</p>',
            )
        },
    )

    available, results, missing, records = fetch_build_pages(
        config, manifest, fetcher
    )

    assert [page.slug for page in available] == ["scp-597"]
    assert results[0].path == snapshot
    assert results[0].url == fallback.source_url
    assert missing == []
    assert records == [
        FallbackPageRecord(
            slug="scp-597",
            title="SCP-597 - 万物之母",
            source_url=fallback.source_url,
            source_language="en",
            snapshot_path="translations/scp-597.zh-CN.html",
        )
    ]
```

- [ ] **Step 3: Write the future-official-page priority test**

Create the same fallback, but make the successful primary page contain:

```html
<p>本文包含成人内容，请谨慎阅读。</p>
<p><strong>项目编号：</strong>SCP-597</p>
<p><strong>特殊收容措施：</strong>官方中文正文。</p>
```

Assert:

```python
assert results[0].url == f"{BASE_URL}/scp-597"
assert results[0].path != snapshot
assert records == []
assert missing == []
```

- [ ] **Step 4: Write the invalid-snapshot-after-gate test**

Use a valid snapshot file but give `PageFallback.layout_signature` a different 64-character digest. Assert the page is omitted and the failure is explicit:

```python
assert available == []
assert results == []
assert records == []
assert missing[0]["slug"] == "scp-597"
assert "primary page rejected by adult-gate-only" in missing[0]["reason"]
assert "fallback snapshot layout signature mismatch" in missing[0]["reason"]
```

- [ ] **Step 5: Run the three tests and verify RED**

Run:

```powershell
pytest -q tests/test_pipeline.py -k "successful_primary_is_adult_gate or future_official or invalid_snapshot_after_gate"
```

Expected: the first test keeps the primary gate result rather than loading the snapshot; the invalid-snapshot case also fails its expected missing-page assertions.

- [ ] **Step 6: Refactor fallback loading into one local branch and implement rejection**

Import the predicate:

```python
from .page_fallbacks import load_fallback_fetch_result, primary_page_should_fallback
```

Inside the manifest-order loop, resolve these values before the current exception branch:

```python
fallback = config.page_fallbacks.get(entry.slug)
primary_error = result if isinstance(result, Exception) else None
if (
    primary_error is None
    and fallback is not None
    and fallback.primary_page_rejection is not None
    and primary_page_should_fallback(
        result.path.read_text(encoding="utf-8"),
        entry.slug,
        fallback.primary_page_rejection,
    )
):
    primary_error = ValueError(
        f"primary page rejected by {fallback.primary_page_rejection}"
    )
```

Then use the existing fallback-loading code whenever `primary_error is not None`, formatting errors with `primary_error`. Keep the no-fallback missing-page branch unchanged in meaning. Do not mutate or delete the successful primary cache file.

Wrap primary HTML reading errors as a primary-page evaluation failure so a configured fallback can still be attempted:

```python
try:
    reject_primary = primary_page_should_fallback(
        result.path.read_text(encoding="utf-8"),
        entry.slug,
        fallback.primary_page_rejection,
    )
except (OSError, UnicodeError) as exc:
    primary_error = ValueError(f"primary page evaluation failed: {exc}")
```

- [ ] **Step 7: Run focused pipeline tests and verify GREEN**

Run:

```powershell
pytest -q tests/test_pipeline.py -k "fallback or adult_gate or future_official"
```

Expected: all selected tests pass, including all pre-existing fetch-failure fallback tests.

- [ ] **Step 8: Commit only the new pipeline/test hunks if separable**

Commit:

```text
feat: fall back from configured adult gates
```

Confirm the cached diff excludes worker caps, linked-appendix ordering, SCP-455 tests, and all other pre-existing changes.

### Task 4: Create and verify the complete SCP-597 translation snapshot

**Files:**
- Create: `translations/featured/scp-597.zh-CN.html`
- Modify: `tests/test_transform.py:17-180`

- [ ] **Step 1: Save the public English source outside tracked translation paths for reference**

Use the existing fetcher or a read-only request to retrieve `https://scp-wiki.wikidot.com/scp-597`. Do not add the raw response to Git. Confirm that its single `#page-content` contains the detailed `ADULT CONTENT` warning, `Item #: SCP-597`, `Special Containment Procedures`, `Description`, and documents `597-XX-23`, `597-XD-12`, `597-XX-25`, and `597-XY-C13`.

- [ ] **Step 2: Write the real-snapshot regression case before creating the snapshot**

Do not yet append `"scp-597"` to `FEATURED_FALLBACK_SLUGS`, because that tuple represents fully configured fallbacks and the YAML declaration belongs to Task 5. Instead, let the dedicated SCP-597 test below drive creation of the missing file first.

Add this dedicated content-completeness test:

```python
def test_scp_597_translation_is_complete_chinese_body_with_visible_warning():
    html = (FEATURED_TRANSLATIONS / "scp-597.zh-CN.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#page-content")
    assert content is not None
    text = content.get_text(" ", strip=True)

    assert "成人内容警告" in text
    assert all(label in text for label in ("性暗示", "露骨性内容", "性侵", "血腥内容"))
    assert text.index("成人内容警告") < text.index("项目编号")
    assert all(
        marker in text
        for marker in (
            "项目编号： SCP-597",
            "项目等级： Euclid",
            "特殊收容措施：",
            "描述：",
            "文档 597-XX-23",
            "文档 597-XD-12",
            "文档 597-XX-25",
            "文档 597-XY-C13",
        )
    )
    assert text.count("[数据删除]") >= 10
    assert "ADULT CONTENT" not in text
    assert "Special Containment Procedures" not in text
    assert "Description:" not in text
    assert content.find("script") is None
    assert content.select_one(".adult-content-warning") is not None
```

- [ ] **Step 3: Run the snapshot tests and verify RED**

Run:

```powershell
pytest -q tests/test_transform.py -k "scp_597 or featured_translation_snapshots"
```

Expected: failure because `translations/featured/scp-597.zh-CN.html` does not exist.

- [ ] **Step 4: Extract the content-only DOM and translate every visible source passage**

Create the snapshot with this envelope:

```html
<!--
source-url: https://scp-wiki.wikidot.com/scp-597
source-language: en
translation-language: zh-CN
translation-note: 完整翻译公开英文正文；成人内容警告在同页直接可见。
-->
<div id="page-content">
  <section class="adult-content-warning" aria-label="成人内容警告">
    <h2>成人内容警告</h2>
    <p>本文包含可能不适合所有读者的成人内容。</p>
    <ul>
      <li><strong>性暗示：</strong>包含性主题或相关语言，但不描写性行为。</li>
      <li><strong>露骨性内容：</strong>包含对性行为的描述。</li>
      <li><strong>性侵：</strong>包含非自愿性行为。</li>
      <li><strong>血腥内容：</strong>包含血液、血腥或肢体残损描写。</li>
    </ul>
  </section>
  <!-- Follow immediately with the translated article body. -->
</div>
```

Translate the English body paragraph by paragraph without summarizing. Preserve the exact source order and these structures:

- metadata paragraphs for item number and object class;
- all five containment-procedure paragraphs;
- all seven description/effects paragraphs through the staff-effects discussion;
- Addendum 01 heading, `Document 597-XX-23`, its introduction, and five specimen lists;
- Addendum 02 heading, `Document 597-XD-12`, and all three expunged passages;
- Addendum 03 heading, `Document 597-XX-25`, and its complete paragraph;
- Addendum 04 heading, `Document 597-XY-C13`, and all three concluding passages.

Use these fixed terminology choices consistently:

```text
Item # -> 项目编号
Object Class -> 项目等级
Special Containment Procedures -> 特殊收容措施
Description -> 描述
Addendum -> 附录
Document -> 文档
[DATA EXPUNGED] -> [数据删除]
overseer level personnel -> 监督者级人员
on-site analyst -> 现场分析员
psychological contamination -> 心理污染
suckle / suckling -> 吸吮 / 正在吸吮
teat -> 乳头
Oedipal complex -> 俄狄浦斯情结
```

Keep explicit material clinical and faithful. Do not euphemize away events, add interpretation, or invent text for expunged sections. Remove rating controls, site navigation, footer wikiwalk navigation, edit controls, scripts, and the interactive English warning modal.

- [ ] **Step 5: Compare source and translation structure manually**

Using BeautifulSoup, print the direct children of English and translated `#page-content`. Confirm that after excluding the English warning modal/rating/footer and adding the visible Chinese warning section, the translated article has the same sequence of metadata, containment, description, addenda, document headings, and lists. Count source and translation body blocks and investigate every difference rather than assuming it is harmless.

- [ ] **Step 6: Run the content tests and verify GREEN**

Run:

```powershell
pytest -q tests/test_transform.py -k "scp_597 or featured_translation_snapshots"
```

Expected: content, warning, structure, and language assertions pass.

- [ ] **Step 7: Compute and lock the real layout signature**

Run:

```powershell
@'
from pathlib import Path
from scp_epub.page_fallbacks import snapshot_layout_signature
path = Path("translations/featured/scp-597.zh-CN.html")
print(snapshot_layout_signature(path.read_text(encoding="utf-8")))
'@ | python -
```

Record the resulting 64-character digest for the exact test and YAML edits in Task 5. Never use a hand-written or all-zero digest.

- [ ] **Step 8: Run transform tests and verify GREEN**

Run:

```powershell
pytest -q tests/test_transform.py
```

Expected: all transform tests pass.

- [ ] **Step 9: Commit the translation and its isolated snapshot tests**

Commit:

```text
content: translate SCP-597 for Featured
```

### Task 5: Declare SCP-597 in the Featured configuration

**Files:**
- Modify: `config/featured-scp.yaml:52-90`
- Modify: `tests/test_config.py:321-340`
- Modify: `tests/test_transform.py:144-175`

- [ ] **Step 1: Extend the exact Featured fallback declaration and snapshot tests**

Append this expected tuple after the existing entries:

```python
(
    "scp-597",
    "https://scp-wiki.wikidot.com/scp-597",
    "en",
    "SCP-597 - 万物之母",
    "translations/featured/scp-597.zh-CN.html",
    "adult-gate-only",
),
```

Extend every existing expected fallback tuple with `fallback.primary_page_rejection`, using `None` for the five pre-existing entries. This proves backward compatibility rather than silently changing them.

Append `"scp-597"` to `FEATURED_FALLBACK_SLUGS`. The dedicated SCP-597 test from Task 4 already checks its markers and counts; extend it with:

```python
    assert len(soup.find_all("style")) == 0
    assert len(content.find_all("img")) == 0
    assert len(content.find_all("table")) == 0
    assert len(content.select(".collapsible-block")) == 0
    assert len(content.select(".yui-navset")) == 0
```

The generic `test_featured_fallback_snapshots_match_configured_layout_signatures` will lock the Task 4 digest through the real configuration.

- [ ] **Step 2: Run the Featured declaration test and verify RED**

Run:

```powershell
pytest -q tests/test_config.py::test_featured_scp_config_declares_translated_page_fallbacks tests/test_transform.py::test_featured_fallback_snapshots_match_configured_layout_signatures
```

Expected: SCP-597 is absent from the loaded config.

- [ ] **Step 3: Add the SCP-597 fallback mapping**

Use `apply_patch` to append a `page_fallbacks.scp-597` mapping with these five literal fields:

```yaml
  scp-597:
    source_url: https://scp-wiki.wikidot.com/scp-597
    source_language: en
    translated_title: SCP-597 - 万物之母
    snapshot_path: translations/featured/scp-597.zh-CN.html
    primary_page_rejection: adult-gate-only
```

Between `snapshot_path` and `primary_page_rejection`, add `layout_signature:` followed by the literal 64-character digest emitted by Task 4 Step 7. Keep SCP-597 after the five existing fallbacks so existing iteration/report order remains stable and the new exact-order tests agree.

- [ ] **Step 4: Run configuration and real-snapshot tests**

Run:

```powershell
pytest -q tests/test_config.py tests/test_transform.py
```

Expected: all tests pass and all six configured snapshots match their signatures.

- [ ] **Step 5: Commit only the SCP-597 config/test hunks if separable**

Commit:

```text
feat: enable SCP-597 Featured translation
```

Confirm cached YAML excludes the pre-existing SCP-455 explicit appendix change.

### Task 6: Verify page selection and all output modes

**Files:**
- Verify only; modify tests if a real regression is found.

- [ ] **Step 1: Run the focused suite**

```powershell
pytest -q tests/test_page_fallbacks.py tests/test_config.py tests/test_pipeline.py tests/test_transform.py
```

Expected: all selected tests pass.

- [ ] **Step 2: Run Kindle-related regressions**

```powershell
pytest -q tests/test_kindle.py tests/test_kindle_stable.py tests/test_cli.py tests/test_epub.py
```

Expected: all selected tests pass; no output naming or report regression.

- [ ] **Step 3: Run the full test suite**

```powershell
pytest -q
```

Expected: all tests pass with no new warnings.

- [ ] **Step 4: Build the normal Featured EPUB**

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured
```

Expected output includes:

```text
Wrote C:\Users\Administrator\Documents\SCP-Story\output\epub\SCP基金会档案精选.epub
```

- [ ] **Step 5: Verify report selection and EPUB text**

```powershell
@'
import json
import zipfile
from pathlib import Path

report_path = Path("output/reports/SCP基金会档案精选-report.json")
report = json.loads(report_path.read_text(encoding="utf-8"))
fallback = next(item for item in report["fallback_pages"] if item["slug"] == "scp-597")
assert fallback == {
    "slug": "scp-597",
    "title": "SCP-597 - 万物之母",
    "source_url": "https://scp-wiki.wikidot.com/scp-597",
    "source_language": "en",
    "snapshot_path": "translations/featured/scp-597.zh-CN.html",
}
assert "scp-597" not in {item["slug"] for item in report["missing_pages"]}

with zipfile.ZipFile("output/epub/SCP基金会档案精选.epub") as archive:
    pages = [
        archive.read(name).decode("utf-8", "replace")
        for name in archive.namelist()
        if name.endswith(".xhtml")
    ]
page = next(text for text in pages if "SCP-597 - 万物之母" in text)
for marker in (
    "成人内容警告",
    "性侵",
    "特殊收容措施",
    "文档 597-XX-23",
    "文档 597-XY-C13",
):
    assert marker in page, marker
print("verified SCP-597 Featured translation")
'@ | python -
```

Expected: prints `verified SCP-597 Featured translation` and exits 0.

- [ ] **Step 6: Build Kindle modes if Calibre is available**

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

Expected: each mode writes its independently named EPUB, AZW3, and report. Both reports select SCP-597 through the same fallback and neither lists it in `missing_pages`.

### Task 7: Final review and handoff

**Files:**
- Review all feature changes and the existing dirty worktree boundary.

- [ ] **Step 1: Review feature behavior against the approved design**

Confirm:

- the detector is inactive without `primary_page_rejection`;
- only a same-slug adult link plus warning/age text and absence of article markers triggers it;
- an official complete Chinese page wins automatically;
- a bad translation snapshot produces a missing-page record rather than packaging the gate;
- full translated content and the visible warning are present;
- Series configurations remain unchanged;
- no raw page cache or generated EPUB/report is staged.

- [ ] **Step 2: Inspect Git state and cached scope**

```powershell
git status --short
git diff --check
git diff --cached --check
git diff --cached --stat
```

Expected: no whitespace errors. Any pre-existing unrelated modifications remain unstaged and intact.

- [ ] **Step 3: Run final verification after any review correction**

```powershell
pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Prepare the completion report**

Report the changed files, exact tests/builds run, output paths, SCP-597 report entry, and any unrelated pre-existing dirty files left untouched. Do not claim Kindle/AZW3 verification if Calibre was unavailable or a build was not actually run.
