# Featured Appendix Design

## Goal

Add an appendix as the final top-level entry of the featured SCP EPUB. The
appendix provides Foundation reference material without introducing unrelated
links or changing Series book behavior.

## Scope

The appendix is enabled only by `config/featured-scp.yaml`. It contains these
first-level entries in order:

1. 项目等级
2. 安保许可等级
3. 基金会设施
4. 基金会部门
5. 人事档案
6. O5指挥部档案
7. 相关组织
8. 相关地点

`附录` appears after every featured SCP entry and is a peer of those entries in
the EPUB navigation.

## Source Handling

Regular appendix pages retain their source document body.

`安保许可等级` includes only the `简介` tab and removes its redundant single-tab
wrapper and heading.

`基金会设施` retains its source document and adds one child for every link whose
visible text begins with `安保设施档案：`. Links are read in source order and
deduplicated by normalized destination URL. The current source has 41 matches
and 40 unique destinations. No URL pattern filtering is applied, so links to
nonstandard but explicitly labelled destinations remain included.

`人事档案` and `O5指挥部档案` are navigation groups. Each direct Wikidot tab
becomes a child EPUB page titled with that tab label. The parent does not repeat
all panel content in its own body.

## Design

Introduce a featured-only appendix configuration that declares the root title,
ordered source pages, and the extraction mode for each page. The pipeline
expands this declaration into normal manifest entries before fetching. Three
bounded modes cover the required behavior:

- `page`: fetch and transform one source page.
- `facility-links`: fetch one source page and add only explicitly labelled
  facility dossier links as its direct children.
- `tabs-as-pages`: fetch one source page, create a group parent, and create one
  child document per direct tab panel.

The existing tab filter and single-tab unwrap options are reused for `安保许可等级`.
Facility links and tab panels are expanded one level only. They do not recurse
through links found in the resulting child pages.

## Failure Handling

If an appendix child page cannot be fetched, omit only that child and list the
URL in the existing build report. The appendix root and successfully fetched
siblings remain available. A source page with no matching facility links or no
tab panels remains a normal appendix page or empty navigation group; it never
falls back to collecting arbitrary links.

## Verification

Tests cover configuration parsing, final manifest order and levels, source-order
facility link extraction with URL deduplication, tab panel child generation,
single-tab unwrapping for `安保许可等级`, and protection against ordinary internal
links being collected. A featured build verifies that the appendix is the final
top-level TOC entry and that the generated child documents are present.
