# Kindle Scribe Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `build --kindle` path that creates a Kindle-optimized EPUB and atomically converts it to AZW3 with Calibre's Kindle Scribe profile without changing normal EPUB builds.

**Architecture:** Keep fetching, transformation, assets, cover, and navigation shared. Add a focused `kindle.py` module for copied-page XHTML fallbacks and Calibre execution, package a separate KF8-compatible stylesheet, let `write_epub()` accept an optional stylesheet, and branch only at the final output stage in `build_volume()`.

**Tech Stack:** Python 3.11+, BeautifulSoup 4, standard-library `dataclasses`, `importlib.resources`, `pathlib`, `shutil`, and `subprocess`; pytest; Calibre `ebook-convert` as an optional external executable.

## Global Constraints

- Without `--kindle`, existing paths, filenames, XHTML, CSS, reports, and command behavior remain unchanged.
- A Kindle build writes `<output_slug>-Kindle.epub`, `<output_slug>-Kindle.azw3`, and `<output_slug>-Kindle-report.json`.
- The Kindle output remains reflowable and does not embed a Chinese body font.
- Use Calibre arguments `--output-profile=kindle_scribe` and `--no-inline-toc`.
- Do not enable `--linearize-tables`, forced justification, fixed margins, or automatic Calibre installation.
- Calibre failure retains the optimized EPUB and report, preserves any previous valid final AZW3, removes the temporary AZW3, and exits with a clear error.
- Update both `README.md` and `AGENTS.md`.
- Do not stage or commit generated EPUB/AZW3/report/cache files or the existing untracked `uv.lock`.

---

### Task 1: Make the EPUB writer accept an explicit stylesheet

**Files:**
- Modify: `src/scp_epub/epub.py:487-535`
- Test: `tests/test_epub.py`

**Interfaces:**
- Consumes: existing `BOOK_CSS: str` and `write_epub(...) -> Path`.
- Produces: `write_epub(..., book_css: str = BOOK_CSS) -> Path`; all existing callers continue to receive `BOOK_CSS` by default.

- [ ] **Step 1: Write the failing custom-stylesheet regression test**

Add `BOOK_CSS` to the import from `scp_epub.epub`, then add:

```python
def test_write_epub_accepts_custom_css_without_changing_default(tmp_path: Path):
    page = _page("scp-001", "SCP-001", 1)
    default_path = tmp_path / "default.epub"
    custom_path = tmp_path / "custom.epub"

    write_epub(
        [page],
        default_path,
        title="SCP",
        language="zh-CN",
        creator="SCP",
    )
    write_epub(
        [page],
        custom_path,
        title="SCP",
        language="zh-CN",
        creator="SCP",
        book_css="body { color: black; }\n",
    )

    with zipfile.ZipFile(default_path) as archive:
        default_css = archive.read("OEBPS/styles/book.css").decode("utf-8")
    with zipfile.ZipFile(custom_path) as archive:
        custom_css = archive.read("OEBPS/styles/book.css").decode("utf-8")

    assert default_css == BOOK_CSS
    assert custom_css == "body { color: black; }\n"
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_epub.py::test_write_epub_accepts_custom_css_without_changing_default -q
```

Expected: FAIL because `write_epub()` does not accept `book_css`.

- [ ] **Step 3: Add the optional stylesheet parameter**

Change the signature and archive write in `src/scp_epub/epub.py`:

```python
def write_epub(
    pages: list[ProcessedPage],
    output_path: Path,
    *,
    title: str,
    language: str,
    creator: str,
    identifier: str | None = None,
    modified: datetime | str | None = None,
    assets: list[AssetRef] | tuple[AssetRef, ...] = (),
    remote_resource_page_slugs: set[str] | tuple[str, ...] | list[str] = (),
    cover_image_path: Path | None = None,
    book_css: str = BOOK_CSS,
) -> Path:
    # Keep the existing body unchanged except for the stylesheet write.
```

Replace:

```python
archive.writestr("OEBPS/styles/book.css", BOOK_CSS)
```

with:

```python
archive.writestr("OEBPS/styles/book.css", book_css)
```

- [ ] **Step 4: Run EPUB tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_epub.py -q
```

Expected: all `tests/test_epub.py` tests pass, proving the new hook and the unchanged default.

- [ ] **Step 5: Commit the isolated writer change**

```powershell
git add src/scp_epub/epub.py tests/test_epub.py
git commit -m "feat: allow custom epub styles"
```

---

### Task 2: Add copied-page Kindle fallbacks and a KF8-compatible stylesheet

**Files:**
- Create: `src/scp_epub/kindle.py`
- Create: `src/scp_epub/styles/kindle.css`
- Create: `tests/test_kindle.py`

**Interfaces:**
- Consumes: `ProcessedPage` from `src/scp_epub/models.py` and packaged `scp_epub/styles/kindle.css`.
- Produces: `prepare_kindle_pages(pages: Sequence[ProcessedPage]) -> list[ProcessedPage]` and `load_kindle_css() -> str`.
- Preserves: every original `ProcessedPage` and its cached XHTML.

- [ ] **Step 1: Write failing Kindle page and CSS tests**

Create `tests/test_kindle.py`:

```python
from pathlib import Path

