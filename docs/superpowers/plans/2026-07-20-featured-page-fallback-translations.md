# Featured Page Fallback Translations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace five missing Featured Chinese pages with reproducible, layout-preserving Chinese translation snapshots sourced from the specified English and Japanese pages.

**Architecture:** Add a typed `page_fallbacks` configuration and a focused snapshot-validation module. The build continues to fetch the Chinese URL first; only a fetch failure loads a committed Chinese snapshot, uses the foreign source URL as the transform base, records the fallback in the build report, and otherwise follows the existing EPUB/Kindle pipeline unchanged.

**Tech Stack:** Python 3.11+, dataclasses, BeautifulSoup, tinycss2-compatible CSS text handling, PyYAML, pytest, EbookLib, Pillow, Calibre `ebook-convert`.

---

## File map

- Create `src/scp_epub/page_fallbacks.py`: validate snapshots, compute structural signatures, and create fallback `FetchResult` values.
- Create `tests/test_page_fallbacks.py`: isolated snapshot/signature tests.
- Create `translations/featured/scp-4846.zh-CN.html`: curated Chinese snapshot.
- Create `translations/featured/scp-8304.zh-CN.html`: curated Chinese snapshot.
- Create `translations/featured/scp-8274.zh-CN.html`: curated Chinese snapshot.
- Create `translations/featured/scp-7875.zh-CN.html`: curated Chinese snapshot.
- Create `translations/featured/yamizushi-file-no233.zh-CN.html`: curated Chinese snapshot.
- Modify `src/scp_epub/models.py`: add `PageFallback` and `FallbackPageRecord`; expose fallbacks on `AppConfig`.
- Modify `src/scp_epub/config.py`: parse and validate `page_fallbacks`.
- Modify `src/scp_epub/pipeline.py`: use snapshots after primary fetch failure and pass source URLs to the transformer.
- Modify `src/scp_epub/epub.py`: conditionally serialize `fallback_pages`.
- Modify `config/featured-scp.yaml`: declare the five fallback pages and final layout signatures.
- Modify `tests/test_config.py`: configuration and Featured declarations.
- Modify `tests/test_pipeline.py`: primary-page priority, fallback success/failure, titles, links, Kindle integration.
- Modify `tests/test_epub.py`: conditional report serialization.
- Modify `tests/test_transform.py`: actual snapshot layout smoke tests.

### Task 1: Add typed page-fallback configuration

**Files:**
- Modify: `src/scp_epub/models.py:42-99`
- Modify: `src/scp_epub/config.py:44-128,233-287`
- Modify: `tests/test_config.py:1-342`
- Modify: `tests/test_pipeline.py:16-98`

- [ ] **Step 1: Write failing configuration tests**

Add a helper and parsing test to `tests/test_config.py`:

```python
def write_config_with_page_fallbacks(config_path: Path, fallbacks_yaml: str) -> None:
    write_config(config_path)
    config_path.write_text(
        f"{config_path.read_text(encoding='utf-8')}\npage_fallbacks:\n{fallbacks_yaml}",
        encoding="utf-8",
    )


def test_load_config_parses_page_fallbacks(tmp_path: Path):
    snapshot = tmp_path / "translations" / "featured" / "scp-4846.zh-CN.html"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text('<div id="page-content"><p>友善化石</p></div>', encoding="utf-8")
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

    fallback = load_config(config_path).page_fallbacks["scp-4846"]

    assert fallback.source_url == "https://scp-wiki.wikidot.com/scp-4846"
    assert fallback.source_language == "en"
    assert fallback.translated_title == "SCP-4846 - 友善化石"
    assert fallback.snapshot_path == snapshot
    assert fallback.layout_signature == (
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    )
```

Add parametrized rejection tests for these exact invalid values:

```python
@pytest.mark.parametrize(
    ("fallback_yaml", "message"),
    [
        ("  scp-4846: invalid\n", "page_fallbacks.scp-4846 must be a mapping"),
        (
            """  scp-4846:
    source_url: ftp://example.test/scp-4846
    source_language: en
    translated_title: SCP-4846 - 友善化石
    snapshot_path: translations/featured/scp-4846.zh-CN.html
    layout_signature: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
""",
            "page_fallbacks.scp-4846.source_url must be an absolute HTTP(S) URL",
        ),
        (
            """  scp-4846:
    source_url: https://scp-wiki.wikidot.com/scp-4846
    source_language: en
    translated_title: SCP-4846 - 友善化石
    snapshot_path: ../outside.html
    layout_signature: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
""",
            "page_fallbacks.scp-4846.snapshot_path must stay inside the workspace",
        ),
        (
            """  scp-4846:
    source_url: https://scp-wiki.wikidot.com/scp-4846
    source_language: en
    translated_title: SCP-4846 - 友善化石
    snapshot_path: translations/featured/scp-4846.zh-CN.html
    layout_signature: bad
""",
            "page_fallbacks.scp-4846.layout_signature must be a 64-character hexadecimal SHA-256",
        ),
        (
            """  scp-4846:
    source_url: https://scp-wiki.wikidot.com/scp-4846
    source_language: en
    translated_title: SCP-4846 - 友善化石
    snapshot_path: translations/featured/missing.zh-CN.html
    layout_signature: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
""",
            "page_fallbacks.scp-4846.snapshot_path does not exist",
        ),
        (
            """  scp-4846:
    source_url: https://scp-wiki.wikidot.com/scp-4846
    source_language: en
    translated_title: SCP-4846 - 友善化石
    snapshot_path: translations/featured/scp-4846.zh-CN.html
    layout_signature: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
    translate_at_build_time: true
""",
            "page_fallbacks.scp-4846 contains unknown keys: translate_at_build_time",
        ),
        (
            """  SCP-4846:
    source_url: https://scp-wiki.wikidot.com/scp-4846
    source_language: en
    translated_title: SCP-4846 - 友善化石
    snapshot_path: translations/featured/scp-4846.zh-CN.html
    layout_signature: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
  scp-4846:
    source_url: https://scp-wiki.wikidot.com/scp-4846
    source_language: en
    translated_title: SCP-4846 - 友善化石
    snapshot_path: translations/featured/scp-4846.zh-CN.html
    layout_signature: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
""",
            "page_fallbacks contains duplicate key after normalization: scp-4846",
        ),
    ],
)
def test_load_config_rejects_invalid_page_fallbacks(
    tmp_path: Path,
    fallback_yaml: str,
    message: str,
):
    snapshot = tmp_path / "translations" / "featured" / "scp-4846.zh-CN.html"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text('<div id="page-content"></div>', encoding="utf-8")
    config_path = tmp_path / "series.yaml"
    write_config_with_page_fallbacks(config_path, fallback_yaml)

    with pytest.raises(ValueError, match=re.escape(message)):
        load_config(config_path)


def test_load_config_rejects_absolute_page_fallback_snapshot_path(tmp_path: Path):
    snapshot = tmp_path / "translations" / "featured" / "scp-4846.zh-CN.html"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text('<div id="page-content"></div>', encoding="utf-8")
    config_path = tmp_path / "series.yaml"
    write_config_with_page_fallbacks(
        config_path,
        f"""  scp-4846:
    source_url: https://scp-wiki.wikidot.com/scp-4846
    source_language: en
    translated_title: SCP-4846 - 友善化石
    snapshot_path: {snapshot.as_posix()}
    layout_signature: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
""",
    )

    with pytest.raises(
        ValueError,
        match="page_fallbacks.scp-4846.snapshot_path must be a relative path inside the workspace",
    ):
        load_config(config_path)
```

