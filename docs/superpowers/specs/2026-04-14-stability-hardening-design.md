# Stability Hardening Design

## Goal

Harden the current `kbparser` implementation in the smallest maintainable way by fixing the parse timestamp bug, removing version ownership drift, bounding external binary calls, and adding repo-level smoke verification for the current developer workflow.

## In Scope

1. Fix incorrect `finished_at` handling in parser lifecycle code.
2. Make version ownership explicit and consistent across packaging, runtime, parsers, CLI manifest, and exported JSON.
3. Keep OCR failures soft for PDF parsing, but make them diagnosable and bounded.
4. Keep LibreOffice conversion failures hard for legacy `.doc` parsing.
5. Add repository smoke verification for the Makefile workflow.

## Out of Scope

1. CI/CD and GitHub Actions.
2. Corpus/evals and RAG quality measurement.
3. New runtime dependencies.
4. Broad refactors outside the versioning / parser lifecycle / external binary boundary.
5. Changing the existing output schema beyond the minimum needed warning-code additions.

## Current Problems

### 1. Timestamp bug

`src/kbparser/parsers/base.py` currently stamps `finished_at` while the parse is being initialized, not when parsing actually finishes. This makes parse metadata incorrect and undermines any duration or timing audit.

### 2. Version ownership drift

The current codebase spreads version information across multiple places:
- `pyproject.toml`
- `src/kbparser/__init__.py`
- parser module literals
- `src/kbparser/cli.py`
- `src/kbparser/export.py`

This creates fragile coupling and makes it easy for packaging/runtime/output metadata to drift.

### 3. OCR failure classification is too coarse

PDF OCR currently treats several different failure modes as nearly the same outcome. Timeout, engine failure, empty OCR result, and missing binary are operationally different and should remain soft, but they should not be collapsed into a single vague result.

### 4. DOC conversion failure surface is too generic

`.doc` parsing already depends completely on LibreOffice conversion. That hard dependency is acceptable, but timeout, non-zero exit, and missing output should be surfaced as explicit conversion failures instead of one generic runtime error path.

### 5. Makefile workflow has no repository-level smoke coverage

The current `Makefile` looks syntactically fine, but the repository does not verify that its intended local workflow remains wired correctly.

## Chosen Approach: Balanced Cleanup

This work keeps the current architecture intact and changes only the load-bearing parts:
- centralize version ownership,
- correct parse lifecycle timing,
- classify external binary failures more precisely,
- preserve the current CLI success/partial/failed contract,
- add targeted verification.

This approach deliberately avoids speculative restructuring, new services, or a full metadata subsystem rewrite.

## Architecture

### Version ownership

Introduce one small shared module for version constants. It will own:
- package/release version,
- schema version,
- records version.

`cli.py`, `export.py`, and parser modules will import from that shared module instead of duplicating literals or importing upward through the CLI layer.

`src/kbparser/__init__.py` will continue exposing `__version__`, but it will become a re-export of the shared version source instead of an independent truth.

`pyproject.toml` will stop being an independent literal source for package version and will read the runtime version dynamically.

### Parse lifecycle

`src/kbparser/parsers/base.py` will keep creating `Source` and `Parse` metadata at parse start. However, `finished_at` will no longer be treated as final at creation time.

A tiny lifecycle helper will finalize the `Parse` object immediately before the parser returns the final `Document`. This keeps the change small while ensuring timestamps reflect actual parse completion.

### OCR policy

`src/kbparser/parsers/ocr.py` will become the boundary where OCR runtime outcomes are classified. It will distinguish at least:
- missing binary,
- timeout,
- engine/runtime error,
- empty OCR result,
- successful OCR result.

`src/kbparser/parsers/pdf.py` will remain responsible for policy decisions:
- which pages qualify for OCR,
- whether OCR was used,
- which document warnings are emitted,
- how page-scoped OCR outcomes affect final parse status.

OCR failures remain soft: the parser should still return a `Document` wherever possible.

### DOC conversion policy

`src/kbparser/parsers/doc.py` remains the owner of LibreOffice conversion.

The parser will keep failing hard when conversion is impossible, but conversion errors will be represented explicitly:
- missing LibreOffice,
- conversion timeout,
- conversion process failure,
- missing converted output.

This keeps behavior aligned with current expectations: `.doc` parsing cannot continue if conversion does not complete.

### Verification boundary

Repository verification stays local and lightweight. Instead of introducing CI in this task, the repo gains a smoke path that verifies the intended local developer workflow through tests and `Makefile` targets.

## Components and File Responsibilities

### New module

- `src/kbparser/versioning.py`
  - single source of truth for package version,
  - schema version,
  - records version.

### Modified modules

- `src/kbparser/__init__.py`
  - re-export runtime version from the shared versioning module.

- `pyproject.toml`
  - consume package version dynamically from the runtime package.

- `src/kbparser/export.py`
  - build `Output` using shared version constants,
  - remove dependency on `cli.py` for metadata.