from scp_epub.kindle import load_kindle_css, prepare_kindle_pages
from scp_epub.models import PageRef, ProcessedPage


def _page(xhtml: str) -> ProcessedPage:
    return ProcessedPage(
        entry=PageRef(
            title="SCP-001",
            url="https://scp-wiki-cn.wikidot.com/scp-001",
            slug="scp-001",
            level=1,
            role="scp",
            order=1,
        ),
        xhtml=xhtml,
        asset_urls=(),
        internal_links=(),
        external_links=(),
    )


def test_prepare_kindle_pages_materializes_anomaly_labels_without_mutating_source():
    source = _page(
        '<div class="anom-bar-container clear-4">'
        '<div class="top-right-box"><div class="clearance"></div></div>'
        '<div class="risk-class"><div class="class-text">危急</div></div>'
        '<div class="danger-diamond"><a href="memo.xhtml">备忘录</a></div>'
        "</div>"
    )

    [prepared] = prepare_kindle_pages([source])

    assert prepared is not source
    assert '<span class="kindle-clearance-label">SECRET</span>' in prepared.xhtml
    assert '<span class="kindle-danger-label">危急</span>' in prepared.xhtml
    assert 'href="memo.xhtml"' in prepared.xhtml
    assert "SECRET" not in source.xhtml
    assert "kindle-danger-label" not in source.xhtml


def test_prepare_kindle_pages_maps_all_clearance_levels():
    expected = {
        1: "PUBLIC",
        2: "RESTRICTED",
        3: "CONFIDENTIAL",
        4: "SECRET",
        5: "TOP SECRET",
        6: "COSMIC TOP SECRET",
    }
    pages = [
        _page(
            f'<div class="anom-bar-container clear-{level}">'
            '<div class="top-right-box"><div class="clearance"></div></div>'
            "</div>"
        )
        for level in expected
    ]

    prepared = prepare_kindle_pages(pages)

    for page, label in zip(prepared, expected.values(), strict=True):
        assert f'>{label}</span>' in page.xhtml


def test_kindle_css_uses_kf8_fallbacks_and_preserves_scp_components():
    css = load_kindle_css()
    lowered = css.lower()

    for unsupported in (
        "display: grid",
        "display:grid",
        "display: flex",
        "display:flex",
        "::before",
        "::after",
        ":first-child",
        ":last-child",
        "linear-gradient",
        "transform:",
        "box-shadow",
    ):
        assert unsupported not in lowered

    assert ".content-panel" in css
    assert ".scp-image-block.block-right" in css
    assert "table.wiki-content-table" in css
    assert ".tabview-panel-epub" in css
    assert ".anom-bar-container" in css
    assert ".kindle-clearance-label" in css
    assert ".kindle-danger-label" in css
```

- [ ] **Step 2: Run the new test file and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_kindle.py -q
```

Expected: collection fails because `scp_epub.kindle` does not exist.

- [ ] **Step 3: Implement copied-page Kindle preparation**

Create `src/scp_epub/kindle.py` with the page/CSS portion below. Task 3 will append conversion behavior to the same module.

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from importlib import resources

from bs4 import BeautifulSoup, Tag

from .models import ProcessedPage


CLEARANCE_LABELS = {
    "clear-1": "PUBLIC",
    "clear-2": "RESTRICTED",
    "clear-3": "CONFIDENTIAL",
    "clear-4": "SECRET",
    "clear-5": "TOP SECRET",
    "clear-6": "COSMIC TOP SECRET",
}


def load_kindle_css() -> str:
    return (
        resources.files("scp_epub")
        .joinpath("styles/kindle.css")
        .read_text(encoding="utf-8")
    )


def prepare_kindle_pages(pages: Sequence[ProcessedPage]) -> list[ProcessedPage]:
    return [replace(page, xhtml=_prepare_kindle_xhtml(page.xhtml)) for page in pages]


def _prepare_kindle_xhtml(xhtml: str) -> str:
    soup = BeautifulSoup(f"<root>{xhtml}</root>", "html.parser")
    root = soup.find("root")
    if not isinstance(root, Tag):
        return xhtml

    for container in root.select(".anom-bar-container"):
        if not isinstance(container, Tag):
            continue
        classes = {str(value) for value in container.get("class", [])}
        clearance_text = next(
            (label for class_name, label in CLEARANCE_LABELS.items() if class_name in classes),
            None,
        )
        clearance = container.select_one(".top-right-box .clearance")
        if (
            clearance_text
            and isinstance(clearance, Tag)
            and not clearance.get_text(strip=True)
        ):
            label = soup.new_tag("span")
            label["class"] = "kindle-clearance-label"
            label.string = clearance_text
            clearance.append(label)

        risk = container.select_one(".risk-class .class-text")
        diamond = container.select_one(".danger-diamond")
        if (
            isinstance(risk, Tag)
            and isinstance(diamond, Tag)
            and not diamond.select_one(".kindle-danger-label")
        ):
            risk_text = risk.get_text(" ", strip=True)
            if risk_text:
                label = soup.new_tag("span")
                label["class"] = "kindle-danger-label"
                label.string = risk_text
                diamond.insert(0, label)

    return "".join(str(child) for child in root.contents).strip()
