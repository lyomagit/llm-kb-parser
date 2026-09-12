# KBParser desktop quality implementation plan

**Goal:** Deliver a local macOS build that responds normally and preserves document content, ordering, and output identity.

**Architecture:** Keep the Python parsers, canonical model, CLI, and Tkinter UI. Fix extraction at its source, render the existing document flow, and validate an existing export before reusing its filename. Build against a verified modern Tcl/Tk runtime instead of the installed app's Tk 8.6.12.

**Verification:** Use the existing pytest suite and small regression cases reproducing the audit. Run `pytest`, `ruff check src/ tests/`, `mypy src/kbparser/`, and the packaged CLI smoke checks. Inspect the newly built window with the native UI tool.

- [x] Establish the macOS event-handling cause, choose a working build runtime, and prevent an unsupported toolkit from silently entering a new build (`scripts/build_apps.py`, `.github/workflows/build-apps.yml`). Verify both the Tcl/Tk version and real window input.
- [x] Preserve text and tables before the first heading in DOCX/PDF (`parsers/docx.py`, `parsers/pdf.py`). Regression: preamble, heading, body must all remain in both the canonical document and derived output, with every block linked to a section.
- [x] Preserve Markdown flow and cell positions (`export.py`). Regression: paragraph, table, paragraph must retain order; headers occur once; merged cells must not shift values left; tables remain with their workbook sheet.
- [x] Read PDF columns in column order while preserving spanning headings (`parsers/pdf.py`). Regression: heading followed by two two-paragraph columns, followed by a full-width paragraph.
- [x] Report unextracted scan pages and empty results explicitly (`model.py`, `parsers/pdf.py`, `cli.py`). Regression: scanned input in `text-lite` yields a warning, never an unqualified success.
- [x] Reuse outputs only when source hash and parse settings match; avoid collisions across separate runs; write through a temporary file and atomic replace (`cli.py`, `export.py`). Regression: two distinct same-name documents, changed settings, corrupt existing output, and interrupted writes preserve prior valid files.
- [x] Bound derived table records by row groups with repeated headers and original row lineage; retain the full canonical table (`records/chunker.py`). Regression: a large table splits into deterministic, source-linked records without missing rows.
- [x] Improve the existing UI with bounded live output, visible progress, safe single-job state, cancellation, and a readable result preview (`gui.py`, `cli.py`). Test worker completion, failure, cancellation, and responsiveness without changing the parser's public output schema unnecessarily.
- [x] Bump the package/record policy version where behavior changes require it, set the actual macOS bundle version, build a separate reviewable app, and run full verification. Do not overwrite the installed app until a working build exists.

For each behavior: add the regression to its existing test module, observe the failure, implement the smallest fix, and rerun that module. Keep the original `feature/android-office-engine` checkout intact.

## Verified result

KBParser 0.3.0 builds with Python 3.13.15 and Tcl/Tk 9.0.4. The final Python suite has 174 passing tests and 2 environment-conditional skips; ruff and mypy pass. The packaged macOS app opened a DOCX through its native menu, produced verified JSON/Markdown with the preamble and table in place, and cancelled a 20-page OCR job without exporting an incomplete document. Window state updated without moving the window.

- [ ] Confirm ordinary clicks and typing in Tk widgets with the user. The UI automation tool could operate native menus/dialogs but returned timeouts or noWindowsAvailable for coordinate clicks and direct field input. This does not establish that the user-reported input freeze is fixed.

Windows/Android builds were not run locally. GitHub publication was authorized after local verification on 2026-09-12.
