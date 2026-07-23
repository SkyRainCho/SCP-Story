# Featured Light-Text Readability Design

## Goal

Eliminate EPUB-only cases where light text loses its intended dark background in the Featured collection, while preserving text that is intentionally hidden on the source page.

## Confirmed scope

A computed-style scan of all 372 Featured XHTML documents found seven real regressions after comparison with the source pages:

- `SCP-6747 - 混沌学说`: image caption inside a dark notation panel.
- `SCP-6838 - 林中之光`: Parawatch forum posts.
- `SCP-8274 - 帝王蝶`: terminal diary blocks and an image caption.
- `SCP-9100 - 白日梦`: dark auditor panels.
- `安保设施档案：Site-7（未同步）`: colored dossier labels.
- `安保设施档案：Site-81TG`: blackboard/game panels.
- `安保设施档案：Area-12`: dark dossier elements.

The white text in the `博士` tab of `人员及角色档案` is also white on a light background on the source page. It is an intentional hidden-text joke and must remain unchanged.

## Root causes

Three conversion behaviors combine to create the regressions:

1. The page-style rule extractor can attach CSS comments or semicolon at-rules such as `@import` to the following selector. The resulting selector is invalid, so the reader drops the dark-background rule.
2. Matching rules are retained without the numeric CSS custom properties they reference. A declaration such as `background: rgb(var(--bright-accent))` becomes invalid in the EPUB even though `color: white` remains valid.
3. The global EPUB stylesheet forces light backgrounds on `.blockquote` and `.scp-image-block`. Those backgrounds cover dark ancestor panels used by terminal and notation layouts.

## Chosen approach

The fix will operate at the shared transformation and base-style layers rather than introducing seven page-specific overrides.

### Normalize page CSS before rule matching

Before applying `CSS_RULE_RE`, remove CSS comments and standalone semicolon at-rules that cannot be packaged usefully, including `@import`, `@charset`, and `@namespace`. Removing the complete construct prevents it from being treated as part of the next selector.

This normalization is limited to the copy of CSS used for EPUB rule extraction. It does not alter the cached source HTML.

### Resolve numeric CSS custom properties

Collect numeric RGB custom-property values from all source style blocks. Resolve aliases such as `--swatch-primary: var(--bright-accent)` recursively, with cycle protection. When emitting a matching page rule, replace numeric `var(...)` references with their resolved triplets or with the declaration's numeric fallback.

Only numeric RGB triplets are resolved. Unrelated variables for dimensions, fonts, animation, and layout remain unchanged, avoiding broad changes to complex page themes.

### Let nested dark panels supply their own background

Change the global EPUB defaults for `blockquote`, `.blockquote`, and `.scp-image-block` from forced light backgrounds to transparent backgrounds. On ordinary pages the visible background remains the white page, so their appearance is effectively unchanged. Inside a terminal, notation panel, or other dark component, the intended ancestor background remains visible.

The fix will not globally recolor light text. This is necessary to preserve intentional hidden text and author-selected color effects.

## Testing

Tests will be written before implementation and will cover the three root causes independently:

1. An `@import` followed by a dark block rule must emit a valid selector and retain its background.
2. Comments before ordinary rules must not comment out or corrupt those rules.
3. Direct and aliased numeric CSS variables must resolve inside retained page declarations.
4. The base EPUB CSS must use transparent blockquote and image-block backgrounds.
5. A terminal/notation fixture must retain light text without receiving a forced light child background.
6. Explicit white text with no source dark background must not be automatically recolored, protecting intentional hidden text.

After unit tests pass, rebuild the Featured EPUB and rerun the same browser computed-style audit across all 372 documents. The seven confirmed documents must no longer contain visible light-on-light text. The intentional hidden text in the personnel dossier may remain as the sole known source-equivalent candidate.

## Outputs

- Updated transformation and base EPUB CSS behavior.
- Regression tests in the existing transform and EPUB test modules.
- Rebuilt `output/epub/SCP基金会档案精选.epub` and report, which remain untracked build artifacts.
- Final affected-document list and verification results reported to the user.
