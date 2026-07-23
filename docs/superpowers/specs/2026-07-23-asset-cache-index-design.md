# Asset cache index design

## Goal

Make cached EPUB builds fast by avoiding a full directory glob for every asset
cache lookup. The change applies to every volume and preserves the existing
on-disk cache format.

## Design

`CacheStore` will lazily build an in-memory mapping from the existing
16-character asset digest to its cached asset path. The first `find_asset`
call enumerates `data/raw/assets` once, ignores metadata sidecars, and uses
the same deterministic ordering as the current lookup when legacy duplicate
asset files are present. Later lookups use the mapping directly.

`write_asset` updates an already-initialized mapping. The refresh path removes
the old digest entry before writing a replacement, so a forced download cannot
leave a stale path in memory. No index file is written to disk.

## Compatibility and errors

The cache directory may be absent, contain metadata JSON files, or contain
legacy duplicate extensions for one digest. Those cases retain their current
observable behavior: absent entries are cache misses, JSON files are ignored,
and the stable first non-metadata asset is selected. A new process rebuilds its
mapping from the current directory contents, so manual cache changes are also
observed on the next build.

## Tests and validation

Tests will demonstrate repeated lookups use a single directory enumeration,
that metadata and duplicate legacy assets are handled compatibly, and that a
forced refresh replaces the indexed path. Validation will include the focused
cache/fetcher tests, the full pytest suite, a fresh timed Featured build, and
cached builds of every configured non-Kindle volume; Kindle builds will be run
as well when `ebook-convert` is available.
