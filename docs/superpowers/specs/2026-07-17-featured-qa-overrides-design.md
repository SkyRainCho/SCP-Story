# Featured QA Overrides Design

## Goal

Correct the page-specific content and layout defects listed in `QA.md` when
building `SCP基金会档案精选`, without broadening cleanup or linked-document
behavior for unrelated SCP pages.

## Scope

The change applies only when a configuration declares page overrides. The
initial configuration is `config/featured-scp.yaml`; the Series configurations
remain unchanged.

The listed fixes fall into three groups:

1. Remove page-specific non-article UI: terminal three-link navigation, author
   work lists, leading hub/author metadata, and the SCP-7069 adult-content
   notice.
2. Inline specified companion documents into their owning page without adding a
   `原文附属文档` navigation group: SCP-1898 photographs, the five SCP-7503
   iteration pages, SCP-6445's offset document, and Document 2814-Gamma.
3. Repair layout in SCP-6183, SCP-4612, and SCP-6599 against their original
   wiki pages using styles or structural normalization scoped to each page.

The initial override map is explicit:

- Terminal navigation: SCP-9928, SCP-7261, SCP-3662, SCP-5550, SCP-5514,
  SCP-5109, SCP-5494, and SCP-5109's generated linked-appendix children.
- Leading metadata: SCP-5464.
- Author work lists: SCP-6698, SCP-4233, and SCP-5595.
- Adult-content warning: SCP-7069.
- Layout profiles: SCP-6183, SCP-4612, and SCP-6599.
- Inline documents: SCP-1898, SCP-7503, SCP-6445 (displayed as SCP-⌘), and
  SCP-2814.

## Configuration Model

Add an optional `page_overrides` mapping to `AppConfig`, keyed by page slug.
Each immutable `PageOverride` supports these independent fields:

- `remove_terminal_navigation`: remove a qualifying trailing navigation block.
- `remove_leading_metadata`: remove configured leading metadata blocks.
- `remove_adult_content_warning`: remove only the designated content-warning
  block.
- `remove_author_work_list`: remove a qualifying author-work-list block.
- `layout_profile`: an explicit profile name for a page-specific layout repair.
- `inline_documents`: ordered `InlineDocumentSpec` values with a URL, title,
  insertion rule, and optional end boundary.

An inline insertion rule is one of:

- `after_text`: insert immediately after the element containing the configured
  text.
- `before_text`: insert immediately before the element containing the
  configured text.
- `append`: append after the main article body.

Each override is opt-in. A missing override produces the current behavior.

## Content Processing

During a featured build, the pipeline fetches only documents explicitly listed
in `inline_documents`. It transforms each companion document with the same
sanitization and asset collection path as its owner, then inserts the cleaned
fragment at the configured position. A simple section heading identifies the
inserted document when the source does not already provide one.

The companion pages are not appended to the manifest, do not appear in EPUB
navigation, and are excluded from automatic `原文附属文档` discovery for the
same source page. This keeps SCP-1898 and SCP-7503 readable as one article
while preserving the existing linked-appendix behavior elsewhere.

For SCP-7503, the configured offset pages `/offset/1` through `/offset/4` are
inserted in order after the main page, separated by stable section boundaries.
For SCP-6445, `/scp-6445/offset/1` is appended after the primary document. For
SCP-2814, Document 2814-Gamma is inserted before the `Footnotes` boundary.

## Cleanup Rules

The transformer removes a terminal navigation block only when all of these are
true: the override is enabled, the candidate is at the end of article content,
and its visible text matches the compact three-link navigation shape (including
the left/right guillemets). It does not remove similar text inside normal
paragraphs.

Author-work-list and leading-metadata cleanup use page-scoped DOM/text markers,
not a global phrase blacklist. The SCP-7069 warning removal is likewise scoped
to that page and its warning container. SCP-5109's terminal-navigation override
is inherited by its generated linked-appendix children; no other override is
inherited by child pages.

## Layout Profiles

`layout_profile` is resolved only after source-page inspection. Each profile
uses a stable slug-specific selector and may normalize a problematic float,
table, fixed-width container, or generated style rule. No profile contributes
CSS to unrelated pages.

## Verification

Tests will cover:

- configuration parsing and validation for overrides and inline documents;
- each cleanup operation retaining adjacent article text;
- inline document ordering, anchor placement, asset inclusion, and absence from
  EPUB navigation;
- SCP-7503's five-page sequence and SCP-2814's pre-footnote placement;
- scoped layout-profile output for SCP-6183, SCP-4612, and SCP-6599;
- regression coverage proving ordinary linked appendices and non-featured
  configurations are unchanged.

The implementation will also generate an offline cached featured sample and
inspect the relevant XHTML and navigation entries before integration.