- [ ] **Step 2: Run the tests and confirm the missing model/parser failure**

Run:

```powershell
pytest -q tests/test_config.py -k page_fallbacks
```

Expected: FAIL because `AppConfig` has no `page_fallbacks` and `load_config` ignores the new mapping.

- [ ] **Step 3: Add the data models**

Add to `src/scp_epub/models.py` after `PageOverride`:

```python
@dataclass(frozen=True)
class PageFallback:
    source_url: str
    source_language: str
    translated_title: str
    snapshot_path: Path
    layout_signature: str


@dataclass(frozen=True)
class FallbackPageRecord:
    slug: str
    title: str
    source_url: str
    source_language: str
    snapshot_path: str
```

Add this field to `AppConfig` before `appendix`:

```python
page_fallbacks: dict[str, PageFallback] = field(default_factory=dict)
```

- [ ] **Step 4: Implement strict configuration parsing**

Import `re`, `urlparse`, and `PageFallback` in `src/scp_epub/config.py`, then add:

```python
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")


def _absolute_http_url(value: Any, name: str) -> str:
    url = _required_string(value, name).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    return url


def _layout_signature(value: Any, name: str) -> str:
    signature = _required_string(value, name).strip().lower()
    if _SHA256_RE.fullmatch(signature) is None:
        raise ValueError(f"{name} must be a 64-character hexadecimal SHA-256")
    return signature


def _load_page_fallbacks(
    value: Any,
    name: str,
    workspace: Path,
) -> dict[str, PageFallback]:
    if value is None:
        return {}
    fallbacks: dict[str, PageFallback] = {}
    for raw_slug, raw_fallback in _mapping(value, name).items():
        slug = _required_string(raw_slug, f"{name} key").strip().lower()
        if slug in fallbacks:
            raise ValueError(f"{name} contains duplicate key after normalization: {slug}")
        fallback_name = f"{name}.{slug}"
        fallback = _mapping(raw_fallback, fallback_name)
        _reject_unknown_keys(
            fallback,
            {
                "source_url",
                "source_language",
                "translated_title",
                "snapshot_path",
                "layout_signature",
            },
            fallback_name,
        )
        snapshot_path = _workspace_path(
            workspace,
            f"{fallback_name}.snapshot_path",
            fallback.get("snapshot_path"),
        )
        if not snapshot_path.is_file():
            raise ValueError(f"{fallback_name}.snapshot_path does not exist: {snapshot_path}")
        fallbacks[slug] = PageFallback(
            source_url=_absolute_http_url(
                fallback.get("source_url"),
                f"{fallback_name}.source_url",
            ),
            source_language=_required_string(
                fallback.get("source_language"),
                f"{fallback_name}.source_language",
            ).strip(),
            translated_title=_required_string(
                fallback.get("translated_title"),
                f"{fallback_name}.translated_title",
            ).strip(),
            snapshot_path=snapshot_path,
            layout_signature=_layout_signature(
                fallback.get("layout_signature"),
                f"{fallback_name}.layout_signature",
            ),
        )
    return fallbacks
```

Pass `workspace` into the loader from `load_config`:

```python
page_fallbacks=_load_page_fallbacks(
    data.get("page_fallbacks", {}),
    "page_fallbacks",
    workspace,
),
```

Update `tests/test_pipeline.py::app_config` to accept and pass:

```python
page_fallbacks: dict[str, PageFallback] | None = None,
```

and:

```python
page_fallbacks=page_fallbacks or {},
```

- [ ] **Step 5: Run focused and full configuration tests**

Run:

```powershell
pytest -q tests/test_config.py
```

Expected: PASS.

- [ ] **Step 6: Commit the configuration model**

```powershell
git add src/scp_epub/models.py src/scp_epub/config.py tests/test_config.py tests/test_pipeline.py
git commit -m "feat: configure page fallbacks"
```

### Task 2: Validate translated snapshots and compute layout signatures

**Files:**
- Create: `src/scp_epub/page_fallbacks.py`
- Create: `tests/test_page_fallbacks.py`

- [ ] **Step 1: Write failing signature and validation tests**

Create `tests/test_page_fallbacks.py`:

```python
from pathlib import Path

import pytest

from scp_epub.models import PageFallback
from scp_epub.page_fallbacks import (
    load_fallback_fetch_result,
    snapshot_layout_signature,
)


SOURCE_HTML = """
<html><head><style>.badge::before { content: "Level"; color: red; }</style></head>
<body><div id="page-content"><section class="panel"><h1 title="English">Title</h1>
<img src="/local--files/example/image.png" alt="English image"/></section></div></body></html>
"""

TRANSLATED_HTML = """
<html><head><style>.badge::before { content: "等级"; color: red; }</style></head>
<body><div id="page-content"><section class="panel"><h1 title="中文">标题</h1>
<img src="/local--files/example/image.png" alt="中文图片"/></section></div></body></html>
"""


def test_snapshot_layout_signature_ignores_translated_text_only():
    assert snapshot_layout_signature(SOURCE_HTML) == snapshot_layout_signature(TRANSLATED_HTML)


def test_snapshot_layout_signature_detects_structure_change():
    changed = TRANSLATED_HTML.replace('<section class="panel">', '<article class="panel">').replace(
        "</section>", "</article>"
    )
    assert snapshot_layout_signature(SOURCE_HTML) != snapshot_layout_signature(changed)


@pytest.mark.parametrize(
    ("html", "message"),
    [
        ("<html><body></body></html>", "must contain exactly one #page-content"),
        (
            '<div id="page-content"></div><div id="page-content"></div>',
            "must contain exactly one #page-content",
        ),
        ('<div id="page-content"><script>alert(1)</script></div>', "must not contain script elements"),
    ],
)
def test_load_fallback_fetch_result_rejects_invalid_snapshot(
    tmp_path: Path,
    html: str,
    message: str,
):
    path = tmp_path / "snapshot.html"
    path.write_text(html, encoding="utf-8")
    fallback = PageFallback(
        source_url="https://scp-wiki.wikidot.com/scp-4846",
        source_language="en",
        translated_title="SCP-4846 - 友善化石",
        snapshot_path=path,
        layout_signature="0" * 64,
    )

    with pytest.raises(ValueError, match=message):
        load_fallback_fetch_result("scp-4846", fallback)


def test_load_fallback_fetch_result_returns_source_based_result(tmp_path: Path):
    path = tmp_path / "snapshot.html"
    path.write_text(TRANSLATED_HTML, encoding="utf-8")
    fallback = PageFallback(
        source_url="https://scp-wiki.wikidot.com/scp-4846",
        source_language="en",
        translated_title="SCP-4846 - 友善化石",
        snapshot_path=path,
        layout_signature=snapshot_layout_signature(TRANSLATED_HTML),
    )

    result = load_fallback_fetch_result("scp-4846", fallback)

    assert result.url == fallback.source_url
    assert result.path == path
    assert result.status_code == 200
    assert result.content_type == "text/html; charset=utf-8"
    assert result.from_cache is True


def test_load_fallback_fetch_result_rejects_non_utf8_snapshot(tmp_path: Path):
    path = tmp_path / "snapshot.html"
    path.write_bytes(b"\xff\xfe\xfd")
    fallback = PageFallback(
        source_url="https://scp-wiki.wikidot.com/scp-4846",
        source_language="en",
        translated_title="SCP-4846 - 友善化石",
        snapshot_path=path,
        layout_signature="0" * 64,
    )

    with pytest.raises(ValueError, match="is unreadable"):
        load_fallback_fetch_result("scp-4846", fallback)
```

