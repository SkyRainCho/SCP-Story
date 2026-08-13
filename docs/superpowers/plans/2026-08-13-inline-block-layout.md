# Centered Collapsible Card Restoration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore shrink-to-content centered cards only on pages whose original collapsible layout explicitly combines centered panels with inline-block cards.

**Architecture:** Detect the original two-condition pattern before page CSS and inline styles are sanitized. Materialize it into two EPUB-only classes and static CSS rules; do not broaden the global inline-style whitelist or retain interactive collapsible CSS.

**Tech Stack:** Python 3.11+, BeautifulSoup, pytest, existing SCP EPUB pipeline, Calibre.

---

### Task 1: Materialize the conditional static layout

**Files:**
- Modify: `tests/test_transform.py`
- Modify: `src/scp_epub/transform.py`

- [ ] Add a failing test containing the real `#page-content .collapsible-block { text-align:center }` rule, an inline-block card, and a following left-aligned paragraph. Assert the output has `centered-inline-block-container-epub` and `centered-inline-block-card-epub`, plus the two static CSS declarations.
- [ ] Run the target test and confirm it fails because the classes are absent.
- [ ] Implement a source-style detector using `iter_css_rules`; match the centered collapsible selector and a `text-align:center` declaration.
- [ ] When detected, find inline-block descendants of each `.collapsible-block-content`, add the two EPUB-only classes, and append the two static CSS rules only when at least one card was found.
- [ ] Run the target test and confirm it passes.

### Task 2: Prove the condition is narrow

**Files:**
- Modify: `tests/test_transform.py`

- [ ] Add parameterized negative cases for: no centered collapsible rule, no inline-block card, `display:none`, and `display:flex`.
- [ ] Assert none receives either EPUB-only class and no restoration CSS is emitted.
- [ ] Run the focused tests, then all `tests/test_transform.py` tests.
- [ ] Commit only `src/scp_epub/transform.py` and `tests/test_transform.py` with `fix: restore centered collapsible cards`.

### Task 3: Rebuild and verify Featured outputs

**Files:**
- Generate ignored processed XHTML, EPUB, AZW3, and reports for Featured.

- [ ] Run the complete `pytest -q` suite.
- [ ] Build normal Featured EPUB.
- [ ] Build Kindle Scribe stable EPUB/AZW3.
- [ ] Verify both EPUB ZIP archives and the Scribe AZW3 size.
- [ ] Inspect generated SCP-3934 and SCP-4612 XHTML for both EPUB modes; confirm both restoration classes and CSS exist, while following paragraphs remain left-aligned.
- [ ] Visually inspect SCP-3934 and SCP-4612 in rendered output and report the final 10-page global / 2-page Featured impact scope.