```

- [ ] **Step 4: Add the complete Kindle stylesheet**

Create `src/scp_epub/styles/kindle.css`:

```css
body {
  line-height: 1.55;
}

h1 {
  color: #660011;
}

h2 {
  margin: 0.75em 0;
}

hr {
  border: 0;
  border-top: 1px solid #777;
  margin: 1.5em 0;
}

img {
  height: auto;
}

.content-panel {
  margin: 1em 0;
  padding: 0.9em 1em;
  border: 1px solid #777;
  border-radius: 0.35em;
  background: #f7f7f7;
}

.yui-navset {
  margin: 0.5em 0;
}

.yui-navset .yui-nav {
  margin: 0 0 0.8em;
  padding: 0;
  text-align: right;
  list-style: none;
}

.yui-navset .yui-nav li {
  display: inline-block;
  margin: 0 0 0.35em 0.8em;
}

.yui-navset .yui-nav a {
  color: #660011;
  text-decoration: none;
}

.yui-navset .yui-nav a em {
  font-style: normal;
}

.yui-navset .yui-nav .selected a {
  color: #111;
  font-weight: bold;
}

.yui-navset .yui-content {
  padding: 0.25em 0;
  text-align: center;
}

.yui-navset .divider {
  margin: 1em 0 0.45em;
  padding-top: 0.35em;
  border-top: 1px solid #aaa;
  color: #555;
  font-family: Georgia, "Times New Roman", serif;
  font-weight: bold;
  text-align: center;
}

.tabview-epub {
  margin: 1em 0;
}

.tabview-panel-epub {
  margin: 1em 0;
  padding: 0.9em 1em;
  border: 1px solid #888;
  border-left: 0.3em solid #660011;
  background: #f7f7f7;
}

.tabview-panel-title {
  margin: 0 0 0.75em;
  padding-bottom: 0.35em;
  border-bottom: 1px solid #aaa;
  color: #660011;
  font-size: 1.05em;
}

blockquote,
.blockquote {
  margin: 1em 1.5em;
  padding: 0.75em 1em;
  border: 1px dashed #777;
  background: #f7f7f7;
}

table.wiki-content-table {
  width: 100%;
  margin: 1em auto;
  border-collapse: collapse;
  table-layout: auto;
}

table.wiki-content-table th,
table.wiki-content-table td {
  padding: 0.4em 0.55em;
  border: 1px solid #666;
  vertical-align: top;
  word-wrap: break-word;
}

table.wiki-content-table th {
  background: #e8e8e8;
  font-weight: bold;
  text-align: center;
}

.scp-image-block {
  width: 42%;
  margin: 0.75em 0 1em;
  border: 1px solid #555;
  background: #fff;
}

.scp-image-block.block-right {
  float: right;
  clear: right;
  margin: 0 0 1em 1.2em;
}

.scp-image-block.block-left {
  float: left;
  clear: left;
  margin: 0 1.2em 1em 0;
}

.scp-image-block.block-center {
  clear: both;
  width: 70%;
  margin: 1em auto;
}

.scp-image-block img {
  display: block;
  width: 100%;
}

.scp-image-caption {
  padding: 0.3em 0.5em;
  border-top: 1px solid #555;
  text-align: center;
  font-size: 0.9em;
  font-weight: bold;
}

.anom-bar-container {
  width: 100%;
  margin: 1.2em 0;
  padding: 0.65em;
  border: 2px solid #7a1726;
  background: #e7e7e7;
  color: #111;
  font-family: Arial, Helvetica, sans-serif;
}

.anom-bar-container .lang-tr {
  display: none;
}

.anom-bar-container .top-box,
.anom-bar-container .bottom-box,
.anom-bar-container .main-class {
  display: table;
  width: 100%;
  border-collapse: separate;
  border-spacing: 0.35em;
}

.anom-bar-container .top-left-box,
.anom-bar-container .top-center-box,
.anom-bar-container .top-right-box,
.anom-bar-container .text-part,
.anom-bar-container .diamond-part,
.anom-bar-container .contain-class,
.anom-bar-container .second-class {
  display: table-cell;
  vertical-align: middle;
}

.anom-bar-container .top-left-box {
  width: 28%;
}

.anom-bar-container .top-center-box {
  width: 44%;
  border-top: 0.35em solid #111;
  border-bottom: 0.35em solid #111;
}

.anom-bar-container .top-right-box {
  width: 28%;
  text-align: center;
}

.anom-bar-container .number {
  font-size: 2em;
  font-weight: bold;
  letter-spacing: 0.08em;
}

.anom-bar-container .level {
  font-size: 1.5em;
  font-weight: bold;
}