- [ ] **Step 2: Run the new test file and verify import failures**

Run:

```powershell
pytest -q tests/test_page_fallbacks.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scp_epub.page_fallbacks'`.

- [ ] **Step 3: Implement the focused snapshot module**

Create `src/scp_epub/page_fallbacks.py`:

```python
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from .models import FetchResult, PageFallback


TRANSLATABLE_ATTRIBUTES = frozenset({"alt", "title", "aria-label"})
_CSS_CONTENT_RE = re.compile(
    r"(\bcontent\s*:\s*)(['\"])(.*?)(?<!\\)\2",
    flags=re.IGNORECASE | re.DOTALL,
)


def snapshot_layout_signature(html: str) -> str:
    soup, page_content = _validated_snapshot(html)
    tokens: list[object] = []
    for style in soup.find_all("style"):
        tokens.append(
            [
                "style",
                _CSS_CONTENT_RE.sub(
                    lambda match: f'{match.group(1)}{match.group(2)}#text{match.group(2)}',
                    style.get_text("", strip=False),
                ),
            ]
        )
    _append_structure_tokens(page_content, tokens)
    payload = json.dumps(tokens, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_fallback_fetch_result(slug: str, fallback: PageFallback) -> FetchResult:
    try:
        html = fallback.snapshot_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"fallback snapshot for {slug} is unreadable: {exc}") from exc
    _validated_snapshot(html)
    actual_signature = snapshot_layout_signature(html)
    if actual_signature != fallback.layout_signature:
        raise ValueError(
            f"fallback snapshot layout signature mismatch for {slug}: "
            f"expected {fallback.layout_signature}, got {actual_signature}"
        )
    return FetchResult(
        url=fallback.source_url,
        path=fallback.snapshot_path,
        metadata_path=fallback.snapshot_path,
        from_cache=True,
        status_code=200,
        content_type="text/html; charset=utf-8",
    )


def _validated_snapshot(html: str) -> tuple[BeautifulSoup, Tag]:
    soup = BeautifulSoup(html, "html.parser")
    page_contents = soup.select("#page-content")
    if len(page_contents) != 1:
        raise ValueError("fallback snapshot must contain exactly one #page-content")
    if soup.find("script") is not None:
        raise ValueError("fallback snapshot must not contain script elements")
    return soup, page_contents[0]


def _append_structure_tokens(node: Tag, tokens: list[object]) -> None:
    attributes: list[list[object]] = []
    for name, value in sorted(node.attrs.items()):
        normalized_value: object
        if name in TRANSLATABLE_ATTRIBUTES:
            normalized_value = "#translated"
        elif isinstance(value, list):
            normalized_value = list(value)
        else:
            normalized_value = str(value)
        attributes.append([name, normalized_value])
    tokens.append(["open", node.name, attributes])
    for child in node.children:
        if isinstance(child, Tag):
            _append_structure_tokens(child, tokens)
        elif isinstance(child, NavigableString) and str(child).strip():
            tokens.append(["text"])
    tokens.append(["close", node.name])
```

- [ ] **Step 4: Run the snapshot tests**

Run:

```powershell
pytest -q tests/test_page_fallbacks.py
```

Expected: PASS.

- [ ] **Step 5: Commit the snapshot validator**

```powershell
git add src/scp_epub/page_fallbacks.py tests/test_page_fallbacks.py
git commit -m "feat: validate translated page snapshots"
```

### Task 3: Load page fallbacks in the build pipeline

**Files:**
- Modify: `src/scp_epub/pipeline.py:3-47,207-306,463-511,1020-1085`
- Modify: `tests/test_pipeline.py:16-98,930-980,1226-1260`

- [ ] **Step 1: Write failing primary-success and fallback-success tests**

Add imports for `FallbackPageRecord`, `PageFallback`, `snapshot_layout_signature`, and `_process_pages`, then add to `tests/test_pipeline.py`:

```python
def fallback_config(tmp_path: Path, html: str) -> PageFallback:
    snapshot = tmp_path / "translations" / "featured" / "scp-4846.zh-CN.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(html, encoding="utf-8")
    return PageFallback(
        source_url="https://scp-wiki.wikidot.com/scp-4846",
        source_language="en",
        translated_title="SCP-4846 - 友善化石",
        snapshot_path=snapshot,
        layout_signature=snapshot_layout_signature(html),
    )


def test_fetch_build_pages_prefers_available_chinese_page(tmp_path: Path):
    fallback_html = '<div id="page-content"><p>回退译文</p></div>'
    config = app_config(
        tmp_path,
        page_fallbacks={"scp-4846": fallback_config(tmp_path, fallback_html)},
    )
    entry = PageRef(
        title="SCP-4846",
        url=f"{BASE_URL}/scp-4846",
        slug="scp-4846",
        level=1,
        role="scp",
    )
    fetcher = FakeFetcher(tmp_path, {"scp-4846": '<div id="page-content"><p>中文正文</p></div>'})

    available, results, missing, fallback_pages = fetch_build_pages(config, [entry], fetcher)

    assert available == [entry]
    assert results[0].url == entry.url
    assert missing == []
    assert fallback_pages == []


def test_fetch_build_pages_uses_snapshot_after_chinese_404(tmp_path: Path):
    fallback_html = (
        '<div id="page-content"><img src="/local--files/scp-4846/Jim.jpg" alt="吉姆"/>'
        '<p>友善化石</p></div>'
    )
    config = app_config(
        tmp_path,
        page_fallbacks={"scp-4846": fallback_config(tmp_path, fallback_html)},
    )
    entry = PageRef(
        title="SCP-4846",
        url=f"{BASE_URL}/scp-4846",
        slug="scp-4846",
        level=1,
        role="scp",
        order=7,
    )
    fetcher = FakeFetcher(tmp_path, {}, failed_pages={"scp-4846"})

    available, results, missing, fallback_pages = fetch_build_pages(config, [entry], fetcher)

    assert available[0].title == "SCP-4846 - 友善化石"
    assert available[0].slug == entry.slug
    assert available[0].order == 7
    assert results[0].url == "https://scp-wiki.wikidot.com/scp-4846"
    assert missing == []
    assert fallback_pages == [
        FallbackPageRecord(
            slug="scp-4846",
            title="SCP-4846 - 友善化石",
            source_url="https://scp-wiki.wikidot.com/scp-4846",
            source_language="en",
            snapshot_path="translations/featured/scp-4846.zh-CN.html",
        )
    ]

    processed = _process_pages(
        config,
        config.volumes["001-099"],
        available,
        results,
    )[0]
    assert processed.asset_urls == (
        "https://scp-wiki.wikidot.com/local--files/scp-4846/Jim.jpg",
    )
```

