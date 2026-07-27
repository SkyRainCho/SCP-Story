# Kindle Scribe Stability Design

## Goal

Add an opt-in Kindle Scribe stability build that reduces renderer memory pressure
without changing the existing standard EPUB or current high-quality Kindle build.
The stable build must preserve readable image detail on a roughly 1860 by 2480,
300 ppi display while preventing image-heavy XHTML documents from presenting an
unbounded decoded-image working set to the reader.

The new build will be invoked with `--kindle-stable` and will generate:

- `output/epub/SCP基金会档案精选-Kindle-Scribe.epub`;
- `output/azw3/SCP基金会档案精选-Kindle-Scribe.azw3`;
- `output/reports/SCP基金会档案精选-Kindle-Scribe-report.json`.

The existing non-Kindle and `--kindle` commands, CSS, reports, and filenames remain
unchanged.

## Evidence and Failure Model

The current Kindle EPUB contains 1,038 raster images. Their compressed payload is
about 373 MiB, but their estimated RGBA decode footprint is about 5.6 GiB. Thirteen
XHTML documents reference more than 100 MiB of decoded image data.

The worst current documents include:

- `secure-facilities-locations--appendix-group`: 91 images, about 721 MiB decoded;
- `locations-of-interest`: 51 unique images, about 433 MiB decoded;
- `scp-9777`: 25 images, about 396 MiB decoded;
- `scp-9000`: 14 unique images, about 323 MiB decoded;
- `secure-facility-dossier-area-12`: 24 unique images, about 217 MiB decoded.

One packaged PNG is 9449 by 5670 pixels. Although its compressed size is about
1 MiB, decoding it as RGBA requires about 204 MiB. Lowering JPEG quality or PNG
compression without changing pixel dimensions therefore cannot address the main
failure mode. The working hypothesis is renderer memory exhaustion while Kindle
prepares the current and adjacent pages.

## Approaches Considered

### Quality-only recompression

This reduces transfer and storage size but leaves `width * height * 4` decode
memory unchanged. It is insufficient for the observed crashes.

### One global pixel cap

A global 1800 by 2400 bounding box matches the Scribe screen well and removes
obviously wasted resolution. However, pages containing dozens of images can still
exceed 100 MiB after that cap.

### Context-aware variants with a per-page budget

This is the selected approach. It combines screen-sized default images,
small variants for thumbnail contexts, and smaller page-specific variants only
where a document remains over budget. It preserves higher-resolution use of a
shared source image on other pages and avoids risky automatic splitting of
navigation, footnotes, tables, and inline anchors.

Structural XHTML splitting is reserved for a later targeted fix if a page cannot
meet the hard budget even at the minimum stable image cap.

## Stable Build Mode

The CLI will add `--kindle-stable`. It implies Kindle page preparation, Kindle CSS,
image validation, and AZW3 conversion, but selects a distinct output suffix
`-Kindle-Scribe` and enables the stability policy.

`build_volume` will represent Kindle behavior with an explicit build mode rather
than two loosely related booleans. The supported modes are:

- standard EPUB;
- current high-quality Kindle;
- Kindle Scribe stable.

The public CLI remains simple: no flag uses standard EPUB, `--kindle` uses the
existing behavior, and `--kindle-stable` uses the new behavior. Passing both
Kindle flags is rejected with a clear argument error.

## Image Policy

### Display-aware limits

The stable policy uses these limits while preserving aspect ratio:

- facility grid icons (`facility-icon-epub`): maximum 384 by 384 pixels;
- ordinary images: maximum bounding box 1800 by 2400 pixels;
- adaptive page variants: successively smaller bounding boxes selected from
  1600 by 2200, 1400 by 1900, 1200 by 1600, 1000 by 1400, and 800 by 1100.

The 384-pixel facility image is a separate asset variant. The source asset remains
available at the ordinary-image resolution when another chapter uses it as a
larger illustration.

### Encoding

- JPEG inputs that require rewriting are saved as baseline RGB JPEG at quality 85
  with optimization enabled.
- PNG inputs remain PNG so transparency, line art, and text rendering are not
  damaged by a photographic-format heuristic.
- WebP and BMP continue to be converted to PNG, now with the stable size limit
  applied during the same decode operation.
- Animated GIFs are converted to a static first-frame PNG in stable mode.
- Static GIFs may remain GIF when they already satisfy the selected size limit.
- EXIF orientation is applied before dimensions are measured and pixels are saved.
- Existing SVG safety validation remains in place. Its current 1400-pixel
  landscape and 1600-pixel portrait render limits are already below the stable
  ordinary-image bounds.

Images that already satisfy the selected dimensions and format rules are reused
byte-for-byte where possible. Generated variants use deterministic filenames and
are deduplicated by source href, variant purpose, and bounding box.

## Per-page Decode Budget

