# Kindle Scribe Output Design

## Goal

Add an opt-in `--kindle` build path that preserves the existing EPUB build by
default, creates a Kindle-optimized EPUB for the selected volume, and converts
that EPUB to AZW3 with Calibre for USB transfer to a Kindle Scribe.

The first end-to-end sample is the complete `featured` volume. The design
prioritizes preserving the visual character of SCP Wiki pages while staying
within the more limited Kindle Format 8 rendering model used by AZW3.

## Confirmed User Workflow

The user runs:

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle
```

The generated AZW3 is transferred to Kindle Scribe through Calibre and USB.
Cloud delivery through Send to Kindle is outside this feature.

## Compatibility Boundary

Without `--kindle`, all existing paths, filenames, XHTML, CSS, reports, and
command behavior remain unchanged.

With `--kindle`, the build uses the same manifest, fetching, cleaning, linked
appendix, asset localization, cover, and navigation pipeline. Only the final
page preparation, stylesheet, EPUB naming, report naming, and Calibre
conversion are Kindle-specific.

The existing malformed Wikidot template-selector filtering described in
`docs/superpowers/specs/2026-07-16-calibre-template-css-design.md` remains the
general Calibre input-safety layer. This feature does not duplicate or replace
that filtering.

## Outputs

A successful Kindle build writes:

```text
output/epub/SCP基金会档案精选-Kindle.epub
output/azw3/SCP基金会档案精选-Kindle.azw3
output/reports/SCP基金会档案精选-Kindle-report.json
```

Other configured volumes use the same `<output_slug>-Kindle` suffix rule.
The normal EPUB and normal report are neither rebuilt nor overwritten by a
Kindle build.

## Architecture

### CLI and Pipeline

`--kindle` is a boolean option on the `build` command. It is not exposed as a
meaningful option on `index`, `manifest`, `fetch`, `clean`, or
`scan-linked-appendices`.

The pipeline follows the existing build flow until it has localized assets and
assembled `ProcessedPage` values. In Kindle mode it then:

1. Creates copied Kindle page values through a Kindle preparation function.
2. Writes the copied pages with the Kindle stylesheet to the `-Kindle.epub`
   path.
3. Writes a separate `-Kindle-report.json` describing that EPUB build.
4. Converts the optimized EPUB to a temporary AZW3 with Calibre.
5. Atomically replaces the final `-Kindle.azw3` after successful conversion.

Normal mode continues to pass the original pages and default stylesheet to the
existing EPUB writer.

### Module Boundaries

Create a focused Kindle module responsible for:

- copying and adjusting `ProcessedPage` XHTML for Kindle;
- loading the packaged Kindle stylesheet;
- locating `ebook-convert`;
- constructing and running the Calibre conversion command;
- temporary AZW3 cleanup and conversion errors.

Store the Kindle stylesheet as package data under `src/scp_epub/styles/`.
The existing `epub.py` writer gains only an optional stylesheet input whose
default is the current `BOOK_CSS`. It does not learn Calibre process behavior
or contain Kindle-specific XHTML transformations.

## Kindle XHTML and CSS Strategy

The Kindle output remains reflowable. It must not fix page dimensions, render
whole pages to images, or embed a Chinese body font.

The Kindle stylesheet preserves headings, SCP red accents, borders, captions,
tables, quotations, tab sections, content panels, and anomaly classification
information. It uses high-contrast borders and restrained grayscale
backgrounds that remain legible on an E Ink display.

Kindle mode applies these compatibility rules:

- replace layout dependencies on CSS Grid and Flexbox with blocks,
  inline-blocks, floats, or simple table-like presentation;
- avoid generated-content and structural pseudo selectors such as
  `::before`, `::after`, `:first-child`, and `:last-child`;
- turn clearance labels such as `PUBLIC`, `SECRET`, and `TOP SECRET` into real
  XHTML text derived from the anomaly bar's `clear-N` class;
- preserve the anomaly number, containment class, secondary class, disruption
  class, risk class, and clearance level as readable text;
- replace unsupported decorative danger-diamond effects with a simpler
  high-contrast badge while keeping the associated information;
- keep left and right SCP image blocks on the wide Scribe layout using
  percentage widths, with a single-column centered fallback for narrow
  layouts;
- keep semantic tables rather than asking Calibre to linearize them, while
  adding cell wrapping and stable borders;
- omit unreliable shadows, gradients, and transformations when a border or
  solid background conveys the same hierarchy;
- avoid fixed body font family and fixed body font size so Scribe reading
  controls continue to work.

Kindle page preparation operates on dataclass copies. It must not mutate
cached processed XHTML or alter a later normal EPUB build.

## Calibre Conversion

Locate `ebook-convert` with `shutil.which`. Do not install Calibre
automatically and do not add Calibre as a Python package dependency.

Invoke Calibre without a shell, using an argument list equivalent to:

```text
ebook-convert <kindle.epub> <temporary.azw3>
  --output-profile=kindle_scribe
  --no-inline-toc