- [ ] **Step 2: Write the failing fallback-error test**

```python
def test_fetch_build_pages_reports_primary_and_fallback_errors(tmp_path: Path):
    html = '<div id="page-content"><p>译文</p></div>'
    fallback = fallback_config(tmp_path, html)
    fallback = PageFallback(
        source_url=fallback.source_url,
        source_language=fallback.source_language,
        translated_title=fallback.translated_title,
        snapshot_path=fallback.snapshot_path,
        layout_signature="0" * 64,
    )
    config = app_config(tmp_path, page_fallbacks={"scp-4846": fallback})
    entry = PageRef(
        title="SCP-4846",
        url=f"{BASE_URL}/scp-4846",
        slug="scp-4846",
        level=1,
        role="scp",
    )
    fetcher = FakeFetcher(tmp_path, {}, failed_pages={"scp-4846"})

    available, results, missing, fallback_pages = fetch_build_pages(config, [entry], fetcher)

    assert available == []
    assert results == []
    assert fallback_pages == []
    assert missing[0]["slug"] == "scp-4846"
    assert "failed fake page for scp-4846" in missing[0]["reason"]
    assert "fallback failed" in missing[0]["reason"]
    assert "layout signature mismatch" in missing[0]["reason"]
```

- [ ] **Step 3: Run focused pipeline tests and confirm tuple/behavior failures**

Run:

```powershell
pytest -q tests/test_pipeline.py -k "fetch_build_pages and fallback"
```

Expected: FAIL because `fetch_build_pages` returns three values and never loads snapshots.

- [ ] **Step 4: Implement fallback loading**

Import `replace` from `dataclasses`, `FallbackPageRecord`, and `load_fallback_fetch_result`. Change the return annotation and initialize `fallback_pages`:

```python
) -> tuple[
    list[PageRef],
    list[FetchResult],
    list[dict[str, str]],
    list[FallbackPageRecord],
]:
    available_manifest: list[PageRef] = []
    fetch_results: list[FetchResult] = []
    missing_pages: list[dict[str, str]] = []
    fallback_pages: list[FallbackPageRecord] = []
```

Replace the current `except` body with:

```python
        except Exception as primary_error:
            fallback = config.page_fallbacks.get(entry.slug)
            if fallback is None:
                missing_pages.append(
                    {
                        "slug": entry.slug,
                        "title": entry.title,
                        "url": entry.url,
                        "reason": str(primary_error),
                    }
                )
                continue
            try:
                result = load_fallback_fetch_result(entry.slug, fallback)
            except Exception as fallback_error:
                missing_pages.append(
                    {
                        "slug": entry.slug,
                        "title": entry.title,
                        "url": entry.url,
                        "reason": f"{primary_error}; fallback failed: {fallback_error}",
                    }
                )
                continue
            entry = replace(entry, title=fallback.translated_title)
            fallback_pages.append(
                FallbackPageRecord(
                    slug=entry.slug,
                    title=entry.title,
                    source_url=fallback.source_url,
                    source_language=fallback.source_language,
                    snapshot_path=fallback.snapshot_path.relative_to(config.workspace).as_posix(),
                )
            )
```

Return four values:

```python
return available_manifest, fetch_results, missing_pages, fallback_pages
```

Update `build_volume` to unpack the fourth value. Update existing direct tests that unpack `fetch_build_pages` to expect an empty fourth list.

- [ ] **Step 5: Use `FetchResult.url` as the transform base URL**

Change both main and inline transform calls in `_process_pages`:

```python
page = transform_page(
    entry,
    result.path.read_text(encoding="utf-8"),
    result.url,
    manifest_slugs,
    include_tab_titles=include_tab_titles,
    unwrap_single_included_tab=unwrap_single_included_tab,
    background_asset_url=(
        configured_page.epub_background_url if configured_page is not None else None
    ),
    page_options=_page_transform_options(config, entry),
)
```

and:

```python
transform_page(
    inline_entry,
    inline_result.path.read_text(encoding="utf-8"),
    inline_result.url,
    manifest_slugs,
    page_options=_page_transform_options(config, inline_entry),
)
```

The fallback-success test written in Step 1 already calls `_process_pages` and asserts that the relative image URL resolves against the English `FetchResult.url`. Keep that assertion unchanged when updating the implementation.

- [ ] **Step 6: Run pipeline tests**

Run:

```powershell
pytest -q tests/test_pipeline.py
```

Expected: PASS.

- [ ] **Step 7: Commit pipeline fallback behavior**

```powershell
git add src/scp_epub/pipeline.py tests/test_pipeline.py
git commit -m "feat: load translated page fallbacks"
```

### Task 4: Record fallback pages in build reports

**Files:**
- Modify: `src/scp_epub/epub.py:709-738`
- Modify: `src/scp_epub/pipeline.py:284-302`
- Modify: `tests/test_epub.py:600-660`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing conditional-report tests**

In `tests/test_epub.py`, add:

```python
from scp_epub.models import FallbackPageRecord


def test_write_build_report_includes_used_fallback_pages(tmp_path: Path):
    report_path = tmp_path / "report.json"
    fallback = FallbackPageRecord(
        slug="scp-4846",
        title="SCP-4846 - 友善化石",
        source_url="https://scp-wiki.wikidot.com/scp-4846",
        source_language="en",
        snapshot_path="translations/featured/scp-4846.zh-CN.html",
    )

    write_build_report(
        report_path,
        pages=[_page("scp-4846", "SCP-4846 - 友善化石", 1)],
        output_path=tmp_path / "book.epub",
        fallback_pages=[fallback],
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["fallback_pages"] == [
        {
            "slug": "scp-4846",
            "title": "SCP-4846 - 友善化石",
            "source_url": "https://scp-wiki.wikidot.com/scp-4846",
            "source_language": "en",
            "snapshot_path": "translations/featured/scp-4846.zh-CN.html",
        }
    ]


def test_write_build_report_omits_empty_fallback_pages(tmp_path: Path):
    report_path = tmp_path / "report.json"
    write_build_report(
        report_path,
        pages=[_page("scp-001", "SCP-001", 1)],
        output_path=tmp_path / "book.epub",
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "fallback_pages" not in report
```