- `src/kbparser/cli.py`
  - consume shared version constants for manifest and doctor output,
  - keep current success/partial/failed semantics.

- `src/kbparser/parsers/base.py`
  - create `Parse` metadata at start,
  - finalize `finished_at` at end,
  - provide the lifecycle helper used by parser implementations.

- `src/kbparser/parsers/doc.py`
  - use shared version source,
  - classify conversion failures explicitly,
  - keep hard-fail behavior for conversion failure,
  - finalize parse metadata before return.

- `src/kbparser/parsers/ocr.py`
  - add bounded OCR execution,
  - classify OCR runtime outcomes.

- `src/kbparser/parsers/pdf.py`
  - translate OCR runtime outcomes into document warnings,
  - keep OCR failures soft,
  - finalize parse metadata before return.

- parser modules with local version literals (for example DOCX / PDF / Excel parsers)
  - stop owning separate release-version literals.

- `Makefile`
  - expose a smoke path for repo-level workflow verification.

### Tests

- Add focused hardening coverage for:
  - version consistency,
  - timestamp lifecycle,
  - OCR soft-failure behavior,
  - DOC hard-failure behavior.

- Add repo smoke coverage for:
  - Makefile-driven local workflow,
  - CLI parse of generated fixtures,
  - basic doctor/version path where practical.

## Data Flow

### Parse lifecycle

1. Parser starts and records `started_at`.
2. Base helper builds initial `Source` and `Parse` metadata.
3. Parser performs its document-specific work.
4. Parser finalizes `Parse.finished_at` immediately before returning the `Document`.
5. CLI builds records, validates output, writes JSON, and produces manifest data as before.

### Version flow

1. Shared versioning module defines the canonical values.
2. Runtime package re-exports package version.
3. CLI doctor/manifest reads shared constants.
4. Exported JSON reads shared constants.
5. Parser modules use the same shared package version instead of maintaining local literals.

### OCR flow

1. PDF parser decides whether a page is an OCR candidate.
2. OCR helper executes Tesseract with bounded runtime.
3. OCR helper returns structured outcome.
4. PDF parser:
   - attaches OCR text on success,
   - emits reason-specific warnings on non-success,
   - keeps parsing the file.

### DOC conversion flow

1. DOC parser resolves LibreOffice binary.
2. Conversion runs in an isolated temp environment.
3. Explicit failure modes are detected.
4. On success, DOCX parser handles content extraction.
5. Final metadata is rewritten back to the original `.doc` source context.
6. On conversion failure, parser raises hard-fail exception and CLI reports file failure.

## Error Handling Policy

### OCR / PDF

Soft failures only. The parser returns a `Document` whenever the underlying PDF parse remains possible.

Expected warning categories:
- OCR skipped because binary is missing,
- OCR timed out,
- OCR engine failed,
- OCR returned no usable text.

These warnings should remain page-scoped where possible.

### DOC / LibreOffice

Hard failures only. If conversion cannot complete, `.doc` parsing fails for that file.

Expected failure categories:
- converter missing,
- converter timeout,
- converter exited unsuccessfully,
- converter produced no output file.

### Output / manifest semantics

No new global severity framework is introduced. Existing behavior stays:
- parser exception -> CLI `failed`,
- parser warnings -> CLI `partial`,
- clean parse -> CLI `success`.

## Testing Strategy

### 1. Version consistency

Verify that the following remain aligned:
- package runtime version,
- parser `.version` attributes,
- top-level exported output version,
- CLI `--version`,
- batch manifest version fields.

### 2. Timestamp lifecycle

Verify:
- `finished_at >= started_at`,
- `finished_at` is assigned after parse work completes,
- parser outputs still remain deterministic aside from timestamps.

### 3. OCR soft-failure behavior

Verify that timeout, engine failure, and empty OCR result each produce the correct warning behavior without converting the whole file into a hard parser failure.

### 4. DOC hard-failure behavior

Verify converter missing, timeout, process failure, and missing-output paths, and confirm CLI reports them as `failed`.

### 5. Makefile smoke

Verify the intended local repo workflow remains valid via a smoke target and corresponding test coverage.

## Risks

### 1. Partial cleanup could leave one stray version literal behind

Mitigation: add explicit tests comparing runtime version and parser/module-facing version values.

### 2. Parser finalize helper could be missed on one return path

Mitigation: add timestamp-focused coverage on the parsers in active use.

### 3. OCR warning taxonomy could grow without clear coverage

Mitigation: keep the reason set intentionally small and test each one directly.

### 4. Makefile smoke could become too broad

Mitigation: keep it lightweight and scoped to the supported local workflow, not full integration infrastructure.

## Success Criteria

This design is complete when:
- parse timestamps reflect real completion time,
- version metadata has one clear ownership path,
- `export.py` no longer depends on `cli.py` for version metadata,
- OCR failures are bounded, classified, and soft,
- DOC conversion failures are explicit and hard,
- repo has smoke verification for the intended Makefile workflow,
- existing core tests still pass and new targeted tests cover the hardening paths.