.kindle-clearance-label {
  display: block;
  margin-top: 0.2em;
  font-size: 0.78em;
  font-weight: bold;
}

.anom-bar-container .text-part {
  width: 76%;
}

.anom-bar-container .diamond-part {
  width: 24%;
  text-align: center;
}

.anom-bar-container .contain-class,
.anom-bar-container .second-class,
.anom-bar-container .disrupt-class,
.anom-bar-container .risk-class {
  padding: 0.35em 0.5em;
  border-left: 0.45em solid #7a1726;
  background: #f2f2f2;
}

.anom-bar-container .class-category {
  font-size: 0.78em;
}

.anom-bar-container .class-text {
  font-size: 1.15em;
  font-weight: bold;
  line-height: 1.1;
  text-transform: uppercase;
}

.anom-bar-container .danger-diamond {
  display: inline-block;
  width: 5.5em;
  min-height: 5.5em;
  padding: 0.5em;
  border: 0.25em double #111;
  background: #fff;
  text-align: center;
}

.anom-bar-container .danger-diamond a,
.anom-bar-container .danger-diamond .arrows,
.anom-bar-container .danger-diamond .octagon,
.anom-bar-container .danger-diamond .quadrants,
.anom-bar-container .danger-diamond .top-icon,
.anom-bar-container .danger-diamond .right-icon,
.anom-bar-container .danger-diamond .left-icon,
.anom-bar-container .danger-diamond .bottom-icon {
  display: none;
}

.kindle-danger-label {
  display: block;
  padding-top: 1.5em;
  font-size: 1em;
  font-weight: bold;
}

@media (max-width: 600px) {
  .scp-image-block,
  .scp-image-block.block-left,
  .scp-image-block.block-right,
  .scp-image-block.block-center {
    float: none;
    clear: both;
    width: 80%;
    margin: 1em auto;
  }

  .anom-bar-container .top-box,
  .anom-bar-container .bottom-box,
  .anom-bar-container .main-class,
  .anom-bar-container .top-left-box,
  .anom-bar-container .top-center-box,
  .anom-bar-container .top-right-box,
  .anom-bar-container .text-part,
  .anom-bar-container .diamond-part,
  .anom-bar-container .contain-class,
  .anom-bar-container .second-class {
    display: block;
    width: auto;
  }

  .anom-bar-container .top-right-box,
  .anom-bar-container .diamond-part {
    margin-top: 0.6em;
    text-align: left;
  }
}
```

- [ ] **Step 5: Run Kindle tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_kindle.py -q
```

Expected: all three tests pass.

- [ ] **Step 6: Commit the Kindle presentation layer**

```powershell
git add src/scp_epub/kindle.py src/scp_epub/styles/kindle.css tests/test_kindle.py
git commit -m "feat: add Kindle-compatible page styling"
```

---

### Task 3: Add atomic Calibre AZW3 conversion

**Files:**
- Modify: `src/scp_epub/kindle.py`
- Test: `tests/test_kindle.py`

**Interfaces:**
- Consumes: an existing Kindle EPUB path, a final AZW3 path, optional `ebook-convert` executable, and an injectable subprocess runner.
- Produces: `KindleConversionError` and `convert_epub_to_azw3(epub_path: Path, azw3_path: Path, *, executable: str | Path | None = None, runner: Runner = subprocess.run) -> Path`.
- Guarantees: only a nonempty temporary AZW3 replaces the final path; failures retain the EPUB and previous final AZW3.

- [ ] **Step 1: Write failing converter tests**

Append to `tests/test_kindle.py`, adding `subprocess`, `pytest`, and the converter imports:

```python
import subprocess

import pytest

from scp_epub.kindle import (
    KindleConversionError,
    convert_epub_to_azw3,
    load_kindle_css,
    prepare_kindle_pages,
)


def test_convert_epub_to_azw3_uses_scribe_profile_and_atomically_replaces_output(
    tmp_path: Path,
):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub")
    azw3_path = tmp_path / "azw3" / "book.azw3"
    azw3_path.parent.mkdir()
    azw3_path.write_bytes(b"old valid azw3")
    commands = []

    def fake_runner(command, **kwargs):
        commands.append((command, kwargs))
        Path(command[2]).write_bytes(b"new valid azw3")
        return subprocess.CompletedProcess(command, 0, stdout="converted", stderr="")

    result = convert_epub_to_azw3(
        epub_path,
        azw3_path,
        executable="ebook-convert-test",
        runner=fake_runner,
    )

    assert result == azw3_path
    assert azw3_path.read_bytes() == b"new valid azw3"
    command, kwargs = commands[0]
    assert command == [
        "ebook-convert-test",
        str(epub_path),
        str(tmp_path / "azw3" / "book.tmp.azw3"),
        "--output-profile=kindle_scribe",
        "--no-inline-toc",
    ]
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert not (tmp_path / "azw3" / "book.tmp.azw3").exists()


def test_convert_epub_to_azw3_reports_missing_calibre(tmp_path: Path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub")
    monkeypatch.setattr("scp_epub.kindle.shutil.which", lambda _name: None)

    with pytest.raises(KindleConversionError, match="ebook-convert"):
        convert_epub_to_azw3(epub_path, tmp_path / "book.azw3")


def test_convert_epub_to_azw3_cleans_temp_and_preserves_previous_output_on_failure(
    tmp_path: Path,
):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"epub remains")
    azw3_path = tmp_path / "book.azw3"
    azw3_path.write_bytes(b"previous valid azw3")

    def fake_runner(command, **_kwargs):
        Path(command[2]).write_bytes(b"partial")
        return subprocess.CompletedProcess(command, 9, stdout="", stderr="conversion failed")

    with pytest.raises(KindleConversionError, match="conversion failed"):
        convert_epub_to_azw3(
            epub_path,
            azw3_path,
            executable="ebook-convert-test",
            runner=fake_runner,
        )

    assert epub_path.read_bytes() == b"epub remains"
    assert azw3_path.read_bytes() == b"previous valid azw3"
    assert not (tmp_path / "book.tmp.azw3").exists()
```

