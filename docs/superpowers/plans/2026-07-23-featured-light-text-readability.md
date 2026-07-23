# Featured Light-Text Readability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the intended dark backgrounds behind light text in the Featured EPUB without recoloring intentionally hidden source text.

**Architecture:** Normalize source CSS before the existing selector-matching pass, resolve only numeric RGB custom properties used by retained rules, and make generic blockquote/image backgrounds transparent so nested theme panels remain visible. Keep all behavior in the shared transform and EPUB stylesheet layers, with regression coverage for each root cause.

**Tech Stack:** Python 3.11+, BeautifulSoup, regular expressions, pytest, EPUB ZIP inspection, Playwright CLI for final computed-style auditing.

---

## File map

- `src/scp_epub/transform.py`: clean CSS rule boundaries and resolve numeric CSS custom properties before emitting page styles.
- `src/scp_epub/epub.py`: stop global blockquote and image-block backgrounds from covering dark ancestor panels.
- `tests/test_transform.py`: reproduce malformed `@import`/comment selectors, numeric variable loss, and intentional hidden text preservation.
- `tests/test_epub.py`: verify the scoped base CSS rules use transparent backgrounds.

### Task 1: Make retained page CSS self-contained and syntactically valid

**Files:**
- Modify: `tests/test_transform.py`
- Modify: `src/scp_epub/transform.py:79-105`
- Modify: `src/scp_epub/transform.py:1173-1210`
- Modify: `src/scp_epub/transform.py:1630-1660`

- [ ] **Step 1: Add failing tests for standalone at-rules and comments**

Add these tests near `test_preserves_document_styles_that_target_page_content`:

```python
def test_page_styles_do_not_attach_import_to_following_selector():
    html = """
    <html><head><style>
      @import url("https://fonts.example/mono.css");
      .parawatch blockquote { background: #1a1a1a; color: #f2f2f2; }
    </style></head><body><div id="page-content">
      <div class="parawatch"><blockquote>深色论坛正文。</blockquote></div>
    </div></body></html>
    """

    result = transform_page(page_ref("scp-6838"), html, BASE_URL)
    style_text = soup_fragment(result.xhtml).find("style").get_text()

    assert "import url" not in style_text
    assert ".parawatch blockquote {background: #1a1a1a; color: #f2f2f2;}" in style_text


def test_page_styles_do_not_attach_comments_to_following_selector():
    html = """
    <html><head><style>
      /* AUDITOR PANEL */
      .auditor-content { background: #001600; color: #c3c3c3; }
    </style></head><body><div id="page-content">
      <div class="auditor-content">审计正文。</div>
    </div></body></html>
    """

    result = transform_page(page_ref("scp-9100"), html, BASE_URL)
    style_text = soup_fragment(result.xhtml).find("style").get_text()

    assert "/*" not in style_text
    assert ".auditor-content {background: #001600; color: #c3c3c3;}" in style_text
```

- [ ] **Step 2: Run the new boundary tests and verify RED**

Run:

```powershell
pytest -q tests/test_transform.py::test_page_styles_do_not_attach_import_to_following_selector tests/test_transform.py::test_page_styles_do_not_attach_comments_to_following_selector
```

Expected: both tests fail because `import url(...)` or comment text is currently emitted as part of the selector.

- [ ] **Step 3: Add failing tests for direct, aliased, and fallback numeric variables**

```python
def test_page_styles_resolve_numeric_css_custom_property_aliases():
    html = """
    <html><head><style>
      :root {
        --dark-panel: 26, 26, 26;
        --panel-alias: var(--dark-panel);
      }
      .blackboard {
        background: rgb(var(--panel-alias));
        color: rgb(var(--missing-text, 255, 255, 255));
      }
    </style></head><body><div id="page-content">
      <div class="blackboard">黑板正文。</div>
    </div></body></html>
    """

    result = transform_page(page_ref("secure-facility-dossier-site-81tg"), html, BASE_URL)
    style_text = soup_fragment(result.xhtml).find("style").get_text()

    assert "background: rgb(26, 26, 26)" in style_text
    assert "color: rgb(255, 255, 255)" in style_text
    assert "var(--panel-alias)" not in style_text
    assert "var(--missing-text" not in style_text
```

- [ ] **Step 4: Run the numeric-variable test and verify RED**

Run:

```powershell
pytest -q tests/test_transform.py::test_page_styles_resolve_numeric_css_custom_property_aliases
```

Expected: FAIL because retained page rules currently preserve unresolved `var(...)` calls.

- [ ] **Step 5: Implement CSS source normalization and numeric variable resolution**

Add focused regexes near the existing CSS regex constants:

```python
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
CSS_SEMICOLON_AT_RULE_RE = re.compile(
    r"@(import|charset|namespace)\b[^;{}]*;",
    re.IGNORECASE,
)
CSS_NUMERIC_TRIPLET_RE = re.compile(
    r"\d+(?:\.\d+)?\s*,\s*\d+(?:\.\d+)?\s*,\s*\d+(?:\.\d+)?"
)
```

Update page-style extraction to normalize source CSS once and resolve numeric variables in emitted bodies:

```python
def _applicable_page_styles(soup: BeautifulSoup, page_content: Tag) -> str:
    rules: list[str] = []
    seen_rules: set[str] = set()
    targets = _page_style_targets(page_content)
    custom_properties = _numeric_css_custom_properties(soup)

    for style in soup.find_all("style"):
        css_text = _css_rule_source(style.get_text("\n", strip=True))
        for rule in _matching_css_rules(css_text, targets, custom_properties):
            if rule in seen_rules:
                continue
            seen_rules.add(rule)
            rules.append(rule)

    return "\n".join(rules)


def _css_rule_source(css_text: str) -> str:
    without_comments = CSS_COMMENT_RE.sub(" ", css_text)
    return CSS_SEMICOLON_AT_RULE_RE.sub(" ", without_comments)
```

Extend `_matching_css_rules` with a `custom_properties: dict[str, str]` parameter and resolve each retained body before appending it:

```python
body = _resolve_numeric_css_variables(match.group("body").strip(), custom_properties)
```

Replace `_numeric_css_custom_properties` with an alias-aware implementation:

```python
def _numeric_css_custom_properties(soup: BeautifulSoup) -> dict[str, str]:
    raw_properties: dict[str, str] = {}
    for style in soup.find_all("style"):
        css_text = CSS_COMMENT_RE.sub(" ", style.get_text("\n", strip=True))
        for match in CSS_CUSTOM_PROPERTY_VALUE_RE.finditer(css_text):
            raw_properties[match.group("name").casefold()] = re.sub(
                r"\s*!important\s*$", "", match.group("value"), flags=re.IGNORECASE
            ).strip()

    resolved: dict[str, str] = {}
    resolving: set[str] = set()

    def resolve(name: str) -> str | None:
        if name in resolved:
            return resolved[name]
        if name in resolving:
            return None
        value = raw_properties.get(name)
        if value is None:
            return None
        if CSS_NUMERIC_TRIPLET_RE.fullmatch(value):
            resolved[name] = value
            return value
        variable = CSS_VAR_FUNCTION_RE.fullmatch(value)
        if variable is None:
            return None
        resolving.add(name)
        replacement = resolve(variable.group("name").casefold())
        resolving.remove(name)
        fallback = (variable.group("fallback") or "").strip()
        result = replacement or (fallback if CSS_NUMERIC_TRIPLET_RE.fullmatch(fallback) else None)
        if result is not None:
            resolved[name] = result
        return result

    for property_name in raw_properties:
        resolve(property_name)
    return resolved


def _resolve_numeric_css_variables(style_body: str, custom_properties: dict[str, str]) -> str:
    return CSS_VAR_FUNCTION_RE.sub(
        lambda variable: custom_properties.get(
            variable.group("name").casefold(),
            (variable.group("fallback") or "").strip() or variable.group(0),
        ),
        style_body,
    )
```

- [ ] **Step 6: Run the targeted transform tests and verify GREEN**

Run:

```powershell
pytest -q tests/test_transform.py::test_page_styles_do_not_attach_import_to_following_selector tests/test_transform.py::test_page_styles_do_not_attach_comments_to_following_selector tests/test_transform.py::test_page_styles_resolve_numeric_css_custom_property_aliases tests/test_transform.py::test_preserves_document_styles_that_target_page_content tests/test_transform.py::test_anomaly_diamond_uses_last_resolved_css_variable_quadrant_color
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit the page-style extraction fix**

```powershell
git add -- src/scp_epub/transform.py tests/test_transform.py
git commit -m "fix: preserve dark page style backgrounds"
```

### Task 2: Stop generic EPUB panels from covering dark ancestors

**Files:**
- Modify: `tests/test_epub.py`
- Modify: `src/scp_epub/epub.py:170-185`
- Modify: `src/scp_epub/epub.py:212-250`

- [ ] **Step 1: Change the existing EPUB CSS test to require scoped transparent backgrounds**

Update `test_write_epub_includes_book_styles_for_wiki_tables_and_blockquotes` and add a separate image-block assertion:

```python
    blockquote_rule = re.search(r"blockquote,\s*\.blockquote\s*\{(?P<body>[^}]*)\}", css)
    assert blockquote_rule is not None
    assert "background: transparent;" in blockquote_rule.group("body")

    image_block_rule = re.search(r"\.scp-image-block\s*\{(?P<body>[^}]*)\}", css)
    assert image_block_rule is not None
    assert "background: transparent;" in image_block_rule.group("body")
