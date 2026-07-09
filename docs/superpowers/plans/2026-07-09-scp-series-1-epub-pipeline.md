# SCP Series 1 EPUB Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable Python pipeline that generates the first sample EPUB volume for `SCP-001` through `SCP-099` from the Chinese SCP Wiki Tales Edition index.

**Architecture:** The pipeline is index-driven: parse the Tales Edition index into a manifest, inject `SCP-001` chronological proposals, fetch and cache pages/assets in the workspace, transform Wikidot HTML into EPUB-friendly XHTML, then package an EPUB plus a JSON validation report. Static HTTP is the default fetch path, with a lazy Playwright fallback available for pages that need browser-rendered正文.

**Tech Stack:** Python 3.11+, `httpx`, `beautifulsoup4`, `lxml`, `PyYAML`, `ebooklib`, optional `playwright`, `pytest`.

---

## File Structure

- Create: `pyproject.toml` - package metadata, runtime dependencies, pytest config.
- Create: `config/series-1.yaml` - reusable Series 1 source and volume configuration.
- Create: `src/scp_epub/__init__.py` - package marker and version.
- Create: `src/scp_epub/__main__.py` - `python -m scp_epub` entrypoint.
- Create: `src/scp_epub/cli.py` - argparse commands for `index`, `fetch`, `clean`, and `build`.
- Create: `src/scp_epub/models.py` - dataclasses shared by parser, fetcher, transformer, packager, and reports.
- Create: `src/scp_epub/config.py` - YAML loading and validation.
- Create: `src/scp_epub/urls.py` - URL normalization, slug extraction, safe file naming.
- Create: `src/scp_epub/cache.py` - workspace cache paths, raw page/asset reads and writes, sidecar metadata.
- Create: `src/scp_epub/indexer.py` - Tales Edition index parsing and nested list manifest extraction.
- Create: `src/scp_epub/scp001.py` - chronological proposal extraction from the `SCP-001` tab view.
- Create: `src/scp_epub/manifest.py` - merge index entries with `SCP-001` proposals and de-duplicate chapter targets.
- Create: `src/scp_epub/fetcher.py` - HTTP download, cache reuse, retry/backoff, asset fetching.
- Create: `src/scp_epub/browser.py` - lazy Playwright fallback wrapper.
- Create: `src/scp_epub/transformer.py` - `#page-content` extraction, collapsible expansion, tab conversion, link/image rewriting.
- Create: `src/scp_epub/packager.py` - EPUB creation with local CSS/assets and navigation.
- Create: `src/scp_epub/pipeline.py` - orchestration for each CLI command.
- Create: `src/scp_epub/report.py` - report counters and JSON serialization.
- Create: `src/scp_epub/styles/ebook.css` - EPUB-compatible base stylesheet.
- Create: `tests/fixtures/index_sample.html` - minimal nested Tales Edition fixture.
- Create: `tests/fixtures/scp001_sample.html` - minimal tabbed `SCP-001` fixture.
- Create: `tests/fixtures/page_sample.html` - minimal page正文 fixture.
- Create: `tests/test_cli.py`
- Create: `tests/test_config.py`
- Create: `tests/test_urls_cache.py`
- Create: `tests/test_indexer.py`
- Create: `tests/test_scp001.py`
- Create: `tests/test_manifest.py`
- Create: `tests/test_fetcher.py`
- Create: `tests/test_transformer.py`
- Create: `tests/test_packager.py`
- Create: `tests/test_pipeline.py`
- Modify: `.gitignore` if extra generated directories appear during implementation.

## Task 1: Project Scaffold And CLI Shell

**Files:**
- Create: `pyproject.toml`
- Create: `config/series-1.yaml`
- Create: `src/scp_epub/__init__.py`
- Create: `src/scp_epub/__main__.py`
- Create: `src/scp_epub/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli.py`:

```python
from scp_epub.cli import build_parser, main


def test_parser_exposes_expected_commands():
    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    assert sorted(choices) == ["build", "clean", "fetch", "index"]


def test_help_returns_success(capsys):
    result = main(["--help"])
    captured = capsys.readouterr()
    assert result == 0
    assert "SCP EPUB pipeline" in captured.out
```

- [ ] **Step 2: Run the CLI tests and verify failure**

Run: `python -m pytest tests/test_cli.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'scp_epub'`.

- [ ] **Step 3: Create package scaffold**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "scp-story-epub"
version = "0.1.0"
description = "Build SCP Wiki Tales Edition EPUB volumes."
requires-python = ">=3.11"
dependencies = [
  "beautifulsoup4>=4.12",
  "ebooklib>=0.18",
  "httpx>=0.27",
  "lxml>=5.2",
  "PyYAML>=6.0",
]

[project.optional-dependencies]
browser = ["playwright>=1.44"]
dev = ["pytest>=8.2"]

