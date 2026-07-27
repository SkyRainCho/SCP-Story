# Featured Facility Static Grid Design

## Goal

Convert the interactive site and area grids on the Featured appendix page
`基金会设施` into static EPUB content. Every facility card must show its source
icon when one exists and its complete identifier, while hover/focus popovers and
their hidden detail content are removed. Existing facility dossier child
chapters remain unchanged.

## Root Cause

The source page does not place its visible emblem in the card as an `<img>`.
Instead, each thumbnail depends on an inline `--custom-icon` CSS variable and a
`::before` background. EPUB sanitization correctly removes that dynamic inline
style, so the thumbnail loses its icon. The same source card contains a real
`<img>` inside a `.slideover` panel, but that image is only visible when the
source `:hover` or `:focus` CSS opens the panel.

The generated EPUB contains no scripts and no event-handler attributes. The
observed popup is entirely caused by retained CSS selectors such as
`.s-wrapper > a:hover + .slideover` acting on the retained source markup.

## Design

Add a page-specific DOM normalization for `secure-facilities-locations` during
HTML transformation. It will replace each source `.site-grid` with an EPUB
table using four cells per row.

For each `.s-wrapper` card, the normalizer will:

1. Read the complete visible identifier from `.thumbnail .type`, including the
   nested `.number` text.
2. Move or copy the first `.slideover img` into the static card cell.
3. Create a compact static card containing only that image and identifier.
4. Omit the source `/` trigger link, `.slideover`, `.socontent`, descriptions,
   collapsible blocks, and related-file links.

The generated markup will use dedicated classes such as
`facility-grid-epub`, `facility-card-epub`, `facility-icon-epub`, and
`facility-label-epub`. It will not retain `s-wrapper`, `thumbnail`, or
`slideover`, so the source hover/focus selectors cannot match even if they
remain in the page stylesheet.

The table layout avoids Grid, Flexbox, CSS masks, generated content, and
structural pseudo-classes. Four columns match the current Kindle Scribe page
width. Incomplete final rows will contain only the remaining cells; no empty
fake facility cards are generated.

## Missing Source Icons

The cached source currently contains 92 facility cards but only 91 actual
popover images. Site-5 uses an unresolved template icon variable and provides
no image element. Its static card will therefore show the complete `site-5`
identifier without inventing or substituting an unrelated emblem.

## Data and Navigation Preservation

Facility dossier discovery happens from the fetched source HTML before page
transformation. Removing links from popover markup therefore does not alter the
40 existing `appendix-facility` manifest entries, their source order, or their
parent slug.

Image normalization runs after the static-grid conversion. The promoted images
remain ordinary `<img src>` elements, so the existing asset pipeline downloads,
localizes, Kindle-normalizes, packages, and rewrites them without a new asset
mechanism.

The introductory text, `站点列表` and `区域列表` headings, and selected
`设施种类定义` tab remain unchanged.

## Failure Handling

If an individual card has no image, the card remains text-only. If its image
download fails, existing missing-asset handling removes or preserves alt text
according to the normal asset pipeline and records the source URL in the build
report. A malformed source card without an identifier is omitted rather than
creating a blank interactive artifact.

The normalizer is restricted to the `secure-facilities-locations` slug and does
not change ordinary grids, hover effects, or popovers on other pages.

## Testing

Transformation tests will cover:

- site and area grids become four-column EPUB tables;
- real popover images are promoted into static cells and registered as assets;
- nested number text becomes a visible complete identifier;
- Site-5-style image-less cards remain text-only;
- triggers, `javascript:` links, `.slideover`, hidden descriptions, and source
  interactive classes are removed;
- unrelated pages with similar class names are not modified.

Pipeline and build verification will confirm that:

- the real facilities page produces 92 cards, 91 packaged images, and two
  static tables;
- no facility popover elements or interactive trigger links remain;
- all 40 facility dossier child chapters remain in the manifest/navigation;
- the full test suite passes;
- the rebuilt Kindle EPUB and AZW3 are valid and use the expected metadata.