```

Remove the old assertion requiring `background: #f8f8f8;` from the blockquote rule.

- [ ] **Step 2: Run the EPUB CSS test and verify RED**

Run:

```powershell
pytest -q tests/test_epub.py::test_write_epub_includes_book_styles_for_wiki_tables_and_blockquotes
```

Expected: FAIL because both rules currently force light backgrounds.

- [ ] **Step 3: Make the two generic backgrounds transparent**

In `BOOK_CSS`, change only these declarations:

```css
blockquote,
.blockquote {
  margin: 1em 3em;
  padding: 0.75em 1em;
  border: 1px dashed #999;
  background: transparent;
}

.scp-image-block {
  width: 300px;
  max-width: 100%;
  margin: 0.75em 0 1em;
  border: 1px solid #666;
  background: transparent;
  box-sizing: border-box;
}
```

- [ ] **Step 4: Run the EPUB CSS test and verify GREEN**

Run:

```powershell
pytest -q tests/test_epub.py::test_write_epub_includes_book_styles_for_wiki_tables_and_blockquotes tests/test_epub.py::test_write_epub_includes_book_styles_for_scp_image_blocks
```

Expected: both tests pass.

- [ ] **Step 5: Add a guard test for intentionally hidden source text**

Add to `tests/test_transform.py`:

```python
def test_does_not_recolor_explicit_source_white_text_without_a_dark_panel():
    html = """
    <html><body><div id="page-content">
      <p>档案正文。<span style="color: white">作者刻意隐藏的文字。</span></p>
    </div></body></html>
    """

    result = transform_page(page_ref("personnel-and-character-dossier"), html, BASE_URL)
    hidden = soup_fragment(result.xhtml).find("span", string="作者刻意隐藏的文字。")

    assert hidden["style"] == "color: white"
```

- [ ] **Step 6: Run the guard test**

Run:

```powershell
pytest -q tests/test_transform.py::test_does_not_recolor_explicit_source_white_text_without_a_dark_panel
```

Expected: PASS, proving the solution does not globally recolor white text.

- [ ] **Step 7: Commit the base CSS fix**

```powershell
git add -- src/scp_epub/epub.py tests/test_epub.py tests/test_transform.py
git commit -m "fix: inherit backgrounds in themed panels"
```

### Task 3: Verify, rebuild, and re-audit the Featured collection

**Files:**
- Verify: `src/scp_epub/transform.py`
- Verify: `src/scp_epub/epub.py`
- Verify: `tests/test_transform.py`
- Verify: `tests/test_epub.py`
- Generate, but do not commit: `output/epub/SCP基金会档案精选.epub`
- Generate, but do not commit: `output/reports/*featured*-report.json`

- [ ] **Step 1: Run the focused suites**

```powershell
pytest -q tests/test_transform.py tests/test_epub.py
```

Expected: all transform and EPUB tests pass with zero failures.

- [ ] **Step 2: Run the complete test suite**

```powershell
pytest -q
```

Expected: all repository tests pass with zero failures.

- [ ] **Step 3: Check patch formatting and repository scope**

```powershell
git diff --check
git status -sb
```

Expected: no diff errors; only the plan document is uncommitted if it has not yet been committed, and generated output remains ignored.

