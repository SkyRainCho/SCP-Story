# Style processing performance design

## Goal

Reduce cached EPUB build time by removing duplicated CSS parsing in the HTML
transformation path while keeping generated XHTML, stylesheet output, and
classification-bar semantics unchanged.

## Evidence

A cached Featured build was profiled with `cProfile`. Of 942 seconds of
profiled time, `_process_pages` consumed 810 seconds. Matching applicable CSS
rules consumed 259 seconds; the two independent anomaly-classification style
scans consumed 235 and 224 seconds. EPUB writing and asset localization each
consumed about 14 seconds.

## Design

Replace `_anomaly_icon_urls_from_styles` and
`_anomaly_quadrant_colors_from_styles` with one helper that walks each CSS
rule once and returns both mappings. It obtains numeric custom properties once
and retains existing URL normalization, placeholder handling, selector
interpretation, wildcard behavior, and overwrite ordering.

Before applying the general page-style matcher to a style block, use a
conservative textual prefilter. A block still reaches the existing matcher if
it contains `#page-content`, or mentions any class or id actually present in
the page content. A prefilter miss returns no rules without parsing CSS rules.
This only skips selectors that cannot satisfy the matcher’s current targeting
criteria; the existing matcher remains the authority for all potential
matches.

## Tests and validation

Add focused transform tests proving the combined anomaly helper produces the
same icon and quadrant mappings as the prior public transform behavior,
including wildcard/template selectors and custom-property colors. Add page
style tests proving unrelated large style blocks are skipped and relevant
class, id, and `#page-content` rules remain in output. Run focused transform
tests, the full pytest suite, a cached Featured timing run, then all configured
non-Kindle volume builds; run the Featured Kindle build if Calibre is
available.