- [ ] **Step 2: Run the report tests and confirm the unexpected-keyword failure**

Run:

```powershell
pytest -q tests/test_epub.py -k fallback_pages
```

Expected: FAIL because `write_build_report` does not accept `fallback_pages`.

- [ ] **Step 3: Implement conditional serialization**

Add `FallbackPageRecord` to imports and extend `write_build_report`:

```python
from collections.abc import Sequence


def write_build_report(
    path: Path,
    *,
    pages: list[ProcessedPage],
    output_path: Path,
    external_links: Sequence[str] = (),
    missing_assets: Sequence[str] = (),
    missing_pages: Sequence[dict[str, str]] = (),
    fallback_pages: Sequence[FallbackPageRecord] = (),
) -> Path:
```

Use the existing local report dictionary, then conditionally add:

```python
if fallback_pages:
    report["fallback_pages"] = [
        {
            "slug": page.slug,
            "title": page.title,
            "source_url": page.source_url,
            "source_language": page.source_language,
            "snapshot_path": page.snapshot_path,
        }
        for page in fallback_pages
    ]
```

Pass `fallback_pages=fallback_pages` from `build_volume`.

- [ ] **Step 4: Run report and pipeline tests**

Run:

```powershell
pytest -q tests/test_epub.py tests/test_pipeline.py
```

Expected: PASS.

- [ ] **Step 5: Commit report support**

```powershell
git add src/scp_epub/epub.py src/scp_epub/pipeline.py tests/test_epub.py tests/test_pipeline.py
git commit -m "feat: report translated page fallbacks"
```

### Task 5: Create the SCP-4846 and SCP-8304 Chinese snapshots

**Files:**
- Create: `translations/featured/scp-4846.zh-CN.html`
- Create: `translations/featured/scp-8304.zh-CN.html`
- Modify: `tests/test_transform.py`

- [ ] **Step 1: Fetch source pages into ignored raw cache**

Run with the project Python:

```powershell
$python = Join-Path (Join-Path $env:TEMP 'scp-story-build-venv') 'Scripts\python.exe'
@'
from pathlib import Path
from scp_epub.cache import CacheStore
from scp_epub.fetcher import Fetcher

fetcher = Fetcher(CacheStore(Path("data/raw")), retry_count=3, request_timeout_seconds=60)
for slug, url in {
    "fallback-source-scp-4846": "https://scp-wiki.wikidot.com/scp-4846",
    "fallback-source-scp-8304": "https://scp-wiki.wikidot.com/scp-8304",
}.items():
    result = fetcher.fetch_page(slug, url, force=True)
    print(result.path)
'@ | & $python -
```

Expected: two HTML paths under ignored `data/raw/pages/`.

- [ ] **Step 2: Extract curated snapshot skeletons**

Use this one-off command to copy all source `<style>` elements and the exact `#page-content` subtree into temporary files:

```powershell
@'
from copy import copy
from pathlib import Path
from bs4 import BeautifulSoup

for slug in ("scp-4846", "scp-8304"):
    source = Path(f"data/raw/pages/fallback-source-{slug}.html")
    soup = BeautifulSoup(source.read_text(encoding="utf-8"), "html.parser")
    page_content = soup.select_one("#page-content")
    if page_content is None:
        raise SystemExit(f"missing #page-content in {source}")
    output = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
    for style in soup.find_all("style"):
        output.head.append(copy(style))
    output.body.append(copy(page_content))
    target = Path(f"translations/featured/{slug}.zh-CN.html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(output), encoding="utf-8")
    print(target)
'@ | & $python -
```

- [ ] **Step 3: Translate SCP-4846 without altering DOM structure**

Edit `translations/featured/scp-4846.zh-CN.html` with `apply_patch`. Add this exact comment before `<html>`:

```html
<!-- translated-source: https://scp-wiki.wikidot.com/scp-4846; source-language: en -->
```

Translate every visible English text node, human-readable `alt`/`title`/`aria-label`, and displayed CSS `content:` string. Preserve all tag names, tag order, classes, IDs, styles, URLs, SCP numbers, redactions, names, and image count.

Use these terminology requirements:

- `Item #` → `项目编号`
- `Object Class` → `项目等级`
- `Special Containment Procedures` → `特殊收容措施`
- `Description` → `描述`
- `Instance #` → `个体编号`
- `Discovery Location` → `发现地点`
- `Instance Description` → `个体描述`
- `Notes` → `备注`
- Retain the names `Jim`, `Shelly`, `Ray`, `Alex`, and `Buddy` in Latin letters after their Chinese descriptions.

- [ ] **Step 4: Translate SCP-8304 without altering DOM structure**

Add this exact comment before `<html>`:

```html
<!-- translated-source: https://scp-wiki.wikidot.com/scp-8304; source-language: en -->
```

Edit `translations/featured/scp-8304.zh-CN.html` with the same structural restrictions. Translate the ACS labels, containment procedures, description, interpretation bullets, experiment/test records, table cells, collapsible labels, footnotes, and captions. Preserve the film title and personal names consistently; introduce the film once as `《蝴蝶之卵》（The Butterfly's Egg）` and use `《蝴蝶之卵》` afterward.

- [ ] **Step 5: Add actual-snapshot smoke tests**

Add to `tests/test_transform.py`:

```python
@pytest.mark.parametrize(
    (
        "slug",
        "expected_text",
        "expected_styles",
        "expected_images",
        "expected_tables",
        "expected_collapsibles",
    ),
    [
        ("scp-4846", "特殊收容措施", 3, 10, 0, 1),
        ("scp-8304", "《蝴蝶之卵》", 4, 0, 1, 1),
    ],
)
def test_featured_translation_snapshot_preserves_source_layout(
    slug: str,
    expected_text: str,
    expected_styles: int,
    expected_images: int,
    expected_tables: int,
    expected_collapsibles: int,
):
    path = Path("translations/featured") / f"{slug}.zh-CN.html"
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    content = soup.select_one("#page-content")
    assert content is not None
    assert expected_text in content.get_text(" ", strip=True)
    assert len(soup.find_all("style")) == expected_styles
    assert len(content.find_all("img")) == expected_images
    assert len(content.find_all("table")) == expected_tables
    assert len(content.select(".collapsible-block")) == expected_collapsibles
    assert soup.find("script") is None
    assert soup.select_one("#side-bar") is None
    assert soup.select_one("#header") is None
    assert soup.select_one(".page-options-bottom") is None
```

- [ ] **Step 6: Compare each translated structure against its source skeleton**

Run:

```powershell
@'
from pathlib import Path
from bs4 import BeautifulSoup
from scp_epub.page_fallbacks import snapshot_layout_signature

for slug in ("scp-4846", "scp-8304"):
    source = Path(f"data/raw/pages/fallback-source-{slug}.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(source, "html.parser")
    minimal = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
    from copy import copy
    for style in soup.find_all("style"):
        minimal.head.append(copy(style))
    minimal.body.append(copy(soup.select_one("#page-content")))
    translated = Path(f"translations/featured/{slug}.zh-CN.html").read_text(encoding="utf-8")
    source_signature = snapshot_layout_signature(str(minimal))
    translated_signature = snapshot_layout_signature(translated)
    print(slug, source_signature, translated_signature)
    if source_signature != translated_signature:
        raise SystemExit(f"layout changed for {slug}")
'@ | & $python -
```

Expected: equal hashes for each page.

- [ ] **Step 7: Run snapshot smoke tests and commit**

```powershell
pytest -q tests/test_transform.py -k featured_translation_snapshot
git add translations/featured/scp-4846.zh-CN.html translations/featured/scp-8304.zh-CN.html tests/test_transform.py
git commit -m "content: translate featured SCP-4846 and SCP-8304"
```

### Task 6: Create the SCP-8274 and SCP-7875 Chinese snapshots

**Files:**
- Create: `translations/featured/scp-8274.zh-CN.html`
- Create: `translations/featured/scp-7875.zh-CN.html`
- Modify: `tests/test_transform.py`

- [ ] **Step 1: Fetch and extract both source pages**

Run with the project Python:

```powershell
$python = Join-Path (Join-Path $env:TEMP 'scp-story-build-venv') 'Scripts\python.exe'
@'
from pathlib import Path
from scp_epub.cache import CacheStore
from scp_epub.fetcher import Fetcher

fetcher = Fetcher(CacheStore(Path("data/raw")), retry_count=3, request_timeout_seconds=60)
for slug, url in {
    "fallback-source-scp-8274": "https://scp-wiki.wikidot.com/scp-8274",
    "fallback-source-scp-7875": "https://scp-wiki.wikidot.com/scp-7875",
}.items():
    result = fetcher.fetch_page(slug, url, force=True)
    print(result.path)
'@ | & $python -
```

Extract the source `<style>` elements and exact `#page-content` subtrees:

```powershell
@'
from copy import copy
from pathlib import Path
from bs4 import BeautifulSoup

for slug in ("scp-8274", "scp-7875"):
    source = Path(f"data/raw/pages/fallback-source-{slug}.html")
    soup = BeautifulSoup(source.read_text(encoding="utf-8"), "html.parser")
    page_content = soup.select_one("#page-content")
    if page_content is None:
        raise SystemExit(f"missing #page-content in {source}")
    output = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
    for style in soup.find_all("style"):
        output.head.append(copy(style))
    output.body.append(copy(page_content))
    target = Path(f"translations/featured/{slug}.zh-CN.html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(output), encoding="utf-8")
    print(target)
'@ | & $python -
```

Expected snapshot paths:

```text
translations/featured/scp-8274.zh-CN.html
translations/featured/scp-7875.zh-CN.html
```

- [ ] **Step 2: Translate SCP-8274 with interactive presentation intact**

Add this exact comment before `<html>`:

```html
<!-- translated-source: https://scp-wiki.wikidot.com/scp-8274; source-language: en -->
```

Translate every visible text node and human-readable attribute. Preserve 13 `<style>` blocks, 11 images, one collapsible block, one footnote container, the alert panels, and all custom classes/data attributes. Required Chinese markers:

```text
欢迎回来，Talum博士
全站警报
特殊收容措施
描述
```

Use the directory title `SCP-8274 - 帝王蝶` and translate “The Monarch Butterfly” as `帝王蝶` consistently.

- [ ] **Step 3: Translate SCP-7875 with tabs and collapsibles intact**

Add this exact comment before `<html>`:

```html
<!-- translated-source: https://scp-wiki.wikidot.com/scp-7875; source-language: en -->
```

Translate every visible text node and human-readable attribute. Preserve 11 `<style>` blocks, two tables, five collapsible blocks, two `.yui-navset` tab views, one image, one footnote container, classification banners, and access-warning layout. Required Chinese markers:

```text
警告：以下文件为4/7875级机密
任何未经4/7875级授权访问此文件的尝试都将被记录
特殊收容措施
描述
```

Use the directory title `SCP-7875 - 患上正常症` and translate the idiomatic title consistently as `患上正常症`.

- [ ] **Step 4: Extend snapshot smoke-test cases**

Add these cases to the existing parametrization:

```python
("scp-8274", "欢迎回来，Talum博士", 13, 11, 0, 1),
("scp-7875", "警告：以下文件为4/7875级机密", 11, 1, 2, 5),
```

Add a dedicated raw-snapshot assertion for the two tab views:

```python
def test_scp_7875_translation_snapshot_preserves_both_tab_views():
    soup = BeautifulSoup(
        Path("translations/featured/scp-7875.zh-CN.html").read_text(encoding="utf-8"),
        "html.parser",
    )
    assert len(soup.select("#page-content .yui-navset")) == 2
```

- [ ] **Step 5: Compare source and translated structure signatures**

Run:

```powershell
@'
from copy import copy
from pathlib import Path
from bs4 import BeautifulSoup
from scp_epub.page_fallbacks import snapshot_layout_signature

for slug in ("scp-8274", "scp-7875"):
    source = Path(f"data/raw/pages/fallback-source-{slug}.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(source, "html.parser")
    minimal = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
    for style in soup.find_all("style"):
        minimal.head.append(copy(style))
    page_content = soup.select_one("#page-content")
    if page_content is None:
        raise SystemExit(f"missing #page-content for {slug}")
    minimal.body.append(copy(page_content))
    translated = Path(f"translations/featured/{slug}.zh-CN.html").read_text(encoding="utf-8")
    source_signature = snapshot_layout_signature(str(minimal))
    translated_signature = snapshot_layout_signature(translated)
    print(slug, source_signature, translated_signature)
    if source_signature != translated_signature:
        raise SystemExit(f"layout changed for {slug}")
'@ | & $python -
```

Expected: equal source and translated hashes for both pages.

- [ ] **Step 6: Run focused tests and commit**

```powershell
pytest -q tests/test_transform.py -k "featured_translation_snapshot or scp_7875_translation_snapshot"
git add translations/featured/scp-8274.zh-CN.html translations/featured/scp-7875.zh-CN.html tests/test_transform.py
git commit -m "content: translate featured SCP-8274 and SCP-7875"
```

### Task 7: Create the Yamizushi File No.233 Chinese snapshot

**Files:**
- Create: `translations/featured/yamizushi-file-no233.zh-CN.html`
- Modify: `tests/test_transform.py`

- [ ] **Step 1: Fetch and extract the Japanese source page**

Run with the project Python:

```powershell
$python = Join-Path (Join-Path $env:TEMP 'scp-story-build-venv') 'Scripts\python.exe'
@'
from pathlib import Path
from scp_epub.cache import CacheStore
from scp_epub.fetcher import Fetcher

fetcher = Fetcher(CacheStore(Path("data/raw")), retry_count=3, request_timeout_seconds=60)
result = fetcher.fetch_page(
    "fallback-source-yamizushi-file-no233",
    "http://scp-jp.wikidot.com/yamizushi-file-no233",
    force=True,
)
print(result.path)
'@ | & $python -
```

Extract the source `<style>` elements and exact `#page-content` subtree:

```powershell
@'
from copy import copy
from pathlib import Path
from bs4 import BeautifulSoup

slug = "yamizushi-file-no233"
source = Path(f"data/raw/pages/fallback-source-{slug}.html")
soup = BeautifulSoup(source.read_text(encoding="utf-8"), "html.parser")
page_content = soup.select_one("#page-content")
if page_content is None:
    raise SystemExit(f"missing #page-content in {source}")
output = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
for style in soup.find_all("style"):
    output.head.append(copy(style))
output.body.append(copy(page_content))
target = Path(f"translations/featured/{slug}.zh-CN.html")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(str(output), encoding="utf-8")
print(target)
'@ | & $python -
```

Expected: HTTP 200 and a snapshot containing eight `<style>` elements, six images, and one footnote container.

- [ ] **Step 2: Translate the complete Japanese page**

Add this exact comment before `<html>`:

```html
<!-- translated-source: http://scp-jp.wikidot.com/yamizushi-file-no233; source-language: ja -->
```

Edit `translations/featured/yamizushi-file-no233.zh-CN.html`. Translate all visible Japanese text, image captions, footnotes, credit labels, and human-readable attributes. Preserve all Dark Sushi terminology, file number `No.233`, six image URLs, page-specific classes, styles, and the credit section. Use these fixed translations:

```text
闇寿司ファイル → 暗寿司档案
簡体字巻 → 简体字卷
クレジット → 致谢
```

The directory and page title is `暗寿司档案 No.233「简体字卷」`.

- [ ] **Step 3: Add the Japanese snapshot smoke-test case**

Add:

```python
("yamizushi-file-no233", "致谢", 8, 6, 0, 0),
```

Add a footnote/credit assertion:

```python
def test_yamizushi_translation_snapshot_preserves_credit_and_footnotes():
    soup = BeautifulSoup(
        Path("translations/featured/yamizushi-file-no233.zh-CN.html").read_text(encoding="utf-8"),
        "html.parser",
    )
    content = soup.select_one("#page-content")
    assert content is not None
    assert "致谢" in content.get_text(" ", strip=True)
    assert len(content.select(".footnotes-footer")) == 1
```

- [ ] **Step 4: Compare the Japanese source and Chinese snapshot structure signatures**

Run:

```powershell
@'
from copy import copy
from pathlib import Path
from bs4 import BeautifulSoup
from scp_epub.page_fallbacks import snapshot_layout_signature

slug = "yamizushi-file-no233"
source = Path(f"data/raw/pages/fallback-source-{slug}.html").read_text(encoding="utf-8")
soup = BeautifulSoup(source, "html.parser")
minimal = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
for style in soup.find_all("style"):
    minimal.head.append(copy(style))
page_content = soup.select_one("#page-content")
if page_content is None:
    raise SystemExit(f"missing #page-content for {slug}")
minimal.body.append(copy(page_content))
translated = Path(f"translations/featured/{slug}.zh-CN.html").read_text(encoding="utf-8")
source_signature = snapshot_layout_signature(str(minimal))
translated_signature = snapshot_layout_signature(translated)
print(slug, source_signature, translated_signature)
if source_signature != translated_signature:
    raise SystemExit(f"layout changed for {slug}")
'@ | & $python -
```

Expected: identical source and translated signatures.

- [ ] **Step 5: Run focused tests and commit**

```powershell
pytest -q tests/test_transform.py -k "featured_translation_snapshot or yamizushi_translation_snapshot"
git add translations/featured/yamizushi-file-no233.zh-CN.html tests/test_transform.py
git commit -m "content: translate featured Yamizushi file 233"
```

### Task 8: Declare the five fallbacks and verify real snapshot integration

**Files:**
- Modify: `config/featured-scp.yaml:1-132`
- Modify: `tests/test_config.py:100-245`
- Modify: `tests/test_transform.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Compute final snapshot signatures**

Run:

```powershell
$python = Join-Path (Join-Path $env:TEMP 'scp-story-build-venv') 'Scripts\python.exe'
@'
from pathlib import Path
from scp_epub.page_fallbacks import snapshot_layout_signature

for path in sorted(Path("translations/featured").glob("*.zh-CN.html")):
    print(path.stem.removesuffix(".zh-CN"), snapshot_layout_signature(path.read_text(encoding="utf-8")))
'@ | & $python -
```

Expected: five slug/signature lines, each with a 64-character lowercase hex digest.

- [ ] **Step 2: Emit the exact YAML block with computed signatures**

Run this command; it prints a complete `page_fallbacks` block containing the real digests from Step 1:

```powershell
@'
from pathlib import Path
from scp_epub.page_fallbacks import snapshot_layout_signature

entries = [
    ("scp-4846", "https://scp-wiki.wikidot.com/scp-4846", "en", "SCP-4846 - 友善化石"),
    ("scp-8304", "https://scp-wiki.wikidot.com/scp-8304", "en", "SCP-8304 - 现代安慰"),
    ("scp-8274", "https://scp-wiki.wikidot.com/scp-8274", "en", "SCP-8274 - 帝王蝶"),
    ("scp-7875", "https://scp-wiki.wikidot.com/scp-7875", "en", "SCP-7875 - 患上正常症"),
    (
        "yamizushi-file-no233",
        "http://scp-jp.wikidot.com/yamizushi-file-no233",
        "ja",
        "暗寿司档案 No.233「简体字卷」",
    ),
]
print("page_fallbacks:")
for slug, source_url, language, title in entries:
    path = Path("translations/featured") / f"{slug}.zh-CN.html"
    signature = snapshot_layout_signature(path.read_text(encoding="utf-8"))
    print(f"  {slug}:")
    print(f"    source_url: {source_url}")
    print(f"    source_language: {language}")
    print(f"    translated_title: {title}")
    print(f"    snapshot_path: {path.as_posix()}")
    print(f"    layout_signature: {signature}")
'@ | & $python -
```

Expected: a complete block with five concrete 64-character signatures and no instructional markers.

- [ ] **Step 3: Add the emitted fallback block to Featured config**

Use `apply_patch` to insert the emitted block verbatim before `page_overrides` in `config/featured-scp.yaml`. Re-run the command after patching and compare every emitted line to the YAML before proceeding.

- [ ] **Step 4: Add Featured configuration assertions**

Extend `test_featured_scp_config_uses_archive_mode_and_title_indexes` or add a focused test:

```python
def test_featured_scp_config_declares_translated_page_fallbacks():
    config = load_config(Path("config/featured-scp.yaml"))

    assert list(config.page_fallbacks) == [
        "scp-4846",
        "scp-8304",
        "scp-8274",
        "scp-7875",
        "yamizushi-file-no233",
    ]
    assert {
        slug: fallback.source_language
        for slug, fallback in config.page_fallbacks.items()
    } == {
        "scp-4846": "en",
        "scp-8304": "en",
        "scp-8274": "en",
        "scp-7875": "en",
        "yamizushi-file-no233": "ja",
    }
    assert all(fallback.snapshot_path.is_file() for fallback in config.page_fallbacks.values())