- [ ] **Step 2: Run converter tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_kindle.py -q
```

Expected: collection fails because the conversion API is not defined.

- [ ] **Step 3: Implement converter discovery, execution, and atomic replacement**

Append the following imports and definitions to `src/scp_epub/kindle.py`:

```python
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path


Runner = Callable[..., subprocess.CompletedProcess[str]]


class KindleConversionError(RuntimeError):
    pass


def convert_epub_to_azw3(
    epub_path: Path,
    azw3_path: Path,
    *,
    executable: str | Path | None = None,
    runner: Runner = subprocess.run,
) -> Path:
    if not epub_path.is_file():
        raise KindleConversionError(f"Kindle EPUB does not exist: {epub_path}")

    resolved = str(executable) if executable is not None else shutil.which("ebook-convert")
    if not resolved:
        raise KindleConversionError(
            "Calibre ebook-convert was not found; install Calibre and ensure "
            "ebook-convert is available on PATH"
        )

    azw3_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = azw3_path.with_name(f"{azw3_path.stem}.tmp{azw3_path.suffix}")
    temporary_path.unlink(missing_ok=True)
    command = [
        resolved,
        str(epub_path),
        str(temporary_path),
        "--output-profile=kindle_scribe",
        "--no-inline-toc",
    ]

    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise KindleConversionError(
            f"Failed to start Calibre command {command!r}: {exc}"
        ) from exc

    if result.returncode != 0:
        temporary_path.unlink(missing_ok=True)
        details = "\n".join(
            value.strip()
            for value in (result.stdout, result.stderr)
            if value and value.strip()
        )[-2000:]
        raise KindleConversionError(
            f"Calibre command {command!r} exited with {result.returncode}: {details}"
        )

    if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
        temporary_path.unlink(missing_ok=True)
        raise KindleConversionError(
            f"Calibre command {command!r} did not produce a nonempty AZW3"
        )

    temporary_path.replace(azw3_path)
    return azw3_path
```

Keep all imports at the top of the module; do not literally leave a second import block in the middle of the file.

- [ ] **Step 4: Run Kindle tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_kindle.py -q
```

Expected: all page, CSS, and converter tests pass.

- [ ] **Step 5: Commit the converter**

```powershell
git add src/scp_epub/kindle.py tests/test_kindle.py
git commit -m "feat: add atomic Calibre conversion"
```

---

### Task 4: Integrate `--kindle` with CLI and volume builds

**Files:**
- Modify: `src/scp_epub/cli.py:12-21`
- Modify: `src/scp_epub/pipeline.py:1-30,200-282,544-590,900-930`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 1 `write_epub(..., book_css=...)`; Task 2 `prepare_kindle_pages()` and `load_kindle_css()`; Task 3 `convert_epub_to_azw3()`.
- Produces: `build_volume(..., kindle: bool = False, kindle_converter: KindleConverter | None = None) -> Path` and `kindle_azw3_path_for_volume(config: AppConfig, volume: VolumeSpec | str) -> Path`.
- CLI behavior: `build --kindle` is accepted; non-build commands reject `--kindle`; normal `build` still returns and prints the normal EPUB path.

- [ ] **Step 1: Write failing CLI tests**

Add `pytest` to `tests/test_cli.py` imports and add:

```python
import pytest


def test_parser_accepts_kindle_only_for_build():
    parser = build_parser()

    args = parser.parse_args(["build", "--volume", "featured", "--kindle"])

    assert args.command == "build"
    assert args.volume == "featured"
    assert args.kindle is True
    with pytest.raises(SystemExit):
        parser.parse_args(["fetch", "--kindle"])


def test_build_command_passes_kindle_and_prints_both_outputs(monkeypatch, tmp_path, capsys):
    calls = []
    epub_path = tmp_path / "output" / "epub" / "book-Kindle.epub"
    azw3_path = tmp_path / "output" / "azw3" / "book-Kindle.azw3"

    monkeypatch.setattr("scp_epub.pipeline.load_config", lambda _path: "config")

    def fake_build_volume(config, volume, *, force=False, kindle=False):
        calls.append((config, volume, force, kindle))
        return epub_path

    monkeypatch.setattr("scp_epub.pipeline.build_volume", fake_build_volume)
    monkeypatch.setattr(
        "scp_epub.pipeline.kindle_azw3_path_for_volume",
        lambda _config, _volume: azw3_path,
    )

    result = main(
        [
            "build",
            "--config",
            "config/featured-scp.yaml",
            "--volume",
            "featured",
            "--kindle",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert calls == [("config", "featured", False, True)]
    assert str(epub_path) in captured.out
    assert str(azw3_path) in captured.out
```

- [ ] **Step 2: Write the failing pipeline integration test**

Append to `tests/test_pipeline.py`:

```python
def test_build_volume_kindles_pages_css_report_and_azw3_without_mutating_processed_xhtml(
    tmp_path: Path,
):
    config = app_config(tmp_path)
    manifest = [
        PageRef("SCP-001", f"{BASE_URL}/scp-001", "scp-001", 1, "scp", order=1),
    ]
    from scp_epub.manifest import write_manifest

    write_manifest(manifest, config.manifest_dir / "test-volume.json")
    fetcher = FakeFetcher(
        tmp_path / "cache",
        {
            "scp-001": simple_page(
                "SCP-001",
                '<div class="anom-bar-container clear-4">'
                '<div class="top-right-box"><div class="clearance"></div></div>'
                '<div class="risk-class"><div class="class-text">危急</div></div>'
                '<div class="danger-diamond"></div>'
                "</div>",
            ),
        },
    )
    conversion_calls = []

    def fake_converter(epub_path: Path, azw3_path: Path) -> Path:
        conversion_calls.append((epub_path, azw3_path))
        assert epub_path.exists()
        azw3_path.parent.mkdir(parents=True, exist_ok=True)
        azw3_path.write_bytes(b"azw3")
        return azw3_path

    output_path = build_volume(
        config,
        "001-099",
        fetcher=fetcher,
        kindle=True,
        kindle_converter=fake_converter,
    )

    assert output_path == config.output_dir / "epub" / "test-volume-Kindle.epub"
    azw3_path = config.output_dir / "azw3" / "test-volume-Kindle.azw3"
    assert conversion_calls == [(output_path, azw3_path)]
    assert azw3_path.read_bytes() == b"azw3"

    with zipfile.ZipFile(output_path) as archive:
        css = archive.read("OEBPS/styles/book.css").decode("utf-8")
        chapter = archive.read("OEBPS/text/0001-scp-001.xhtml").decode("utf-8")
    assert ".kindle-clearance-label" in css
    assert '<span class="kindle-clearance-label">SECRET</span>' in chapter
    assert '<span class="kindle-danger-label">危急</span>' in chapter

    processed_path = config.processed_dir / "test-volume" / "0001-scp-001.xhtml"
    assert "kindle-clearance-label" not in processed_path.read_text(encoding="utf-8")
    report_path = config.output_dir / "reports" / "test-volume-Kindle-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["output_path"] == str(output_path)
```

- [ ] **Step 3: Run CLI and pipeline tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_pipeline.py -q
```

Expected: failures because `--kindle`, the pipeline keyword arguments, and Kindle output helper are absent.

- [ ] **Step 4: Add the build-only CLI flag**

In `src/scp_epub/cli.py`, keep the existing common arguments and add the flag only to the build parser:

```python
    for command in ("index", "manifest", "fetch", "clean", "build", "scan-linked-appendices"):
        subparser = subparsers.add_parser(command, parents=[command_parent])
        subparser.add_argument("--volume", default="001-099")
        subparser.add_argument("--refresh", action="store_true")
        subparser.add_argument("--missing-only", action="store_true")
        if command == "build":
            subparser.add_argument("--kindle", action="store_true")
```

- [ ] **Step 5: Add Kindle output helpers and branch only at final writing**

At the top of `src/scp_epub/pipeline.py`, import `Callable`, add `BOOK_CSS` to
the existing imports from `.epub`, and add:

```python
from .kindle import convert_epub_to_azw3, load_kindle_css, prepare_kindle_pages
```

Define:

```python
KindleConverter = Callable[[Path, Path], Path]
```

Change `build_volume` to:

```python
def build_volume(
    config: AppConfig,
    volume_key: str,
    *,
    fetcher: PageFetcher | None = None,
    force: bool = False,
    kindle: bool = False,
    kindle_converter: KindleConverter | None = None,
) -> Path:
```

Keep all existing work through `remote_slugs` unchanged, then replace the final output block with:

```python
    output_slug = f"{volume.output_slug}-Kindle" if kindle else volume.output_slug
    output_pages = prepare_kindle_pages(localized_pages) if kindle else localized_pages
    output_path = config.output_dir / "epub" / f"{output_slug}.epub"
    book_css = load_kindle_css() if kindle else BOOK_CSS
    write_epub(
        output_pages,
        output_path,
        title=volume.title,
        language=config.language,
        creator=config.creator,
        identifier=f"urn:{config.series_id}:{output_slug}",
        assets=localized_assets,
        remote_resource_page_slugs=remote_slugs,
        cover_image_path=cover_image_path_for_volume(config, volume),
        book_css=book_css,
    )
    write_build_report(
        config.output_dir / "reports" / f"{output_slug}-report.json",
        pages=processed_pages,
        output_path=output_path,
        missing_assets=missing_assets,
        missing_pages=missing_pages,
    )
    if kindle:
        converter = kindle_converter or convert_epub_to_azw3
        converter(output_path, kindle_azw3_path_for_volume(config, volume))
    return output_path