- [ ] **Step 4: Rebuild the Featured EPUB**

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured
```

Expected: exit code 0, `output/epub/SCP基金会档案精选.epub` regenerated, and the build report contains zero failed pages.

- [ ] **Step 5: Rerun the browser computed-style audit**

Extract and serve the rebuilt EPUB:

```powershell
$auditRoot = Join-Path (Resolve-Path -LiteralPath 'output').Path 'playwright\featured-light-text-final'
New-Item -ItemType Directory -Force -Path $auditRoot | Out-Null
Expand-Archive -LiteralPath 'output/epub/SCP基金会档案精选.epub' -DestinationPath $auditRoot -Force
$auditServer = Start-Process -FilePath python -ArgumentList '-m','http.server','8766','--bind','127.0.0.1' -WorkingDirectory $auditRoot -WindowStyle Hidden -PassThru
```

Open an isolated browser session:

```powershell
npx --yes --package @playwright/cli playwright-cli -s=featured-light-text-final open 'http://127.0.0.1:8766/OEBPS/nav.xhtml'
```

Run this function through `playwright-cli run-code`; it reads all XHTML manifest items and returns only visible light-on-light findings:

```javascript
async (page) => {
  const origin = "http://127.0.0.1:8766";
  const response = await page.request.get(origin + "/OEBPS/content.opf");
  const opf = await response.text();
  const hrefs = await page.evaluate((text) => {
    const xml = new DOMParser().parseFromString(text, "application/xml");
    return Array.from(xml.querySelectorAll("item"))
      .filter((item) => item.getAttribute("media-type") === "application/xhtml+xml")
      .map((item) => item.getAttribute("href"))
      .filter((href) => href && href.startsWith("text/"));
  }, opf);
  const documents = [];
  for (const href of hrefs) {
    await page.goto(origin + "/OEBPS/" + href, {waitUntil: "domcontentloaded"});
    const issue = await page.evaluate(() => {
      const rgb = (value) => {
        const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
        return match
          ? [Number(match[1]), Number(match[2]), Number(match[3]), match[4] === undefined ? 1 : Number(match[4])]
          : null;
      };
      const effectiveBackground = (element) => {
        let current = element;
        while (current) {
          const style = getComputedStyle(current);
          const color = rgb(style.backgroundColor);
          if (color && color[3] > 0.95) return {color, image: style.backgroundImage};
          if (style.backgroundImage && style.backgroundImage !== "none") {
            return {color: color || [255, 255, 255, 0], image: style.backgroundImage};
          }
          current = current.parentElement;
        }
        return {color: [255, 255, 255, 1], image: "none"};
      };
      const samples = [];
      const seen = new Set();
      for (const element of document.body.querySelectorAll("*")) {
        const text = Array.from(element.childNodes)
          .filter((node) => node.nodeType === Node.TEXT_NODE)
          .map((node) => node.textContent || "")
          .join(" ")
          .replace(/\s+/g, " ")
          .trim();
        if (!text || element.getClientRects().length === 0) continue;
        const foreground = rgb(getComputedStyle(element).color);
        if (!foreground || foreground[0] < 220 || foreground[1] < 220 || foreground[2] < 220) continue;
        const background = effectiveBackground(element);
        if (
          background.color[0] < 220 ||
          background.color[1] < 220 ||
          background.color[2] < 220 ||
          background.image !== "none"
        ) continue;
        const key = element.tagName + "|" + text.slice(0, 100);
        if (seen.has(key)) continue;
        seen.add(key);
        samples.push(text.slice(0, 80));
      }
      return {title: document.title, samples};
    });
    if (issue.samples.length) documents.push({href, ...issue});
  }
  return {scanned: hrefs.length, documents};
}
```

Close the browser and stop the verified audit server process after recording the result:

```powershell
npx --yes --package @playwright/cli playwright-cli -s=featured-light-text-final close
$serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($auditServer.Id)"
if ($serverProcess.CommandLine -notmatch 'http\.server.+8766') { throw 'Unexpected audit server process' }
Stop-Process -Id $auditServer.Id
```

Expected audit summary:

```text
scanned: 372
confirmed EPUB regressions: 0
source-equivalent intentional candidates: 1
intentional candidate: personnel-and-character-dossier--tab-1.xhtml
```

Specifically verify that these seven documents have zero findings:

```text
scp-6747
scp-6838
scp-8274
scp-9100
secure-facility-dossier-site-7
secure-facility-dossier-site-81tg
secure-facility-dossier-area-12
```

- [ ] **Step 6: Visually inspect representative repaired pages**

Restart the same explicit HTTP server if it was stopped, open the following pages in the isolated Playwright session, and use `screenshot` after each `goto`:

```powershell
npx --yes --package @playwright/cli playwright-cli -s=featured-light-text-visual open 'http://127.0.0.1:8766/OEBPS/text/0240-scp-6838.xhtml'
npx --yes --package @playwright/cli playwright-cli -s=featured-light-text-visual screenshot
npx --yes --package @playwright/cli playwright-cli -s=featured-light-text-visual goto 'http://127.0.0.1:8766/OEBPS/text/0260-scp-8274.xhtml'
npx --yes --package @playwright/cli playwright-cli -s=featured-light-text-visual screenshot
npx --yes --package @playwright/cli playwright-cli -s=featured-light-text-visual goto 'http://127.0.0.1:8766/OEBPS/text/0298-secure-facility-dossier-site-81tg.xhtml'
npx --yes --package @playwright/cli playwright-cli -s=featured-light-text-visual screenshot
npx --yes --package @playwright/cli playwright-cli -s=featured-light-text-visual close
```

Confirm in the screenshots:

```text
SCP-6838: Parawatch blockquote uses a dark background behind white text.
SCP-8274: terminal diary blocks and terminal image caption inherit the black terminal background.
Site-81TG: blackboard content renders white text on its dark panel.
```

- [ ] **Step 7: Confirm the final Git scope**

```powershell
git status -sb
git log -3 --oneline
```

Expected: the branch contains the plan commit plus the two focused implementation commits, and no files under `data/`, `output/`, or `.playwright-cli/` are staged or tracked.