```

- [ ] **Step 5: Test every configured signature and transformed source base**

Add:

```python
from scp_epub.config import load_config
from scp_epub.page_fallbacks import snapshot_layout_signature


def test_featured_fallback_snapshots_match_configured_layout_signatures():
    config = load_config(Path("config/featured-scp.yaml"))
    for fallback in config.page_fallbacks.values():
        html = fallback.snapshot_path.read_text(encoding="utf-8")
        assert snapshot_layout_signature(html) == fallback.layout_signature


def test_featured_fallback_snapshots_transform_with_foreign_source_urls():
    config = load_config(Path("config/featured-scp.yaml"))
    for slug, fallback in config.page_fallbacks.items():
        entry = PageRef(
            title=fallback.translated_title,
            url=f"https://scp-wiki-cn.wikidot.com/{slug}",
            slug=slug,
            level=1,
            role="scp",
        )
        page = transform_page(
            entry,
            fallback.snapshot_path.read_text(encoding="utf-8"),
            fallback.source_url,
            set(config.page_fallbacks),
        )
        assert page.xhtml
        assert "page-options-bottom" not in page.xhtml
```

- [ ] **Step 6: Run config, snapshot, transform, and pipeline tests**

Run:

```powershell
pytest -q tests/test_config.py tests/test_page_fallbacks.py tests/test_transform.py tests/test_pipeline.py tests/test_epub.py
```

Expected: PASS.

- [ ] **Step 7: Commit Featured integration**

```powershell
git add config/featured-scp.yaml tests/test_config.py tests/test_transform.py tests/test_pipeline.py tests/test_epub.py
git commit -m "feat: enable featured translation fallbacks"
```

### Task 9: Run full verification and rebuild the Kindle Featured collection

**Files:**
- Verify only: repository test suite and generated ignored outputs

- [ ] **Step 1: Run the complete test suite**

```powershell
pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 2: Remove stale cached Chinese 404 entries for the five slugs**

The cache stores successful pages only, so normally no page HTML exists for these 404s. Verify rather than deleting broadly:

```powershell
Get-ChildItem data\raw\pages -File | Where-Object {
  $_.BaseName -in @('scp-4846','scp-8304','scp-8274','scp-7875','yamizushi-file-no233')
} | Select-Object FullName,Length,LastWriteTime
```

If a listed file is a previously cached non-404 Chinese page, keep it because the primary-source-first rule intentionally prefers it. Do not delete valid HTML merely to force fallback testing.

- [ ] **Step 3: Build the normal Featured EPUB**

```powershell
$python = Join-Path (Join-Path $env:TEMP 'scp-story-build-venv') 'Scripts\python.exe'
& $python -m scp_epub --config config/featured-scp.yaml build --volume featured
```

Expected:

```text
Wrote C:\Users\Administrator\Documents\SCP-Story\output\epub\SCP基金会档案精选.epub
```

- [ ] **Step 4: Inspect the normal report**

```powershell
$report = Get-Content -Raw -Encoding UTF8 'output\reports\SCP基金会档案精选-report.json' | ConvertFrom-Json
$report.fallback_pages | Select-Object slug,title,source_url,source_language,snapshot_path
$report.missing_pages | Select-Object slug,title,url,reason
```

Expected: `fallback_pages` contains exactly the five configured slugs in manifest order; `missing_pages` contains none of them.

- [ ] **Step 5: Build the Kindle Featured EPUB and AZW3**

```powershell
& $python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle
```

Expected:

```text
Wrote C:\Users\Administrator\Documents\SCP-Story\output\epub\SCP基金会档案精选-Kindle.epub
Wrote C:\Users\Administrator\Documents\SCP-Story\output\azw3\SCP基金会档案精选-Kindle.azw3
```

- [ ] **Step 6: Verify report membership, EPUB integrity, and Chinese page text**

```powershell
@'
import json
import zipfile
from pathlib import Path

report = json.loads(Path('output/reports/SCP基金会档案精选-Kindle-report.json').read_text(encoding='utf-8'))
expected = {'scp-4846','scp-8304','scp-8274','scp-7875','yamizushi-file-no233'}
fallback_slugs = {item['slug'] for item in report['fallback_pages']}
missing_slugs = {item['slug'] for item in report['missing_pages']}
assert fallback_slugs == expected
assert not expected & missing_slugs

epub = Path('output/epub/SCP基金会档案精选-Kindle.epub')
with zipfile.ZipFile(epub) as archive:
    assert archive.testzip() is None
    text = '\n'.join(
        archive.read(name).decode('utf-8', 'replace')
        for name in archive.namelist()
        if name.endswith('.xhtml')
    )
for marker in ('友善化石','现代安慰','帝王蝶','患上正常症','暗寿司档案'):
    assert marker in text, marker
print('verified fallback pages:', sorted(fallback_slugs))
'@ | & $python -
```

Expected: prints all five fallback slugs and exits 0.

- [ ] **Step 7: Verify Calibre metadata and worktree state**

```powershell
& 'C:\Program Files\Calibre2\ebook-meta.exe' 'output\epub\SCP基金会档案精选-Kindle.epub'
& 'C:\Program Files\Calibre2\ebook-meta.exe' 'output\azw3\SCP基金会档案精选-Kindle.azw3'
git status --short --branch
```

Expected: both books report title `SCP基金会档案精选`, author `SCP基金会`, language `zho`; Git shows no uncommitted source changes.

### Task 10: Final code review and handoff

**Files:**
- Review: all commits made by Tasks 1-8

- [ ] **Step 1: Review the complete diff against the approved spec**

```powershell
git diff e18ed3c..HEAD --stat
git diff e18ed3c..HEAD -- src/scp_epub config tests translations
```

Check explicitly:

- primary Chinese pages still win when available;
- no online translation service was added;
- no raw downloaded pages under `data/raw` are tracked;
- non-fallback configs omit `fallback_pages`;
- five snapshots contain no scripts and preserve their source structures;
- Kindle and non-Kindle paths share the same fallback behavior.

- [ ] **Step 2: Run final verification after review fixes**

```powershell
pytest -q
git status --short --branch
```

Expected: all tests pass; worktree is clean.

- [ ] **Step 3: Prepare the completion summary**

Report:

- implementation commits;
- tests and build commands run;
- generated EPUB, AZW3, and report paths;
- five `fallback_pages` entries;
- any remaining `missing_pages` or `missing_assets` unrelated to these five pages.