```

Add near the other volume path helpers:

```python
def kindle_azw3_path_for_volume(
    config: AppConfig,
    volume: VolumeSpec | str,
) -> Path:
    volume_spec = volume_for_key(config, volume) if isinstance(volume, str) else volume
    return config.output_dir / "azw3" / f"{volume_spec.output_slug}-Kindle.azw3"
```

- [ ] **Step 6: Pass the CLI flag and print both successful outputs**

Replace the build branch in `run_command` with:

```python
    if command == "build":
        kindle = bool(getattr(args, "kindle", False))
        output_path = build_volume(
            config,
            args.volume,
            force=force,
            kindle=kindle,
        )
        print(f"Wrote {output_path}")
        if kindle:
            print(f"Wrote {kindle_azw3_path_for_volume(config, args.volume)}")
        return
```

- [ ] **Step 7: Run focused integration tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_pipeline.py tests/test_epub.py tests/test_kindle.py -q
```

Expected: all focused tests pass; existing normal-output tests still assert `test-volume.epub` and `test-volume-report.json`.

- [ ] **Step 8: Commit CLI and pipeline integration**

```powershell
git add src/scp_epub/cli.py src/scp_epub/pipeline.py tests/test_cli.py tests/test_pipeline.py
git commit -m "feat: add optional Kindle build"
```

---

### Task 5: Document Kindle Scribe generation and maintenance rules

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: the final CLI, output names, Calibre dependency, error behavior, and test commands from Tasks 1-4.
- Produces: user-facing setup/use instructions and repository-level maintenance constraints.

- [ ] **Step 1: Add the optional Calibre requirement and Kindle command to README**

Under `环境要求`, add:

```markdown
- 可选：Calibre（使用 `build --kindle` 生成 AZW3 时需要，命令 `ebook-convert` 必须可用）
```

After the Featured EPUB example, add:

````markdown
### 构建 Kindle Scribe 优化版

安装 Calibre 后，可为 Featured 精选集同时生成 Kindle 优化 EPUB 和 AZW3：

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle
```

生成结果：

```text
output/epub/SCP基金会档案精选-Kindle.epub
output/azw3/SCP基金会档案精选-Kindle.azw3
output/reports/SCP基金会档案精选-Kindle-report.json
```

Kindle EPUB 使用适合 AZW3/KF8 的专用样式，并由 Calibre 的
`kindle_scribe` 输出配置转换；已有目录会被复用，不会插入重复的正文目录。
该 AZW3 适用于通过 Calibre 和 USB 传入 Kindle Scribe。

`--kindle` 是可选参数。不带该参数时，原有 EPUB 文件名、样式和构建行为不变。
如果未安装 Calibre 或转换失败，命令会保留已生成的 Kindle EPUB 和报告、删除临时
AZW3，并以错误退出；不会用不完整文件覆盖已有 AZW3。
````

- [ ] **Step 2: Extend README project structure and tests**

Add these entries under `src/scp_epub/`:

```text
  kindle.py       Kindle XHTML/CSS 适配与 Calibre AZW3 转换
  styles/         EPUB 打包使用的可选样式资源
```

Add `tests/test_kindle.py` to the test guidance and state that Kindle changes require CLI, pipeline, stylesheet, conversion-failure, and normal-build regression coverage.

- [ ] **Step 3: Add repository rules to AGENTS.md**

After the Featured build command, add:

````markdown
构建 Kindle Scribe 优化版精选样书：

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle
```

该命令生成 `output/epub/SCP基金会档案精选-Kindle.epub`、
`output/azw3/SCP基金会档案精选-Kindle.azw3` 和独立构建报告。它依赖系统中可用的
Calibre `ebook-convert`。不带 `--kindle` 时，原有 EPUB 输出、CSS 和命名必须保持不变。
````

Under testing/HTML constraints add:

```markdown
修改 Kindle 输出时，需要覆盖 `tests/test_kindle.py`、`tests/test_cli.py`、
`tests/test_pipeline.py` 和 `tests/test_epub.py`。Kindle CSS 应避免依赖 KF8 不稳定的
Grid、Flexbox、生成内容伪元素和结构伪类；许可等级等语义内容必须写入真实 XHTML，
不能只存在于 CSS `content` 中。Calibre 转换必须使用临时 AZW3 和原子替换，失败时
保留 Kindle EPUB、报告及已有有效 AZW3。
```

