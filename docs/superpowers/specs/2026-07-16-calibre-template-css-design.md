# Calibre Template CSS Compatibility

## Goal

Allow the featured EPUB to convert to AZW3 in Calibre without changing normal
document layouts.

## Root Cause

The Wikidot source for `scp-8430` includes an `earthworm` navigation rule with
unexpanded template placeholders such as `{$previous-title}`. The current CSS
rule extractor preserves that malformed selector because it references a class
present in the article. Calibre's CSS flattener then aborts while parsing it.

## Design

During page-style extraction, reject only a CSS rule whose selector contains an
unexpanded Wikidot template placeholder. Do not remove the style element, body
markup, or unrelated rules in the same style block.

The placeholder detector will recognize the escaped form emitted by Wikidot
(`\{\$name\}`) and the plain form (`{$name}`). This boundary excludes normal
CSS variables, custom properties, and selectors that merely use the
`earthworm` component.

## Verification

Add a transform regression test with one malformed template selector and one
normal rule targeting the same content. The test must prove that the malformed
rule is absent while the normal rule remains. Run the focused test suite, the
full test suite, and rebuild the featured EPUB before validating the generated
`scp-8430` XHTML no longer contains the placeholders.
