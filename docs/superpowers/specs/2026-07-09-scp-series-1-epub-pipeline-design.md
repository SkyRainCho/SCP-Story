# SCP Series 1 EPUB Pipeline Design

## Goal

Build a reusable EPUB production pipeline for the Chinese SCP Wiki "Series 1 Tales Edition" index. The first validation output is a sample volume covering `SCP-001` through `SCP-099`, including every related story or supplement listed under that range on the Tales Edition index page.

The pipeline must be reusable for later volumes and later SCP series.

## Scope For The First Sample

- Source index: `https://scp-wiki-cn.wikidot.com/scp-series-1-tales-edition`
- Output volume: `SCP-001` through `SCP-099`
- Include all `SCP-001` proposals from the `SCP-001` page's "按时间顺序展示" tab.
- Include the related stories and supplementary pages listed in the Tales Edition index under the `SCP-001` through `SCP-099` range.
- Preserve original images.
- Preserve useful original CSS and page styling as much as EPUB readers reasonably allow.
- Expand正文-related JavaScript-driven collapsible content.
- Convert JavaScript tab interfaces into readable static sections.
- Remove non正文 popups, license/attribution collapsibles, rating widgets, sidebars, admin blocks, and previous/next bottom navigation such as `« SCP-001 | SCP-002 | SCP-003 »`.
- Convert links to pages included in the same EPUB into internal EPUB links where possible.
- Keep links to pages outside the volume as external web links.

## Recommended Approach

Use an index-driven pipeline with a browser fallback.

The Tales Edition index is the source of truth for chapter order and related story placement. The pipeline first parses that index into a manifest, then fetches, transforms, and packages every manifest entry. Standard HTTP fetching is the default. Browser rendering is used only for pages whose required正文 cannot be recovered from static HTML.

This approach avoids missing related stories while still keeping the process fast enough for all later volumes.

## Architecture

### `indexer`

Parses the Tales Edition index page and produces a manifest for the requested volume.

Responsibilities:

- Extract the index page正文 rather than sidebar/navigation links.
- Preserve the index's visible hierarchy.
- Select entries belonging to `SCP-001` through `SCP-099`.
- Include related story and supplement links that appear in that selected range.
- Emit a manifest under `data/manifests/`.
- Record enough metadata for each entry to rebuild the EPUB table of contents.

### `scp001`

Handles the special `SCP-001` proposal page.

Responsibilities:

- Fetch and parse `https://scp-wiki-cn.wikidot.com/scp-001`.
- Select the "按时间顺序展示" tab.
- Extract all proposal links from that chronological list.
- Insert each proposal as a child chapter under `SCP-001`.
- Preserve the chronological proposal order from the source page.

### `fetcher`

Downloads and caches pages and assets.

Responsibilities:

- Read from workspace cache before downloading.
- Store raw page HTML under `data/raw/pages/`.
- Store raw images, CSS, fonts, and other assets under `data/raw/assets/`.
- Store sidecar metadata for cached files, including source URL, fetched timestamp, HTTP status, content type, and content hash.
- Retry transient failures with backoff.
- Rate-limit requests to avoid hammering Wikidot.
- Support `--refresh` to force re-download.
- Support `--missing-only` to fill gaps without replacing existing cache.
- Use browser fallback only when static fetching cannot produce required正文 content.

### `transformer`

Converts source HTML into EPUB-friendly XHTML.

Responsibilities:

- Extract only the page正文 from `#page-content`.
- Keep正文 headings, paragraphs, blockquotes, tables, images, links, and page-local style cues.
- Expand正文-related `collapsible-block` content.
- Remove non正文 collapsibles such as license/attribution boxes and admin blocks.
- Convert Wikidot/YUI tabs into sequential static sections with clear headings.
- Remove rating widgets, sidebars, page tools, comments, and previous/next bottom navigation.
- Rewrite image URLs to local EPUB asset paths.
- Rewrite links to pages included in the volume into internal EPUB links.
- Keep external links for pages outside the generated volume.
- Simplify CSS for EPUB compatibility while preserving visually meaningful正文 styling.

### `packager`

Builds the EPUB file from the processed manifest and XHTML chapters.

Responsibilities:

- Generate EPUB metadata.
- Build a navigable table of contents matching the selected index hierarchy.
- Package local images and CSS.
- Produce the sample EPUB under `output/epub/`.
- Produce a validation report under `output/reports/`.

## Workspace Storage Layout

The cache and output stay inside the workspace so future runs do not repeat downloads.

```text
C:\Users\Administrator\Documents\SCP-Story\
  config\
    series-1.yaml
  data\
    raw\
      pages\
      assets\
    manifests\
    processed\
  output\
    epub\
    reports\
  scripts\
  src\
  tests\
  docs\
```

Git will track scripts, configuration, documentation, tests, and small fixtures. Git will ignore large or generated workspace data such as `data/raw/`, `data/processed/`, and `output/`.

## Commands

The implementation should provide repeatable commands similar to:

```bash
python -m scp_epub index --config config/series-1.yaml
python -m scp_epub fetch --config config/series-1.yaml --volume 001-099 --missing-only
python -m scp_epub clean --config config/series-1.yaml --volume 001-099
python -m scp_epub build --config config/series-1.yaml --volume 001-099
```

`build` should run the full pipeline and write:

```text
output/epub/scp-series-1-001-099-tales.epub
output/reports/scp-series-1-001-099-report.json
```

## Validation Report

The report should include:

- Total manifest entries.
- Total EPUB chapters.
- Number of `SCP-001` proposals included.
- Pages fetched from cache versus network.
- Pages requiring browser fallback.
- Failed page downloads.
- Failed asset downloads.
- Images included in the EPUB.
- Links rewritten as internal EPUB links.
- Links left as external URLs.
- Any unresolved or suspicious links.

## Technology Choices

Use Python for the pipeline.

Libraries:

- HTTP fetching: `httpx`
- HTML parsing: `beautifulsoup4` with `lxml`
- EPUB packaging: `ebooklib`
- Browser fallback: Playwright, only when needed
- Tests: `pytest`

The implementation should keep modules small and focused around the architecture above.

## Testing Strategy

Automated tests should cover:

- Index parsing from a saved fixture.
- `SCP-001` chronological proposal extraction from a saved fixture.
- Cache path and metadata generation.
- Collapsible expansion and non正文 block removal.
- Tab conversion into static sections.
- Link rewriting for internal and external links.
- Basic EPUB packaging smoke test.

The sample build should also produce an indented JSON report so the first EPUB can be reviewed manually.

## Non-Goals For The First Sample

- Build every Series 1 volume in the first pass.
- Perfectly preserve interactive website behavior inside EPUB.
- Commit downloaded raw pages, images, or generated EPUB files to git.
- Translate, rewrite, or otherwise alter SCP正文 content beyond structural conversion needed for EPUB.

## Implementation Notes

- If static HTML contains all needed tab/collapsible content, prefer static parsing over browser fallback.
- If a page's CSS depends heavily on layout structures unsuitable for EPUB, preserve正文 styling and drop site chrome/layout rules.
- If a link target appears multiple times in the selected manifest, generate one chapter and map duplicate links to that chapter.
- If a story or supplement belongs visually under an SCP item in the index, place it under that SCP in the EPUB table of contents.