- [ ] **Step 4: Check documentation and run the complete automated suite**

Run:

```powershell
rg -n -- "--kindle|Kindle-Scribe|Kindle Scribe|ebook-convert|kindle_scribe" README.md AGENTS.md
git diff --check
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: both documents describe the command/dependency/outputs; `git diff --check` is clean; the full suite reports zero failures.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md AGENTS.md
git commit -m "docs: document Kindle Scribe builds"
```

---

### Task 6: Build and validate the complete Featured Kindle sample

**Files:**
- Generated, ignored: `output/epub/SCP基金会档案精选-Kindle.epub`
- Generated, ignored: `output/azw3/SCP基金会档案精选-Kindle.azw3`
- Generated, ignored: `output/reports/SCP基金会档案精选-Kindle-report.json`
- Generated, ignored: `output/verification/SCP基金会档案精选-Kindle-roundtrip.epub`

**Interfaces:**
- Consumes: installed Calibre `ebook-convert`/`ebook-meta`, the cached Featured pages/assets, and the finished `--kindle` implementation.
- Produces: a complete Kindle Scribe sample plus fresh structural and metadata evidence; no generated file is committed.

- [ ] **Step 1: Confirm the full automated suite immediately before the sample build**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Build the complete Featured Kindle EPUB and AZW3**

Run:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle
```

Expected: exit code 0 and two `Wrote` lines for the Kindle EPUB and AZW3.

- [ ] **Step 3: Verify files, report, EPUB structure, and forbidden Kindle CSS patterns**

Run:

```powershell
@'
from pathlib import Path
from zipfile import ZipFile
import json

epub = Path('output/epub/SCP基金会档案精选-Kindle.epub')
azw3 = Path('output/azw3/SCP基金会档案精选-Kindle.azw3')
report = json.loads(
    Path('output/reports/SCP基金会档案精选-Kindle-report.json').read_text(encoding='utf-8')
)
assert epub.stat().st_size > 0
assert azw3.stat().st_size > 0
assert report['output_path'] == str(epub.resolve()) or report['output_path'] == str(epub)
assert report['page_count'] == 364
assert report['missing_assets'] == []
with ZipFile(epub) as archive:
    assert archive.testzip() is None
    css = archive.read('OEBPS/styles/book.css').decode('utf-8').lower()
    chapter_names = [name for name in archive.namelist() if name.startswith('OEBPS/text/')]
    assert len(chapter_names) == 364
    for token in ('display: grid', 'display: flex', '::before', '::after', 'linear-gradient'):
        assert token not in css
print(f'epub_bytes={epub.stat().st_size}')
print(f'azw3_bytes={azw3.stat().st_size}')
print(f'pages={report["page_count"]}')
print(f'missing_pages={len(report["missing_pages"])}')
'@ | .\.venv\Scripts\python.exe -
```

Expected: no assertion failure; current cached Featured input reports 364 pages and zero missing assets. Upstream 404 pages remain accurately listed rather than being hidden.

- [ ] **Step 4: Verify Calibre can read AZW3 metadata**

Run:

```powershell
ebook-meta 'output\azw3\SCP基金会档案精选-Kindle.azw3'
```

Expected: exit code 0 with title `SCP基金会档案精选` and author `SCP基金会`.

- [ ] **Step 5: Round-trip AZW3 back to EPUB and inspect the package**

Run:

```powershell
New-Item -ItemType Directory -Force 'output\verification' | Out-Null
ebook-convert 'output\azw3\SCP基金会档案精选-Kindle.azw3' 'output\verification\SCP基金会档案精选-Kindle-roundtrip.epub' --output-profile=kindle_scribe
@'
from pathlib import Path
from zipfile import ZipFile

path = Path('output/verification/SCP基金会档案精选-Kindle-roundtrip.epub')
with ZipFile(path) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    assert any(name.endswith('.opf') for name in names)
    assert any(name.endswith(('.ncx', 'nav.xhtml')) for name in names)
    assert any('cover' in name.lower() for name in names)
    assert len([name for name in names if name.endswith(('.xhtml', '.html'))]) >= 364
print(f'roundtrip_bytes={path.stat().st_size}')
'@ | .\.venv\Scripts\python.exe -
```

Expected: both commands exit 0; the round-tripped EPUB is a valid ZIP package with metadata, navigation, cover content, and at least the original chapter count.

- [ ] **Step 6: Confirm source status and hand off the physical-device check**

Run:

```powershell
git status --short
```

Expected: no generated output is listed because output/cache paths are ignored; the pre-existing untracked `uv.lock` remains untouched. Report the Kindle EPUB/AZW3 paths, sizes, page/missing counts, full-test result, metadata result, and round-trip result. Ask the user to inspect representative normal pages, floating-image pages, tables, tab sections, and anomaly classification bars on the physical Kindle Scribe.
