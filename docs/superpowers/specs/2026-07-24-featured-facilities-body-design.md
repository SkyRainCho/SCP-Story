# Featured Facilities Body Design

## Goal

Restore the source body of the Featured appendix entry `基金会设施` in both the
standard and Kindle EPUB builds. The entry must contain the introductory text,
site list, area list, and only the Wikidot tab named `设施种类定义`, while keeping
the existing `安保设施档案：…` child documents in the EPUB navigation.

## Root Cause

The `facility-links` manifest expansion correctly reads
`secure-facilities-locations` to discover child dossier links, but represents
the parent as an `appendix-group`. During the later fetch phase every
`appendix-group` is replaced with generated HTML containing only its title.
Consequently, the already-fetched source HTML is discarded and the EPUB parent
page is blank apart from duplicate headings.

This contradicts the original Featured appendix design, which specifies that
`基金会设施` retains its source document while adding facility dossiers as direct
children.

## Design

Keep the current manifest slug and hierarchy for backward compatibility:

- Parent: `secure-facilities-locations--appendix-group`
- Children: existing `appendix-facility` entries beneath that parent

When an `appendix-group` corresponds to a configured `facility-links` section,
the fetch phase will reuse the configured section's original `FetchResult` or
fetch that source URL when no prefetched result is available. Other generated
groups, including the appendix root and `tabs-as-pages` parents, continue to use
minimal generated group HTML.

The page-processing phase will resolve appendix section options for both normal
section slugs and generated group slugs. `config/featured-scp.yaml` will select
the `设施种类定义` tab for the facilities section and unwrap the single selected
panel. Content outside the tabview is unaffected, so the introduction, site
list, and area list remain in source order. All unselected panels, including
`进一步阅读`, `关于此页面`, `添加至现有条目`, and `添加新条目`, are omitted.

No special-purpose HTML selector or page-specific transform function is added;
the existing appendix configuration and generic Wikidot tab filtering remain
the source of behavior.

## Data Flow

1. Manifest expansion fetches the facilities source and extracts labelled
   facility dossier children exactly as today.
2. The facilities parent remains a generated group slug so cached manifests and
   child `parent_slug` values remain valid.
3. Fetch resolution recognizes that this group represents `facility-links` and
   supplies the original source HTML instead of title-only generated HTML.
4. Page processing applies the configured `include_tabs` and
   `unwrap_single_tab` options to the group slug.
5. The EPUB writer emits the restored parent body followed by the unchanged
   facility dossier child chapters in navigation order.

## Failure Handling

If the source page cannot be fetched, existing missing-page handling applies to
the facilities parent. Child dossier extraction and fetching retain their
current conservative behavior. No fallback to arbitrary links or recursive
facility discovery is introduced.

## Testing

Regression tests will prove that:

- a `facility-links` group uses the original source HTML instead of generated
  title-only HTML;
- the parent body retains introductory content, the site list, and the area
  list;
- only `设施种类定义` is included from the Wikidot tabs and its wrapper heading is
  removed;
- existing facility children remain beneath the same parent slug and in source
  order;
- appendix roots and `tabs-as-pages` group parents remain minimal generated
  pages;
- cached-manifest and prefetched-source paths produce equivalent output.

After targeted tests pass, the full test suite will run. The Featured Kindle
volume will then be rebuilt and its XHTML inspected to confirm the required
text and excluded tab labels before validating the EPUB archive and AZW3
metadata.