[project.scripts]
scp-epub = "scp_epub.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
scp_epub = ["styles/*.css"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

Create `config/series-1.yaml`:

```yaml
series_id: scp-series-1
title: SCP Series 1 Tales Edition
language: zh-CN
creator: SCP Wiki CN
base_url: https://scp-wiki-cn.wikidot.com
index_path: /scp-series-1-tales-edition
scp001_path: /scp-001
cache_dir: data/raw
manifest_dir: data/manifests
processed_dir: data/processed
output_dir: output
request_delay_seconds: 0.5
retry_count: 3
volumes:
  "001-099":
    start: 1
    end: 99
    title: SCP Series 1 Tales Edition 001-099
    output_slug: scp-series-1-001-099-tales
```

Create `src/scp_epub/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `src/scp_epub/__main__.py`:

```python
from .cli import main


raise SystemExit(main())
```

Create `src/scp_epub/cli.py`:

```python
from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SCP EPUB pipeline")
    parser.add_argument("--config", default="config/series-1.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("index", "fetch", "clean", "build"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--volume", default="001-099")
        subparser.add_argument("--refresh", action="store_true")
        subparser.add_argument("--missing-only", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    if argv == ["--help"]:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    from .pipeline import run_command

    run_command(args)
    return 0
```

- [ ] **Step 4: Run the CLI tests and verify pass**

Run: `python -m pytest tests/test_cli.py -q`

Expected: PASS with `2 passed`.

- [ ] **Step 5: Commit scaffold**

Run:

```bash
git add pyproject.toml config/series-1.yaml src/scp_epub tests/test_cli.py
git commit -m "feat: scaffold scp epub cli"
```

Expected: commit succeeds.

## Task 2: Shared Models And Config Loading

**Files:**
- Create: `src/scp_epub/models.py`
- Create: `src/scp_epub/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_config.py`:

```python
from pathlib import Path

from scp_epub.config import load_config


def test_load_config_builds_absolute_urls(tmp_path: Path):
    config_path = tmp_path / "series.yaml"
    config_path.write_text(
        """
series_id: scp-series-1
title: Test Series
language: zh-CN
creator: Test Creator
base_url: https://example.test
index_path: /index
scp001_path: /scp-001
cache_dir: data/raw
manifest_dir: data/manifests
processed_dir: data/processed
output_dir: output
request_delay_seconds: 0.1
retry_count: 2
volumes:
  "001-099":
    start: 1
    end: 99
    title: Volume Title
    output_slug: volume-slug
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.index_url == "https://example.test/index"
    assert config.scp001_url == "https://example.test/scp-001"
    assert config.volumes["001-099"].start == 1
    assert config.workspace == tmp_path


def test_load_config_rejects_missing_volume(tmp_path: Path):
    config_path = tmp_path / "series.yaml"
    config_path.write_text("series_id: bad\n", encoding="utf-8")

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "volumes" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run config tests and verify failure**

Run: `python -m pytest tests/test_config.py -q`

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `scp_epub.config`.

- [ ] **Step 3: Implement models and config loader**

Create `src/scp_epub/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class VolumeSpec:
    key: str
    start: int
    end: int
    title: str
    output_slug: str


@dataclass(frozen=True)
class AppConfig:
    workspace: Path
    series_id: str
    title: str
    language: str
    creator: str
    base_url: str
    index_path: str
    scp001_path: str
    cache_dir: Path
    manifest_dir: Path
    processed_dir: Path
    output_dir: Path
    request_delay_seconds: float
    retry_count: int
    volumes: dict[str, VolumeSpec]

    @property
    def index_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.index_path.lstrip('/')}"

    @property
    def scp001_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.scp001_path.lstrip('/')}"


@dataclass(frozen=True)
class PageRef:
    title: str
    url: str
    slug: str
    level: int
    role: str
    parent_slug: str | None = None
    source: str = "index"
    children: tuple["PageRef", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FetchResult:
    url: str
    path: Path
    metadata_path: Path
    from_cache: bool
    status_code: int
    content_type: str


@dataclass(frozen=True)
class ProcessedPage:
    entry: PageRef
    xhtml: str
    asset_urls: tuple[str, ...]
    internal_links: tuple[str, ...]
    external_links: tuple[str, ...]
```

Create `src/scp_epub/config.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import AppConfig, VolumeSpec


REQUIRED_TOP_LEVEL = {
    "series_id",
    "title",
    "language",
    "creator",
    "base_url",
    "index_path",
    "scp001_path",
    "cache_dir",
    "manifest_dir",
    "processed_dir",
    "output_dir",
    "request_delay_seconds",
    "retry_count",
    "volumes",
}


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    missing = sorted(REQUIRED_TOP_LEVEL - set(data))
    if missing:
        raise ValueError(f"Config missing required keys: {', '.join(missing)}")

    volumes = {
        key: VolumeSpec(
            key=key,
            start=int(value["start"]),
            end=int(value["end"]),
            title=str(value["title"]),
            output_slug=str(value["output_slug"]),
        )
        for key, value in _mapping(data["volumes"]).items()
    }
    if not volumes:
        raise ValueError("Config must define at least one volume")

    workspace = config_path.parent.parent if config_path.parent.name == "config" else config_path.parent

    return AppConfig(
        workspace=workspace,
        series_id=str(data["series_id"]),
        title=str(data["title"]),
        language=str(data["language"]),
        creator=str(data["creator"]),
        base_url=str(data["base_url"]).rstrip("/"),
        index_path=str(data["index_path"]),
        scp001_path=str(data["scp001_path"]),
        cache_dir=workspace / str(data["cache_dir"]),
        manifest_dir=workspace / str(data["manifest_dir"]),
        processed_dir=workspace / str(data["processed_dir"]),
        output_dir=workspace / str(data["output_dir"]),
        request_delay_seconds=float(data["request_delay_seconds"]),
        retry_count=int(data["retry_count"]),
        volumes=volumes,
    )


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("volumes must be a mapping")
    return value
```

- [ ] **Step 4: Run config tests and verify pass**

Run: `python -m pytest tests/test_config.py -q`

Expected: PASS with `2 passed`.

- [ ] **Step 5: Commit config work**

Run:

```bash
git add src/scp_epub/models.py src/scp_epub/config.py tests/test_config.py
git commit -m "feat: add config loading"
```

Expected: commit succeeds.

## Task 3: URL And Workspace Cache Utilities

**Files:**
- Create: `src/scp_epub/urls.py`
- Create: `src/scp_epub/cache.py`
- Test: `tests/test_urls_cache.py`

- [ ] **Step 1: Write failing URL and cache tests**

Create `tests/test_urls_cache.py`:

```python
import json
from pathlib import Path

from scp_epub.cache import CacheStore
from scp_epub.urls import normalize_url, safe_filename, slug_from_url


def test_normalize_url_handles_relative_and_fragments():
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "/scp-002#x") == "https://scp-wiki-cn.wikidot.com/scp-002#x"
    assert normalize_url("https://scp-wiki-cn.wikidot.com", "http://example.test/a") == "http://example.test/a"


def test_slug_from_url_keeps_old_namespace():
    assert slug_from_url("https://scp-wiki-cn.wikidot.com/old:kalinins-proposal") == "old:kalinins-proposal"


def test_safe_filename_removes_windows_reserved_characters():
    assert safe_filename("old:kalinins-proposal") == "old_kalinins-proposal"


def test_cache_store_writes_page_and_metadata(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    page_path, meta_path = cache.write_page("scp-002", "https://example.test/scp-002", "<html></html>", 200, "text/html")

    assert page_path.read_text(encoding="utf-8") == "<html></html>"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["url"] == "https://example.test/scp-002"
    assert metadata["status_code"] == 200
    assert len(metadata["sha256"]) == 64
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_urls_cache.py -q`

Expected: FAIL with missing `scp_epub.cache` or `scp_epub.urls`.

- [ ] **Step 3: Implement URL helpers and cache store**

Create `src/scp_epub/urls.py`:

```python
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse


WINDOWS_RESERVED = re.compile(r'[<>:"/\\\\|?*]+')


def normalize_url(base_url: str, href: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", href)


def slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.strip("/")
    return slug or "index"


def safe_filename(value: str) -> str:
    cleaned = WINDOWS_RESERVED.sub("_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned.strip("._ ") or "item"
```

Create `src/scp_epub/cache.py`:

```python
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .urls import safe_filename


class CacheStore:
    def __init__(self, root: Path):
        self.root = root
        self.pages_dir = root / "pages"
        self.assets_dir = root / "assets"

    def page_path(self, slug: str) -> Path:
        return self.pages_dir / f"{safe_filename(slug)}.html"

    def page_metadata_path(self, slug: str) -> Path:
        return self.pages_dir / f"{safe_filename(slug)}.json"

    def has_page(self, slug: str) -> bool:
        return self.page_path(slug).exists()

    def read_page(self, slug: str) -> str:
        return self.page_path(slug).read_text(encoding="utf-8")

    def write_page(self, slug: str, url: str, text: str, status_code: int, content_type: str) -> tuple[Path, Path]:
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        page_path = self.page_path(slug)
        meta_path = self.page_metadata_path(slug)
        page_path.write_text(text, encoding="utf-8")
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "status_code": status_code,
                    "content_type": content_type,
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return page_path, meta_path

    def asset_path(self, url: str, content_type: str = "") -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        suffix = _suffix_from_content_type(content_type) or Path(url.split("?")[0]).suffix or ".bin"
        return self.assets_dir / f"{digest}{suffix}"

    def write_asset(self, url: str, content: bytes, status_code: int, content_type: str) -> tuple[Path, Path]:
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        asset_path = self.asset_path(url, content_type)
        meta_path = asset_path.with_suffix(asset_path.suffix + ".json")
        asset_path.write_bytes(content)
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "status_code": status_code,
                    "content_type": content_type,
                    "sha256": hashlib.sha256(content).hexdigest(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return asset_path, meta_path


def _suffix_from_content_type(content_type: str) -> str:
    content_type = content_type.split(";")[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "text/css": ".css",
        "font/woff": ".woff",
        "font/woff2": ".woff2",
    }.get(content_type, "")
```

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m pytest tests/test_urls_cache.py -q`

Expected: PASS with `4 passed`.

- [ ] **Step 5: Commit URL and cache utilities**

Run:

```bash
git add src/scp_epub/urls.py src/scp_epub/cache.py tests/test_urls_cache.py
git commit -m "feat: add workspace cache utilities"
```

Expected: commit succeeds.

## Task 4: Tales Edition Index Parser

**Files:**
- Create: `src/scp_epub/indexer.py`
- Create: `tests/fixtures/index_sample.html`
- Test: `tests/test_indexer.py`

- [ ] **Step 1: Add fixture and failing parser tests**

Create `tests/fixtures/index_sample.html`:

```html
<html><body>
<div id="side-bar"><a href="/not-content">Ignore Me</a></div>
<div id="page-content">
  <h1 id="toc1"><span>001提案</span></h1>
  <ul>
    <li><a href="/scp-001">SCP-001</a>
      <ul><li><a href="/spc-001">SPC-001</a></li></ul>
    </li>
  </ul>
  <h1 id="toc2"><span>002到099</span></h1>
  <ul>
    <li><a href="/scp-002">SCP-002</a> - Living Room
      <ul><li><a href="/story-002">Story 002</a></li></ul>
    </li>
    <li><a href="/scp-099">SCP-099</a>
      <ul><li><a href="/supplement-099">Supplement 099</a></li></ul>
    </li>
  </ul>
  <h1 id="toc3"><span>100到199</span></h1>
  <ul><li><a href="/scp-100">SCP-100</a></li></ul>
</div>
</body></html>
```

Create `tests/test_indexer.py`:

```python
from pathlib import Path

from scp_epub.indexer import parse_tales_index


def test_parse_tales_index_keeps_target_sections_only():
    html = Path("tests/fixtures/index_sample.html").read_text(encoding="utf-8")
    entries = parse_tales_index(html, "https://scp-wiki-cn.wikidot.com", start=1, end=99)

    slugs = [entry.slug for entry in entries]
    assert slugs == ["scp-001", "spc-001", "scp-002", "story-002", "scp-099", "supplement-099"]
    assert "scp-100" not in slugs
    assert "not-content" not in slugs


def test_parse_tales_index_preserves_nested_levels_and_parents():
    html = Path("tests/fixtures/index_sample.html").read_text(encoding="utf-8")
    entries = parse_tales_index(html, "https://scp-wiki-cn.wikidot.com", start=1, end=99)
    by_slug = {entry.slug: entry for entry in entries}

    assert by_slug["scp-002"].level == 1
    assert by_slug["story-002"].level == 2
    assert by_slug["story-002"].parent_slug == "scp-002"
```

- [ ] **Step 2: Run parser tests and verify failure**

Run: `python -m pytest tests/test_indexer.py -q`

Expected: FAIL with `ModuleNotFoundError` for `scp_epub.indexer`.

- [ ] **Step 3: Implement nested-list index parser**

Create `src/scp_epub/indexer.py`:

```python
from __future__ import annotations

import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Tag

from .models import PageRef
from .urls import normalize_url, slug_from_url


SECTION_RANGE_RE = re.compile(r"(?P<start>\d{3}).*?(?P<end>\d{3})")
SCP_RE = re.compile(r"^SCP-(?P<num>\d{3})$")


def parse_tales_index(html: str, base_url: str, start: int, end: int) -> list[PageRef]:
    soup = BeautifulSoup(html, "lxml")
    content = soup.select_one("#page-content")
    if content is None:
        raise ValueError("Index page does not contain #page-content")

    entries: list[PageRef] = []
    for heading in content.find_all(["h1", "h2"], recursive=False):
        title = heading.get_text(" ", strip=True)
        if not _section_matches(title, start, end):
            continue
        for sibling in _section_siblings(heading):
            if sibling.name in {"h1", "h2"}:
                break
            if sibling.name == "ul":
                entries.extend(_parse_ul(sibling, base_url, level=1, parent_slug=None))
    return entries


def _section_matches(title: str, start: int, end: int) -> bool:
    if "001" in title and start <= 1 <= end:
        return True
    match = SECTION_RANGE_RE.search(title)
    if not match:
        return False
    section_start = int(match.group("start"))
    section_end = int(match.group("end"))
    return section_start <= end and start <= section_end


def _section_siblings(heading: Tag) -> Iterable[Tag]:
    for sibling in heading.next_siblings:
        if isinstance(sibling, Tag):
            yield sibling


def _parse_ul(ul: Tag, base_url: str, level: int, parent_slug: str | None) -> list[PageRef]:
    entries: list[PageRef] = []
    for li in ul.find_all("li", recursive=False):
        anchor = li.find("a", href=True, recursive=False) or li.find("a", href=True)
        if anchor is None:
            continue
        href = anchor["href"]
        if href.startswith("javascript:") or href == "#":
            continue
        url = normalize_url(base_url, href)
        slug = slug_from_url(url)
        title = anchor.get_text(" ", strip=True)
        role = "scp" if SCP_RE.match(title) else "related"
        entries.append(PageRef(title=title, url=url, slug=slug, level=level, role=role, parent_slug=parent_slug))
        for child_ul in li.find_all("ul", recursive=False):
            entries.extend(_parse_ul(child_ul, base_url, level + 1, parent_slug=slug))
    return entries
```

- [ ] **Step 4: Run parser tests and verify pass**

Run: `python -m pytest tests/test_indexer.py -q`

Expected: PASS with `2 passed`.

- [ ] **Step 5: Commit index parser**

Run:

```bash
git add src/scp_epub/indexer.py tests/fixtures/index_sample.html tests/test_indexer.py
git commit -m "feat: parse tales edition index"
```

Expected: commit succeeds.

## Task 5: SCP-001 Chronological Proposal Parser

**Files:**
- Create: `src/scp_epub/scp001.py`
- Create: `tests/fixtures/scp001_sample.html`
- Test: `tests/test_scp001.py`

- [ ] **Step 1: Add fixture and failing tests**

Create `tests/fixtures/scp001_sample.html`:

```html
<html><body>
<div id="page-content">
  <div class="yui-navset">
    <ul class="yui-nav">
      <li class="selected"><a href="javascript:;"><em>随机排序</em></a></li>
      <li><a href="javascript:;"><em>按时间顺序展示</em></a></li>
    </ul>
    <div class="yui-content">
      <div><p><a href="/random-proposal">Random</a></p></div>
      <div>
        <p><a href="/jonathan-ball-s-proposal">代号：Jonathan Ball</a></p>
        <p><a href="/dr-gears-s-proposal">代号：Dr. Gears</a></p>
      </div>
    </div>
  </div>
</div>
</body></html>
```

Create `tests/test_scp001.py`:

```python
from pathlib import Path

from scp_epub.scp001 import extract_chronological_proposals


def test_extract_chronological_proposals_uses_chronological_tab():
    html = Path("tests/fixtures/scp001_sample.html").read_text(encoding="utf-8")
    entries = extract_chronological_proposals(html, "https://scp-wiki-cn.wikidot.com")

    assert [entry.slug for entry in entries] == ["jonathan-ball-s-proposal", "dr-gears-s-proposal"]
    assert all(entry.role == "scp001-proposal" for entry in entries)
    assert all(entry.parent_slug == "scp-001" for entry in entries)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_scp001.py -q`

Expected: FAIL with missing `scp_epub.scp001`.

- [ ] **Step 3: Implement chronological parser**

Create `src/scp_epub/scp001.py`:

```python
from __future__ import annotations

from bs4 import BeautifulSoup

from .models import PageRef
from .urls import normalize_url, slug_from_url


def extract_chronological_proposals(html: str, base_url: str) -> list[PageRef]:
    soup = BeautifulSoup(html, "lxml")
    navset = soup.select_one("#page-content .yui-navset")
    if navset is None:
        raise ValueError("SCP-001 page does not contain a tab view")

    labels = [item.get_text(" ", strip=True) for item in navset.select(".yui-nav li")]
    panes = navset.select(".yui-content > div")
    try:
        pane_index = next(index for index, label in enumerate(labels) if "按时间顺序展示" in label)
    except StopIteration as exc:
        raise ValueError("SCP-001 page does not contain the chronological tab") from exc
    if pane_index >= len(panes):
        raise ValueError("SCP-001 chronological tab has no matching content pane")

    entries: list[PageRef] = []
    for anchor in panes[pane_index].find_all("a", href=True):
        href = anchor["href"]
        if href.startswith("javascript:") or href == "#":
            continue
        url = normalize_url(base_url, href)
        slug = slug_from_url(url)
        entries.append(
            PageRef(
                title=anchor.get_text(" ", strip=True),
                url=url,
                slug=slug,
                level=2,
                role="scp001-proposal",
                parent_slug="scp-001",
                source="scp001",
            )
        )
    return entries
```

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m pytest tests/test_scp001.py -q`

Expected: PASS with `1 passed`.

- [ ] **Step 5: Commit SCP-001 parser**

Run:

```bash
git add src/scp_epub/scp001.py tests/fixtures/scp001_sample.html tests/test_scp001.py
git commit -m "feat: parse scp001 chronological proposals"
```

Expected: commit succeeds.

## Task 6: Manifest Merge And De-Duplication

**Files:**
- Create: `src/scp_epub/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write failing manifest tests**

Create `tests/test_manifest.py`:

```python
from scp_epub.manifest import build_volume_manifest
from scp_epub.models import PageRef


def test_build_volume_manifest_inserts_scp001_proposals_after_scp001():
    index_entries = [
        PageRef("SCP-001", "https://example.test/scp-001", "scp-001", 1, "scp"),
        PageRef("SPC-001", "https://example.test/spc-001", "spc-001", 2, "related", "scp-001"),
        PageRef("SCP-002", "https://example.test/scp-002", "scp-002", 1, "scp"),
    ]
    proposals = [
        PageRef("Proposal A", "https://example.test/a", "a", 2, "scp001-proposal", "scp-001", "scp001"),
        PageRef("Proposal B", "https://example.test/b", "b", 2, "scp001-proposal", "scp-001", "scp001"),
    ]

    manifest = build_volume_manifest(index_entries, proposals)

    assert [entry.slug for entry in manifest] == ["scp-001", "a", "b", "spc-001", "scp-002"]


def test_build_volume_manifest_keeps_first_duplicate_target():
    index_entries = [
        PageRef("SCP-001", "https://example.test/scp-001", "scp-001", 1, "scp"),
        PageRef("Story", "https://example.test/story", "story", 2, "related", "scp-001"),
        PageRef("Story Again", "https://example.test/story", "story", 2, "related", "scp-002"),
    ]

    manifest = build_volume_manifest(index_entries, [])

    assert [entry.title for entry in manifest] == ["SCP-001", "Story"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_manifest.py -q`

Expected: FAIL with missing `scp_epub.manifest`.

- [ ] **Step 3: Implement manifest merge**

Create `src/scp_epub/manifest.py`:

```python
from __future__ import annotations

from .models import PageRef


def build_volume_manifest(index_entries: list[PageRef], scp001_proposals: list[PageRef]) -> list[PageRef]:
    merged: list[PageRef] = []
    inserted_proposals = False
    seen: set[str] = set()

    for entry in index_entries:
        if entry.slug not in seen:
            merged.append(entry)
            seen.add(entry.slug)

        if entry.slug == "scp-001" and not inserted_proposals:
            for proposal in scp001_proposals:
                if proposal.slug not in seen:
                    merged.append(proposal)
                    seen.add(proposal.slug)
            inserted_proposals = True

    if not inserted_proposals:
        for proposal in scp001_proposals:
            if proposal.slug not in seen:
                merged.append(proposal)
                seen.add(proposal.slug)

    return merged


def link_map_for_manifest(entries: list[PageRef]) -> dict[str, str]:
    return {entry.slug: f"{entry.slug}.xhtml" for entry in entries}
```

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m pytest tests/test_manifest.py -q`

Expected: PASS with `2 passed`.

- [ ] **Step 5: Commit manifest merge**

Run:

```bash
git add src/scp_epub/manifest.py tests/test_manifest.py
git commit -m "feat: build volume manifest"
```

Expected: commit succeeds.

## Task 7: Fetcher And Browser Fallback

**Files:**
- Create: `src/scp_epub/browser.py`
- Create: `src/scp_epub/fetcher.py`
- Test: `tests/test_fetcher.py`

- [ ] **Step 1: Write failing fetcher tests**

Create `tests/test_fetcher.py`:

```python
from pathlib import Path

import httpx

from scp_epub.cache import CacheStore
from scp_epub.fetcher import Fetcher


def test_fetcher_reuses_cached_page(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    cache.write_page("scp-002", "https://example.test/scp-002", "<html>cached</html>", 200, "text/html")

    fetcher = Fetcher(cache, client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))))
    result = fetcher.fetch_page("https://example.test/scp-002", "scp-002")

    assert result.from_cache is True
    assert result.path.read_text(encoding="utf-8") == "<html>cached</html>"


def test_fetcher_downloads_missing_page(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>network</html>", headers={"content-type": "text/html"})

    cache = CacheStore(tmp_path / "raw")
    fetcher = Fetcher(cache, client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = fetcher.fetch_page("https://example.test/scp-002", "scp-002")

    assert result.from_cache is False
    assert result.status_code == 200
    assert result.path.read_text(encoding="utf-8") == "<html>network</html>"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_fetcher.py -q`

Expected: FAIL with missing `scp_epub.fetcher`.

- [ ] **Step 3: Implement fetcher and lazy browser wrapper**

Create `src/scp_epub/browser.py`:

```python
from __future__ import annotations


def render_page_html(url: str, timeout_ms: int = 30000) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        html = page.content()
        browser.close()
        return html
```

Create `src/scp_epub/fetcher.py`:

```python
from __future__ import annotations

import time

import httpx

from .cache import CacheStore
from .models import FetchResult


class Fetcher:
    def __init__(
        self,
        cache: CacheStore,
        client: httpx.Client | None = None,
        retry_count: int = 3,
        delay_seconds: float = 0.0,
    ):
        self.cache = cache
        self.client = client or httpx.Client(follow_redirects=True, timeout=30)
        self.retry_count = retry_count
        self.delay_seconds = delay_seconds

    def fetch_page(self, url: str, slug: str, refresh: bool = False) -> FetchResult:
        if self.cache.has_page(slug) and not refresh:
            return FetchResult(url, self.cache.page_path(slug), self.cache.page_metadata_path(slug), True, 200, "text/html")

        response = self._get_with_retries(url)
        content_type = response.headers.get("content-type", "text/html")
        page_path, meta_path = self.cache.write_page(slug, url, response.text, response.status_code, content_type)
        return FetchResult(url, page_path, meta_path, False, response.status_code, content_type)

    def fetch_asset(self, url: str, refresh: bool = False) -> tuple[str, bool]:
        response = self._get_with_retries(url)
        content_type = response.headers.get("content-type", "application/octet-stream")
        asset_path = self.cache.asset_path(url, content_type)
        if asset_path.exists() and not refresh:
            return str(asset_path), True
        self.cache.write_asset(url, response.content, response.status_code, content_type)
        return str(asset_path), False

    def _get_with_retries(self, url: str) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.retry_count):
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            try:
                response = self.client.get(url)
                response.raise_for_status()
                return response
            except Exception as exc:
                last_error = exc
                if attempt + 1 == self.retry_count:
                    break
                time.sleep(0.25 * (attempt + 1))
        raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error
```

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m pytest tests/test_fetcher.py -q`

Expected: PASS with `2 passed`.

- [ ] **Step 5: Commit fetcher**

Run:

```bash
git add src/scp_epub/browser.py src/scp_epub/fetcher.py tests/test_fetcher.py
git commit -m "feat: add cached page fetcher"
```

Expected: commit succeeds.

## Task 8: HTML Transformer

**Files:**
- Create: `src/scp_epub/transformer.py`
- Create: `tests/fixtures/page_sample.html`
- Test: `tests/test_transformer.py`

- [ ] **Step 1: Add fixture and failing transformer tests**

Create `tests/fixtures/page_sample.html`:

```html
<html><body>
<div id="side-bar">ignore</div>
<div id="page-content">
  <div id="toc">remove toc</div>
  <p><img src="/local.png" /></p>
  <p><a href="/scp-002">internal</a> <a href="/outside">external</a></p>
  <div class="collapsible-block">
    <div class="collapsible-block-folded"><a href="javascript:;">Document</a></div>
    <div class="collapsible-block-unfolded">
      <div class="collapsible-block-content"><p>Secret text</p></div>
    </div>
  </div>
  <div class="licensebox">
    <div class="collapsible-block"><div class="collapsible-block-content">License</div></div>
  </div>
  <div class="yui-navset">
    <ul class="yui-nav"><li><a><em>Tab A</em></a></li><li><a><em>Tab B</em></a></li></ul>
    <div class="yui-content"><div><p>A body</p></div><div><p>B body</p></div></div>
  </div>
</div>
</body></html>
```

Create `tests/test_transformer.py`:

```python
from pathlib import Path

from scp_epub.models import PageRef
from scp_epub.transformer import transform_page


def test_transform_page_extracts_content_and_rewrites_links():
    html = Path("tests/fixtures/page_sample.html").read_text(encoding="utf-8")
    entry = PageRef("SCP-002", "https://scp-wiki-cn.wikidot.com/scp-002", "scp-002", 1, "scp")
    processed = transform_page(
        html,
        entry,
        "https://scp-wiki-cn.wikidot.com",
        {"scp-002": "scp-002.xhtml"},
        {"https://scp-wiki-cn.wikidot.com/local.png": "images/local.png"},
    )

    assert "side-bar" not in processed.xhtml
    assert "remove toc" not in processed.xhtml
    assert "Secret text" in processed.xhtml
    assert "License" not in processed.xhtml
    assert 'href="scp-002.xhtml"' in processed.xhtml
    assert 'href="https://scp-wiki-cn.wikidot.com/outside"' in processed.xhtml
    assert 'src="images/local.png"' in processed.xhtml
    assert "Tab A" in processed.xhtml
    assert "B body" in processed.xhtml
```

- [ ] **Step 2: Run transformer tests and verify failure**

Run: `python -m pytest tests/test_transformer.py -q`

Expected: FAIL with missing `scp_epub.transformer`.

- [ ] **Step 3: Implement transformer**

Create `src/scp_epub/transformer.py`:

```python
from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from .models import PageRef, ProcessedPage
from .urls import normalize_url, slug_from_url


REMOVE_SELECTORS = [
    "#toc",
    ".licensebox",
    ".page-tags",
    ".rate-box-with-credit-button",
    ".page-options-bottom",
    ".page-watch-options",
    ".footer-wikiwalk-nav",
    "script",
]


def transform_page(
    html: str,
    entry: PageRef,
    base_url: str,
    link_map: dict[str, str],
    asset_map: dict[str, str],
) -> ProcessedPage:
    soup = BeautifulSoup(html, "lxml")
    content = soup.select_one("#page-content")
    if content is None:
        raise ValueError(f"{entry.slug} does not contain #page-content")

    for selector in REMOVE_SELECTORS:
        for node in content.select(selector):
            node.decompose()

    _expand_collapsibles(soup, content)
    _convert_tabs(soup, content)

    asset_urls: list[str] = []
    for image in content.find_all("img", src=True):
        absolute = normalize_url(base_url, image["src"])
        asset_urls.append(absolute)
        image["src"] = asset_map.get(absolute, absolute)

    internal_links: list[str] = []
    external_links: list[str] = []
    for anchor in content.find_all("a", href=True):
        href = anchor["href"]
        if href.startswith("javascript:") or href == "#":
            anchor.unwrap()
            continue
        absolute = normalize_url(base_url, href)
        slug = slug_from_url(absolute)
        if slug in link_map:
            anchor["href"] = link_map[slug]
            internal_links.append(slug)
        else:
            anchor["href"] = absolute
            external_links.append(absolute)

    body_html = "".join(str(child) for child in content.contents)
    xhtml = f'<section id="{entry.slug}" class="scp-page"><h1>{entry.title}</h1>{body_html}</section>'
    return ProcessedPage(entry, xhtml, tuple(dict.fromkeys(asset_urls)), tuple(dict.fromkeys(internal_links)), tuple(dict.fromkeys(external_links)))


def _expand_collapsibles(soup: BeautifulSoup, content: Tag) -> None:
    for block in list(content.select(".collapsible-block")):
        if block.find_parent(class_="licensebox"):
            block.decompose()
            continue
        title_node = block.select_one(".collapsible-block-folded")
        body_node = block.select_one(".collapsible-block-content")
        section = soup.new_tag("section")
        section["class"] = "collapsible-expanded"
        if title_node is not None:
            heading = soup.new_tag("p")
            heading["class"] = "collapsible-title"
            heading.string = title_node.get_text(" ", strip=True)
            section.append(heading)
        if body_node is not None:
            for child in list(body_node.contents):
                section.append(child.extract())
        block.replace_with(section)


def _convert_tabs(soup: BeautifulSoup, content: Tag) -> None:
    for navset in list(content.select(".yui-navset")):
        labels = [item.get_text(" ", strip=True) for item in navset.select(".yui-nav li")]
        panes = navset.select(".yui-content > div")
        wrapper = soup.new_tag("section")
        wrapper["class"] = "tabs-expanded"
        for index, pane in enumerate(panes):
            label = labels[index] if index < len(labels) else f"Tab {index + 1}"
            section = soup.new_tag("section")
            heading = soup.new_tag("h2")
            heading.string = label
            section.append(heading)
            for child in list(pane.contents):
                section.append(child.extract())
            wrapper.append(section)
        navset.replace_with(wrapper)
```

- [ ] **Step 4: Run transformer tests and verify pass**

Run: `python -m pytest tests/test_transformer.py -q`

Expected: PASS with `1 passed`.

- [ ] **Step 5: Commit transformer**

Run:

```bash
git add src/scp_epub/transformer.py tests/fixtures/page_sample.html tests/test_transformer.py
git commit -m "feat: transform wikidot pages"
```

Expected: commit succeeds.

## Task 9: EPUB Packager And Report Writer

**Files:**
- Create: `src/scp_epub/packager.py`
- Create: `src/scp_epub/report.py`
- Create: `src/scp_epub/styles/ebook.css`
- Test: `tests/test_packager.py`

- [ ] **Step 1: Write failing packager tests**

Create `tests/test_packager.py`:

```python
import zipfile
from pathlib import Path

from scp_epub.models import PageRef, ProcessedPage
from scp_epub.packager import write_epub
from scp_epub.report import BuildReport


def test_write_epub_creates_nav_and_chapter(tmp_path: Path):
    entry = PageRef("SCP-002", "https://example.test/scp-002", "scp-002", 1, "scp")
    page = ProcessedPage(entry, "<section><h1>SCP-002</h1><p>Body</p></section>", (), (), ())
    output = tmp_path / "book.epub"

    write_epub(output, "Title", "zh-CN", "Creator", [page], {})

    assert output.exists()
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "EPUB/scp-002.xhtml" in names
    assert "EPUB/nav.xhtml" in names


def test_build_report_writes_json(tmp_path: Path):
    report = BuildReport()
    report.total_manifest_entries = 2
    report.scp001_proposal_count = 1
    path = tmp_path / "report.json"

    report.write(path)

    text = path.read_text(encoding="utf-8")
    assert '"total_manifest_entries": 2' in text
    assert '"scp001_proposal_count": 1' in text
```

- [ ] **Step 2: Run packager tests and verify failure**

Run: `python -m pytest tests/test_packager.py -q`

Expected: FAIL with missing `scp_epub.packager` or `scp_epub.report`.

- [ ] **Step 3: Implement report and EPUB packager**

Create `src/scp_epub/report.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class BuildReport:
    total_manifest_entries: int = 0
    total_epub_chapters: int = 0
    scp001_proposal_count: int = 0
    pages_from_cache: int = 0
    pages_from_network: int = 0
    browser_fallback_pages: list[str] = field(default_factory=list)
    failed_pages: list[str] = field(default_factory=list)
    failed_assets: list[str] = field(default_factory=list)
    images_included: list[str] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    suspicious_links: list[str] = field(default_factory=list)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
```

Create `src/scp_epub/styles/ebook.css`:

```css
body {
  font-family: serif;
  line-height: 1.55;
}

img {
  max-width: 100%;
  height: auto;
}

table {
  border-collapse: collapse;
  max-width: 100%;
}

td,
th {
  border: 1px solid #888;
  padding: 0.25em 0.4em;
}

blockquote {
  border-left: 0.25em solid #999;
  margin-left: 0;
  padding-left: 1em;
}

.collapsible-title {
  font-weight: bold;
}
```

Create `src/scp_epub/packager.py`:

```python
from __future__ import annotations

from pathlib import Path

from ebooklib import epub

from .models import ProcessedPage


def write_epub(
    output_path: Path,
    title: str,
    language: str,
    creator: str,
    pages: list[ProcessedPage],
    assets: dict[str, Path],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    book = epub.EpubBook()
    book.set_identifier(output_path.stem)
    book.set_title(title)
    book.set_language(language)
    book.add_author(creator)

    style = epub.EpubItem(uid="style", file_name="styles/ebook.css", media_type="text/css", content=_load_style())
    book.add_item(style)

    chapters = []
    for page in pages:
        chapter = epub.EpubHtml(title=page.entry.title, file_name=f"{page.entry.slug}.xhtml", lang=language)
        chapter.content = page.xhtml
        chapter.add_item(style)
        book.add_item(chapter)
        chapters.append(chapter)

    for source_url, path in assets.items():
        media_type = _media_type(path)
        item = epub.EpubItem(uid=path.stem, file_name=f"assets/{path.name}", media_type=media_type, content=path.read_bytes())
        book.add_item(item)

    book.toc = tuple(chapters)
    book.spine = ["nav", *chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(output_path), book)
    return output_path


def _load_style() -> str:
    return (Path(__file__).parent / "styles" / "ebook.css").read_text(encoding="utf-8")


def _media_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".css": "text/css",
    }.get(path.suffix.lower(), "application/octet-stream")
```

- [ ] **Step 4: Run packager tests and verify pass**

Run: `python -m pytest tests/test_packager.py -q`

Expected: PASS with `2 passed`.

- [ ] **Step 5: Commit packager**

Run:

```bash
git add src/scp_epub/packager.py src/scp_epub/report.py src/scp_epub/styles/ebook.css tests/test_packager.py
git commit -m "feat: package epub output"
```

Expected: commit succeeds.

## Task 10: Pipeline Orchestration

**Files:**
- Create: `src/scp_epub/pipeline.py`
- Modify: `src/scp_epub/cli.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing pipeline test**

Create `tests/test_pipeline.py`:

```python
from argparse import Namespace
from pathlib import Path

from scp_epub.pipeline import run_command


def test_index_command_writes_manifest(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "series-1.yaml").write_text(
        """
series_id: scp-series-1
title: Test Series
language: zh-CN
creator: Test Creator
base_url: https://example.test
index_path: /index
scp001_path: /scp-001
cache_dir: data/raw
manifest_dir: data/manifests
processed_dir: data/processed
output_dir: output
request_delay_seconds: 0
retry_count: 1
volumes:
  "001-099":
    start: 1
    end: 99
    title: Volume Title
    output_slug: volume-slug
""",
        encoding="utf-8",
    )
    index_html = Path("tests/fixtures/index_sample.html").read_text(encoding="utf-8")
    scp001_html = Path("tests/fixtures/scp001_sample.html").read_text(encoding="utf-8")

    class FakeFetcher:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_page(self, url, slug, refresh=False):
            target = tmp_path / f"{slug}.html"
            target.write_text(index_html if slug == "scp-series-1-tales-edition" else scp001_html, encoding="utf-8")
            return Namespace(path=target, from_cache=False, status_code=200, content_type="text/html", metadata_path=target.with_suffix(".json"))

    monkeypatch.setattr("scp_epub.pipeline.Fetcher", FakeFetcher)
    args = Namespace(command="index", config=str(config_dir / "series-1.yaml"), volume="001-099", refresh=False, missing_only=False)

    run_command(args)

    manifest = tmp_path / "data" / "manifests" / "volume-slug.json"
    assert manifest.exists()
    assert "scp-002" in manifest.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run pipeline test and verify failure**

Run: `python -m pytest tests/test_pipeline.py -q`

Expected: FAIL with missing `scp_epub.pipeline`.

- [ ] **Step 3: Implement pipeline command dispatcher**

Create `src/scp_epub/pipeline.py`:

```python
from __future__ import annotations

import json
from argparse import Namespace
from dataclasses import asdict
from pathlib import Path

from .cache import CacheStore
from .config import load_config
from .fetcher import Fetcher
from .indexer import parse_tales_index
from .manifest import build_volume_manifest, link_map_for_manifest
from .models import PageRef
from .packager import write_epub
from .report import BuildReport
from .scp001 import extract_chronological_proposals
from .transformer import transform_page
from .urls import slug_from_url


def run_command(args: Namespace) -> None:
    config = load_config(args.config)
    volume = config.volumes[args.volume]
    cache = CacheStore(config.cache_dir)
    fetcher = Fetcher(cache, retry_count=config.retry_count, delay_seconds=config.request_delay_seconds)

    if args.command == "index":
        manifest = _build_manifest(config, volume, fetcher, args.refresh)
        _write_manifest(config.manifest_dir / f"{volume.output_slug}.json", manifest)
        return

    if args.command in {"fetch", "clean", "build"}:
        manifest_path = config.manifest_dir / f"{volume.output_slug}.json"
        manifest = _read_manifest(manifest_path) if manifest_path.exists() else _build_manifest(config, volume, fetcher, args.refresh)
        _write_manifest(manifest_path, manifest)

        if args.command == "fetch":
            for entry in manifest:
                fetcher.fetch_page(entry.url, entry.slug, refresh=args.refresh)
            return

        link_map = link_map_for_manifest(manifest)
        processed = []
        report = BuildReport(total_manifest_entries=len(manifest), scp001_proposal_count=sum(1 for entry in manifest if entry.role == "scp001-proposal"))
        for entry in manifest:
            result = fetcher.fetch_page(entry.url, entry.slug, refresh=args.refresh)
            if result.from_cache:
                report.pages_from_cache += 1
            else:
                report.pages_from_network += 1
            html = result.path.read_text(encoding="utf-8")
            page = transform_page(html, entry, config.base_url, link_map, {})
            processed.append(page)
            report.internal_links.extend(page.internal_links)
            report.external_links.extend(page.external_links)
            report.images_included.extend(page.asset_urls)

        if args.command == "clean":
            config.processed_dir.mkdir(parents=True, exist_ok=True)
            for page in processed:
                (config.processed_dir / f"{page.entry.slug}.xhtml").write_text(page.xhtml, encoding="utf-8")
            return

        report.total_epub_chapters = len(processed)
        epub_path = config.output_dir / "epub" / f"{volume.output_slug}.epub"
        report_path = config.output_dir / "reports" / f"{volume.output_slug}-report.json"
        write_epub(epub_path, volume.title, config.language, config.creator, processed, {})
        report.write(report_path)
        return

    raise ValueError(f"Unknown command: {args.command}")


def _build_manifest(config, volume, fetcher: Fetcher, refresh: bool) -> list[PageRef]:
    index_slug = slug_from_url(config.index_url)
    index_result = fetcher.fetch_page(config.index_url, index_slug, refresh=refresh)
    index_html = Path(index_result.path).read_text(encoding="utf-8")
    index_entries = parse_tales_index(index_html, config.base_url, volume.start, volume.end)

    scp001_slug = slug_from_url(config.scp001_url)
    scp001_result = fetcher.fetch_page(config.scp001_url, scp001_slug, refresh=refresh)
    scp001_html = Path(scp001_result.path).read_text(encoding="utf-8")
    proposals = extract_chronological_proposals(scp001_html, config.base_url)

    return build_volume_manifest(index_entries, proposals)


def _write_manifest(path: Path, manifest: list[PageRef]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(entry) for entry in manifest], ensure_ascii=False, indent=2), encoding="utf-8")


def _read_manifest(path: Path) -> list[PageRef]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [PageRef(**item) for item in raw]
```

- [ ] **Step 4: Run pipeline test and verify pass**

Run: `python -m pytest tests/test_pipeline.py -q`

Expected: PASS with `1 passed`.

- [ ] **Step 5: Run full unit suite**

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Commit pipeline**

Run:

```bash
git add src/scp_epub/pipeline.py src/scp_epub/cli.py tests/test_pipeline.py
git commit -m "feat: orchestrate epub pipeline"
```

Expected: commit succeeds.

## Task 11: Asset Localization In Build Output

**Files:**
- Modify: `src/scp_epub/pipeline.py`
- Modify: `src/scp_epub/packager.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Add failing asset localization test**

Append to `tests/test_pipeline.py`:

```python
def test_build_command_reports_images(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "series-1.yaml").write_text(
        """
series_id: scp-series-1
title: Test Series
language: zh-CN
creator: Test Creator
base_url: https://example.test
index_path: /index
scp001_path: /scp-001
cache_dir: data/raw
manifest_dir: data/manifests
processed_dir: data/processed
output_dir: output
request_delay_seconds: 0
retry_count: 1
volumes:
  "001-099":
    start: 1
    end: 99
    title: Volume Title
    output_slug: volume-slug
""",
        encoding="utf-8",
    )
    index_html = '<div id="page-content"><h1>002到099</h1><ul><li><a href="/scp-002">SCP-002</a></li></ul></div>'
    scp001_html = Path("tests/fixtures/scp001_sample.html").read_text(encoding="utf-8")
    page_html = '<div id="page-content"><p><img src="/image.png"/></p></div>'

    class FakeFetcher:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_page(self, url, slug, refresh=False):
            target = tmp_path / f"{slug}.html"
            if slug == "index":
                target.write_text(index_html, encoding="utf-8")
            elif slug == "scp-001":
                target.write_text(scp001_html, encoding="utf-8")
            else:
                target.write_text(page_html, encoding="utf-8")
            return Namespace(path=target, from_cache=False, status_code=200, content_type="text/html", metadata_path=target.with_suffix(".json"))

        def fetch_asset(self, url, refresh=False):
            asset = tmp_path / "image.png"
            asset.write_bytes(b"png")
            return str(asset), False

    monkeypatch.setattr("scp_epub.pipeline.Fetcher", FakeFetcher)
    args = Namespace(command="build", config=str(config_dir / "series-1.yaml"), volume="001-099", refresh=False, missing_only=False)

    run_command(args)

    report = tmp_path / "output" / "reports" / "volume-slug-report.json"
    assert "https://example.test/image.png" in report.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run pipeline test and verify failure**

Run: `python -m pytest tests/test_pipeline.py::test_build_command_reports_images -q`

Expected: FAIL because `fetch_asset` is not called and the report omits the image.

- [ ] **Step 3: Update pipeline to fetch and map assets before final transform**

Modify the processing loop in `src/scp_epub/pipeline.py`:

```python
asset_paths: dict[str, Path] = {}
for entry in manifest:
    result = fetcher.fetch_page(entry.url, entry.slug, refresh=args.refresh)
    if result.from_cache:
        report.pages_from_cache += 1
    else:
        report.pages_from_network += 1
    html = result.path.read_text(encoding="utf-8")
    first_pass = transform_page(html, entry, config.base_url, link_map, {})
    asset_map: dict[str, str] = {}
    for asset_url in first_pass.asset_urls:
        try:
            asset_path_text, _from_cache = fetcher.fetch_asset(asset_url, refresh=args.refresh)
            asset_path = Path(asset_path_text)
            asset_paths[asset_url] = asset_path
            asset_map[asset_url] = f"assets/{asset_path.name}"
            report.images_included.append(asset_url)
        except Exception:
            report.failed_assets.append(asset_url)
    page = transform_page(html, entry, config.base_url, link_map, asset_map)
    processed.append(page)
    report.internal_links.extend(page.internal_links)
    report.external_links.extend(page.external_links)
```

Modify the build call in `src/scp_epub/pipeline.py`:

```python
write_epub(epub_path, volume.title, config.language, config.creator, processed, asset_paths)
```

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m pytest tests/test_pipeline.py -q`

Expected: all pipeline tests pass.

- [ ] **Step 5: Commit asset localization**

Run:

```bash
git add src/scp_epub/pipeline.py src/scp_epub/packager.py tests/test_pipeline.py
git commit -m "feat: localize page assets"
```

Expected: commit succeeds.

## Task 12: Live Sample Build And Verification

**Files:**
- No required source edits unless live verification reveals a real bug.
- Generated but ignored: `data/raw/`, `data/manifests/`, `data/processed/`, `output/`.

- [ ] **Step 1: Install package in editable mode with dev dependencies**

Run: `python -m pip install -e ".[dev]"`

Expected: package and test dependencies install successfully.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Build the real manifest**

Run: `python -m scp_epub index --config config/series-1.yaml --volume 001-099`

Expected: `data/manifests/scp-series-1-001-099-tales.json` exists and contains `scp-001`, chronological proposal slugs, `scp-002`, and `scp-099`.

- [ ] **Step 4: Fetch pages using workspace cache**

Run: `python -m scp_epub fetch --config config/series-1.yaml --volume 001-099 --missing-only`

Expected: raw HTML pages are stored under `data/raw/pages/`, and rerunning the command reuses cached pages.

- [ ] **Step 5: Build the sample EPUB**

Run: `python -m scp_epub build --config config/series-1.yaml --volume 001-099 --missing-only`

Expected:

```text
output/epub/scp-series-1-001-099-tales.epub
output/reports/scp-series-1-001-099-tales-report.json
```

- [ ] **Step 6: Inspect validation report**

Run: `Get-Content -Raw output/reports/scp-series-1-001-099-tales-report.json`

Expected: report includes nonzero `total_manifest_entries`, nonzero `total_epub_chapters`, nonzero `scp001_proposal_count`, and lists any failed pages or assets.

- [ ] **Step 7: Inspect EPUB container**

Run: `python -c "import zipfile; z=zipfile.ZipFile('output/epub/scp-series-1-001-099-tales.epub'); print(any(n.endswith('nav.xhtml') for n in z.namelist()), sum(n.endswith('.xhtml') for n in z.namelist()))"`

Expected: prints `True` and a chapter count greater than 100 because `SCP-001` proposals and related stories are included.

- [ ] **Step 8: Commit final implementation**

Run:

```bash
git status --short
git add pyproject.toml config src tests
git commit -m "feat: build scp series 1 sample epub"
```

Expected: source/config/test changes are committed, while `data/raw/`, `data/processed/`, and `output/` remain ignored.

## Self-Review

- Spec coverage: Tasks cover index parsing, `SCP-001` chronological proposal extraction, workspace cache, raw assets, collapsible expansion, tab conversion, non正文 removal, internal/external link rewriting, EPUB packaging, report generation, and live sample verification.
- Scan result: clean.
- Type consistency: Shared dataclasses are introduced in Task 2 and reused consistently by later parser, manifest, transformer, packager, and pipeline tasks.
