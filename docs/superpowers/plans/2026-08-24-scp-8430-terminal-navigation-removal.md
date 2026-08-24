# SCP-8430 Terminal Navigation Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove SCP-8430's terminal Earthworm anthology navigation from Featured ordinary and Kindle Scribe outputs while preserving article content and footnotes.

**Architecture:** Enable the existing page-specific terminal-navigation option for SCP-8430 and extend the transformer with a slug-scoped Earthworm recognizer. Keep the behavior opt-in and structurally strict so other Earthworm components are unaffected.

**Tech Stack:** Python 3.11+, BeautifulSoup, PyYAML, pytest, EPUB ZIP inspection, Calibre `ebook-convert`.

---

### Task 1: Add failing transformer and production configuration tests

**Files:**
- Modify: `tests/test_transform.py`
- Modify: `tests/test_config.py`

- [ ] Add `test_removes_scp8430_terminal_earthworm_navigation_before_footnotes` with article text, a `.earthworm` containing `.earthworm__previous`, `.earthworm__hub`, `.earthworm__next`, and a following `.footnotes-footer`. Enable `remove_terminal_navigation` and assert the Earthworm is absent while article and footnotes remain.
- [ ] Add a parameterized negative test proving the same Earthworm remains when cleanup is disabled or the slug is not `scp-8430`.
- [ ] Add `scp-8430` to the exact Featured production set of `remove_terminal_navigation` slugs.
- [ ] Run the focused tests and verify failures caused by the missing recognizer and configuration.

### Task 2: Implement minimal page-scoped cleanup

**Files:**
- Modify: `src/scp_epub/transform.py`
- Modify: `config/featured-scp.yaml`

- [ ] Add `_is_scp_8430_earthworm_navigation(entry.slug, block)` that requires slug `scp-8430`, class `earthworm`, and previous/hub/next descendants.
- [ ] Extend `_remove_terminal_navigation` to remove a matching terminal block while continuing to allow a following footnotes footer.
- [ ] Add `scp-8430: remove_terminal_navigation: true` to Featured `page_overrides`.
- [ ] Run focused transformer/configuration tests and expect all pass.
- [ ] Run all transform and config tests.
- [ ] Stage only SCP-8430 hunks and commit `fix: remove SCP-8430 terminal navigation`.

### Task 3: Full regression

- [ ] Run `.\.venv\Scripts\python.exe -m pytest -q` and require zero failures.

### Task 4: Rebuild and verify ordinary Featured EPUB

- [ ] Run `.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured`.
- [ ] Locate SCP-8430 using the report `slugs` order.
- [ ] Require a valid EPUB ZIP; no `.earthworm`, anthology navigation titles, or `/scp-anthology-2024`; retain a distinctive article excerpt and `Footnotes`.

### Task 5: Rebuild and verify Kindle Scribe

- [ ] Run `.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable`.
- [ ] Repeat all SCP-8430 EPUB assertions.
- [ ] Require AZW3 size greater than 1024 bytes and bytes 60–67 equal `BOOKMOBI`.

### Task 6: Final verification

- [ ] Run a fresh complete `pytest -q`.
- [ ] Confirm the implementation commit contains only SCP-8430 configuration, transformation, and test changes; preserve existing user modifications.
- [ ] Report affected documents, outputs, chapter verification and fresh test count.
