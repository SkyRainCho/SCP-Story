# Kindle Scribe Location Badge Thumbnail Design

## Goal

Reduce the decoded-image working set of the `locations-of-interest` appendix in
the Kindle Scribe stable edition without reducing map resolution or changing the
page's XHTML, CSS, display dimensions, navigation, or content.

The current grayscale Kindle Scribe build contains 169 image references on this
page. Context inspection identifies 164 badge references representing 46 unique
badge assets, plus five non-badge images. The current page estimate is 90,545,036
bytes, or about 86.35 MiB, which leaves it as the only page above the stable
build's 64 MiB target.

## Selected Approach

The stable variant planner will identify location badges from their existing
ancestor containers and assign them a dedicated 320 by 320 maximum bounding box.
The five non-badge images retain the page's current adaptive image spec.

The selected badge contexts are:

- an image inside an ancestor with class `enlarge`, used for map markers;
- an image inside an ancestor with class `legend-box`, used by the map legend;
- an image inside an ancestor carrying both `image-container` and `floatright`,
  used beside location descriptions.

The rule applies only when the page slug is exactly `locations-of-interest`.
Matching by both page and ancestor context prevents unrelated images elsewhere in
the book from being reduced.

## Alternatives Considered

### Apply a 320-pixel cap to the whole page

This is simpler, but it also reduces the world and regional maps. Those maps
contain labels and boundaries that benefit from the existing 800-pixel adaptive
variant, so page-wide resizing is rejected.

### Add permanent badge classes during HTML transformation

Adding a class such as `location-badge-epub` would make the planner rule simple,
but the transformed XHTML is shared by standard EPUB and current high-quality
Kindle builds. Even a currently unstyled class would create an unnecessary
structural difference outside stable mode. Context detection in the stable
planner is more isolated.

### Use a smaller 192- or 256-pixel cap

These caps would lower the estimated page footprint further, but the user chose
320 pixels to preserve additional detail in thin-lined insignia on the 300 ppi
Kindle Scribe display.

## Image Reference Context

`LocalImageReference` will gain an `ancestor_classes` field. While parsing an
`<img>`, `local_image_references` will walk its existing parent chain and collect
space-separated class tokens from every ancestor. The parser already records
parent relationships, so no new HTML parser or BeautifulSoup pass is required.

The new field is metadata only. It does not rewrite the page and is available to
other image-planning rules if needed later. Existing `href`, direct image
`classes`, and occurrence ordering remain unchanged.

## Stable Variant Planning

The stable planner will add:

```text
LOCATION_BADGE_SPEC = StableVariantSpec("location-badge", 320, 320)
```

A small predicate will return true only when:

1. the page slug is `locations-of-interest`; and
2. the reference has an `enlarge` or `legend-box` ancestor, or has both
   `image-container` and `floatright` ancestors.

Initial spec precedence is:

1. facility icons use the existing 384-pixel facility spec;
2. matching location badges use the new 320-pixel location-badge spec;
3. all other images use the ordinary stable spec.

When the page exceeds the target budget, the existing adaptive loop must change
only references still using the ordinary/adaptive path. Fixed facility and
location-badge variants remain at their dedicated sizes. This keeps maps eligible
for the current page-level adaptive bound while preventing badge assets from being
expanded back to 800 pixels.

Repeated use of the same badge source and spec remains deduplicated by the
existing `(source href, StableVariantSpec)` request identity. No new cache or
filename scheme is needed; the purpose name and 320 by 320 dimensions already
participate in the deterministic grayscale filename and digest.

## Expected Performance

Measured against the current generated EPUB:

- current page estimate: about 86.35 MiB;
- 46 unique badge assets capped at 320 pixels, with five other images unchanged:
  about 21.79 MiB.

The exact rebuilt value may differ slightly if source assets or upstream page
content change, but it must remain below the 64 MiB target for the current cached
Featured build. The conservative four decoded bytes per pixel estimate remains
unchanged even though the assets are encoded as grayscale.

## Reporting

The stable `kindle_performance` report will add:

- `location_badge_variant_count`: number of successfully generated unique
  320-pixel badge variants.

The existing `thumbnail_variant_count` continues to represent facility variants
only, preserving its current meaning. `adaptive_variant_count`, grayscale counts,
per-page estimates, and warning handling remain unchanged.

## Error Handling and Compatibility

Location badge rendering uses the existing stable variant path. A failed badge
conversion follows current behavior: its source URL is recorded once in
`missing_assets`, its failed reference is removed by the Kindle fallback, and
other variants continue.

The change is restricted to stable planning and reference metadata. Standard EPUB
and current `--kindle` image preparation do not use the location-badge spec and
must retain their current assets, filenames, reports, and output paths. The
existing grayscale-preserve-alpha encoding applies to the new variants.

## Testing

`tests/test_kindle.py` will verify that `local_image_references` reports direct
image classes separately from accumulated ancestor classes and preserves image
occurrence ordering.

`tests/test_kindle_stable.py` will verify:

- `enlarge`, `legend-box`, and `image-container floatright` references on
  `locations-of-interest` receive the 320-pixel spec;
- a map inside `mainmap` or `secmap` retains the ordinary/adaptive path;
- the same ancestor structures on another page do not trigger the rule;
- repeated badges share one generated variant;
- adaptive budget selection does not overwrite the fixed badge spec;
- performance output reports `location_badge_variant_count` and removes the page
  from warnings when its estimate falls below 64 MiB.

`tests/test_pipeline.py` will extend the stable build integration assertion to
confirm the new report field without changing output filenames.

Final verification will run the complete test suite, rebuild the Featured Kindle
Scribe EPUB/AZW3, and audit the produced EPUB to confirm:

- location badge assets use `gray-location-badge-320x320` variants and do not
  exceed 320 by 320 pixels;
- map assets on the page do not use the location-badge purpose;
- all XHTML files parse and all local image references resolve;
- the `locations-of-interest` report entry is below 64 MiB and absent from
  warnings;
- all generated badge assets remain `L` or `LA` grayscale;
- standard EPUB and high-quality Kindle output paths are not overwritten.

## Non-goals

This change does not redesign the map, combine markers into a composite image,
remove repeated marker references, alter page CSS, resize other appendix icons,
or change the chosen 320-pixel badge bound dynamically. Structural map conversion
or page splitting remains outside this task.
