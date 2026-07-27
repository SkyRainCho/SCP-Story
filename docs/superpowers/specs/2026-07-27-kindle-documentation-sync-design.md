# Kindle Documentation Sync Design

## Goal

Synchronize `README.md` and `AGENTS.md` with the current Kindle build modes and
the stable Kindle Scribe image policy. The documentation must describe durable
commands, output contracts, implementation constraints, and test requirements
without embedding one-off artifact sizes or measured page-memory results.

This is a documentation-only change. It does not alter Python code, tests, cached
pages, or generated EPUB/AZW3 artifacts.

## Audience Separation

`README.md` is user-facing. It will explain which command to run, what each Kindle
mode produces, and the practical behavior of the Scribe stability policy in plain
language.

`AGENTS.md` is contributor-facing. It will define invariants that future code
changes must preserve, including mode isolation, image encoding rules, context
classification, reporting, and required regression coverage.

## README Changes

The environment requirement will state that Calibre `ebook-convert` is required
for both `--kindle` and `--kindle-stable` AZW3 generation.

The existing Kindle sections will distinguish:

- `--kindle`: the current high-quality KF8/AZW3 edition, producing files with the
  `-Kindle` suffix;
- `--kindle-stable`: the Kindle Scribe stability edition, producing files with the
  `-Kindle-Scribe` suffix.

The stable section will document these durable rules:

- generated raster variants use grayscale encoding;
- opaque JPEG/PNG variants use 8-bit luminance (`L`), while transparent PNG/GIF
  variants preserve alpha with grayscale-plus-alpha (`LA`);
- grayscale encoding reduces storage and image-read pressure but does not replace
  pixel bounds or the conservative per-page decode budget;
- facility icons use a maximum 384 by 384 bound;
- `locations-of-interest` badges identified from their existing badge containers
  use a maximum 320 by 320 bound;
- the non-badge images on `locations-of-interest`, including the maps, retain the
  800 by 1100 adaptive bound;
- ordinary stable images use the current 1800 by 2400 maximum and page-adaptive
  fallback sequence;
- the target and hard per-XHTML decode budgets remain 64 MiB and 96 MiB;
- animated GIFs are frozen to their first frame and runtime-only CSS features are
  removed in stable mode;
- stable reports expose the encoding profile and grayscale/facility/location
  variant counts.

The README will not record current EPUB/AZW3 byte sizes, percentage reductions,
the current number of badges, or measured decoded-byte values. Those values can
change when external wiki content changes.

## AGENTS Changes

The build-command section will retain the current `--kindle` command and add the
explicit `--kindle-stable` command with its `-Kindle-Scribe` EPUB, AZW3, and report
paths. It will state that the two modes are isolated and mutually exclusive, and
that standard EPUB behavior remains unchanged when neither flag is used.

The contributor constraints will specify:

- stable raster output is `L` or `LA` grayscale and transparency must not be
  flattened;
- no thresholding, one-bit conversion, dithering, automatic contrast enhancement,
  or similar irreversible e-ink preprocessing is introduced without a separate
  design and visual verification;
- decoded-image estimates remain conservatively calculated at four bytes per
  pixel even for grayscale assets;
- facility icons remain 384 by 384;
- `locations-of-interest` badges remain 320 by 320 and are recognized only on
  that page through `enlarge`, `legend-box`, or combined
  `image-container floatright` ancestor contexts;
- the page's non-badge images retain the 800 by 1100 adaptive spec so badge
  optimization cannot make maps grow back to the ordinary bound;
- fixed facility and location-badge specs are not overwritten by page-adaptive
  planning;
- deterministic variant naming, deduplication, missing-asset behavior, reporting,
  stable output isolation, and atomic AZW3 replacement are preserved.

The testing section will require coverage in `tests/test_kindle_stable.py` for
grayscale modes and alpha preservation, ancestor-context classification, map
exclusion, fixed-spec preservation, deduplication, decode budgets, warnings, and
report counts. `tests/test_kindle.py` must cover direct versus ancestor image-class
metadata, while `tests/test_pipeline.py`, `tests/test_cli.py`, and
`tests/test_epub.py` retain integration and non-stable regression responsibilities.

## Alternatives Rejected

A separate recent-changes section is rejected because it would duplicate the
existing build-mode sections and age quickly. An exhaustive implementation guide
is also rejected because source code and design documents already contain those
details; README and AGENTS should state user contracts and contributor invariants.

## Verification

The documentation edit will be checked with `git diff --check`. Commands, output
paths, dimensions, report field names, and test filenames will be compared against
the current CLI, `kindle_stable.py`, and test suite. Focused CLI and stable tests
will run to ensure documented command-mode assumptions still match executable
behavior, even though the change itself is documentation-only.

## Non-goals

This task does not add a changelog, publish benchmark numbers, document internal
functions line by line, change build defaults, regenerate artifacts, or edit the
already-approved feature design documents beyond adding this documentation-sync
specification.