The stable asset preparation stage will inspect local `<img>` references in each
processed page. Each unique referenced raster contributes
`output_width * output_height * 4` bytes to the estimated decode footprint.
Repeated use of the same asset in one XHTML counts once.

The thresholds are:

- target: at most 64 MiB per XHTML;
- warning range: more than 64 MiB and at most 96 MiB;
- hard limit: more than 96 MiB.

Asset selection begins with the default ordinary-image bound and the fixed
thumbnail variants. When a page exceeds the target, only that page receives the
largest adaptive variant set that brings it under 64 MiB. If no available bound
meets the target but the minimum bound is at or below 96 MiB, the build continues
and records a warning. If a page remains above 96 MiB at the minimum bound, the
stable build stops before overwriting an existing stable EPUB or AZW3 and reports
the offending slugs and estimates. That page then requires a targeted structural
split rather than further automatic quality loss.

CSS background assets are validated as today but are not included in the first
decode-budget calculation because their rendered dimensions cannot be inferred
reliably from the sanitized XHTML. The report identifies them separately so they
can be added to a later policy if measurements show they are material.

## Page-specific Reference Rewriting

The current Kindle preparation creates one replacement href per source asset.
Stable mode will extend this to page-specific replacements:

1. Parse each page's local image elements and their classes.
2. Determine the default, thumbnail, or adaptive variant required for each
   `(page slug, source href)` reference.
3. Prepare each unique asset variant once.
4. Rewrite only the matching page references to the selected variant href.
5. Preserve the current missing-image fallback when source validation or variant
   encoding fails.

This keeps the SCP-6183 opaque rotated symbol variant and anomaly-diamond handling
compatible with the new variant planner rather than replacing their special rules.

## Stable CSS Safety Pass

Stable mode will remove runtime-only declarations that cannot contribute useful
static Kindle content: `animation`, `animation-*`, `transition`, `filter`, and
`backdrop-filter`. Fixed or sticky positioning will be converted to normal flow.
The pass applies to inline styles and retained page `<style>` rules, after the
semantic HTML transformations have materialized generated labels and tab content.

The existing high-quality Kindle CSS remains unchanged. The stable CSS file will
reuse it and add no Grid, Flexbox, generated-content semantics, or script behavior.

## Reporting

The stable report adds a `kindle_performance` object containing:

- display profile and image bounds;
- target and hard decode budgets;
- image count and estimated decoded bytes before and after optimization;
- animated GIFs made static;
- generated thumbnail and adaptive variant counts;
- per-page entries for pages above 32 MiB after optimization;
- warnings for pages in the 64-to-96 MiB range;
- any pages that caused the hard-limit failure.

The existing report fields remain unchanged. Missing or invalid images continue to
be recorded in `missing_assets`.

## Failure and Atomicity

Stable planning and the hard-budget check happen before EPUB writing. A budget
failure therefore leaves any existing stable EPUB and AZW3 untouched. Asset
variants are written to a stable-mode-specific processed directory so they cannot
collide with current Kindle assets.

Calibre conversion keeps the existing temporary-AZW3 and atomic-replacement
behavior. A conversion failure preserves the successfully built stable EPUB,
stable report, and any previous valid stable AZW3.

## Testing

`tests/test_kindle.py` will cover:

- 384-pixel facility variants without reducing the same source on other pages;
- 1800 by 2400 ordinary image bounds and aspect-ratio preservation;
- JPEG quality-path output, PNG transparency preservation, EXIF orientation, and
  animated-GIF first-frame conversion;
- deterministic variant deduplication;
- per-page decoded-byte estimation and adaptive cap selection;
- warning and hard-limit behavior;
- coexistence with SCP-6183 and anomaly-diamond variants;
- stable CSS removal of runtime-only declarations.

`tests/test_cli.py` and `tests/test_pipeline.py` will cover flag exclusivity,
stable output filenames, stable report selection, separate asset directories,
converter invocation, and preservation of standard and current Kindle behavior.

`tests/test_epub.py` will cover the optional stable performance report payload
without changing ordinary report output.

Final verification will run the complete test suite and build the Featured stable
EPUB/AZW3. The produced EPUB must satisfy all of the following:

- the facilities page retains 92 cards, 91 visible icons, the text-only Site-5,
  and all 40 facility child chapters;
- the facilities page estimated decode footprint is below 64 MiB;
- no XHTML exceeds the 96 MiB hard limit;
- all generated image references resolve to packaged assets;
- the EPUB and AZW3 are nonempty and Calibre can read the AZW3 metadata;
- the existing standard EPUB and `-Kindle` filenames are not overwritten.

## Non-goals

This first stable-mode implementation does not change source fetching, manifest
selection, linked appendices, non-Kindle assets, or the current high-quality
Kindle output. It does not automatically divide arbitrary narrative pages into
new navigation entries. Targeted page splitting remains the fallback for a page
that cannot meet the hard budget at the minimum stable resolution.