```

The `kindle_scribe` output profile supplies device dimensions and image
handling. `--no-inline-toc` prevents Calibre from adding a duplicate visible
table of contents because the EPUB already contains hierarchical navigation
and NCX data.

Do not enable `--linearize-tables`, font embedding, forced justification, or
fixed margins in the initial implementation.

## Failure Handling

The optimized EPUB and its report are durable outputs once written. If Calibre
is missing or conversion fails, retain those two files, remove any temporary
AZW3, and exit with a clear error.

The error contains the attempted executable or command, the Calibre exit code
when available, and a concise stdout/stderr summary. A failed build must not
leave or overwrite the final AZW3 with a partial file.

## Testing and Verification

Automated tests cover:

- `build --kindle` argument parsing and unchanged default parsing;
- unchanged default EPUB CSS and XHTML behavior;
- selection of the packaged Kindle stylesheet;
- conversion of generated clearance labels to real XHTML text;
- absence of Grid, Flexbox, generated-content pseudo-elements, and structural
  pseudo-class dependencies from the Kindle stylesheet;
- preservation of tables, image blocks, content panels, and anomaly bar text;
- exact Calibre arguments, including `kindle_scribe` and `--no-inline-toc`;
- missing-Calibre errors;
- nonzero Calibre exit handling;
- temporary-file cleanup and atomic final output replacement;
- separate Kindle output and report naming.

Run the focused tests followed by `pytest -q`. Then build the complete featured
volume in Kindle mode with the installed Calibre 9.9.0. Verify that:

- the Kindle EPUB and AZW3 both exist and are nonempty;
- the Kindle report still describes all featured pages and reports asset/page
  failures accurately;
- Calibre can read the AZW3 metadata;
- a Calibre AZW3-to-EPUB round trip succeeds as a structural integrity check;
- the round-tripped package retains title, creator, cover, chapter content,
  and hierarchical navigation.

Visual acceptance occurs on the physical Kindle Scribe. Any page-specific
rendering issue found there should be reported by page title or screenshot and
handled as a targeted follow-up rather than broadening the first implementation.

## Documentation

Update `README.md` with:

- Calibre as an optional dependency for `--kindle`;
- the complete featured Kindle build command;
- Kindle EPUB, AZW3, and report output paths;
- the fact that default builds are unchanged;
- conversion failure behavior;
- Calibre/USB transfer as the intended Scribe import path.

Update `AGENTS.md` with:

- the Kindle sample build command;
- the opt-in compatibility boundary;
- Kindle CSS and KF8 constraints;
- required CLI, XHTML/CSS, converter, regression, and full-sample checks when
  Kindle output behavior changes.

## Non-Goals

- Send to Kindle cloud delivery.
- KFX generation or Kindle Previewer automation.
- Fixed-layout output.
- Automatic Calibre installation.
- Changing normal EPUB styling or filenames.
- Guaranteeing pixel-identical rendering across all Kindle models.

## Acceptance Criteria

The feature is complete when the default build remains regression-clean and a
featured build with `--kindle` produces a Kindle-specific EPUB, a valid AZW3,
and a separate report; the AZW3 is created with the Scribe output profile, the
optimized EPUB contains KF8-compatible visual fallbacks, documented failure
behavior is enforced, and both `README.md` and `AGENTS.md` describe the new
workflow.
