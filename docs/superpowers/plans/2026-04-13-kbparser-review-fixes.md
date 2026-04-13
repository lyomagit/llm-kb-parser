# kbparser Reviewer Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть 4 подтверждённых reviewer-дефекта в CLI, PDF OCR warnings и Excel formula serialization без расширения scope.

**Architecture:** Работа идёт точечными TDD-циклами по существующим модулям: сначала пишем падающий тест на дефект, затем минимально меняем production code, затем прогоняем таргетный тест. CLI contract остаётся прежним, кроме исправления documented default `--out`; OCR warnings получают отдельные codes для skipped states; Excel formula cells сохраняют formula string и cached display value раздельно.

**Tech Stack:** Python 3.11+, pytest, pydantic v2, pymupdf/pdfplumber, openpyxl, xlrd.

---

## File Map

- Modify: `kbparser/cli.py` — default output directory logic and guaranteed manifest directory creation.
- Modify: `kbparser/model.py` — warning code enum for OCR skipped states.
- Modify: `kbparser/parsers/pdf.py` — emit distinct OCR warning codes only when semantics match.
- Modify: `kbparser/parsers/excel.py` — preserve formula string in `raw_value`; distinguish `display_value=None` from `display_value=""` by preserving current `_cell_text()` semantics and using display when non-`None`.
- Modify: `tests/test_smoke_cli.py` — CLI regression tests.
- Modify: `tests/test_pdf_ocr.py` — OCR warning regression tests.
- Modify: `tests/test_xls_parser.py` — formula cell regression test.

### Task 1: Fix CLI default output path and manifest safety

**Files:**
- Modify: `kbparser/cli.py:72-100`
- Test: `tests/test_smoke_cli.py`

- [ ] **Step 1: Write the failing tests**

Add these tests to `tests/test_smoke_cli.py`:

```python
def test_cli_directory_default_out_uses_parent(tmp_path: Path):
    indir = tmp_path / "in"
    indir.mkdir()
    build_basic_pdf(indir / "a.pdf")

    rc = main(["parse", str(indir)])

    assert rc == 0
    outdir = tmp_path / "kb-parse-out"
    assert outdir.exists()
    assert (outdir / "manifest.json").exists()
    assert len(list(outdir.glob("*.json"))) == 1


def test_cli_batch_manifest_written_even_if_all_files_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    indir = tmp_path / "in"
    indir.mkdir()
    build_basic_pdf(indir / "a.pdf")
    build_basic(indir / "b.docx")

    def fake_parse_one(path, out_dir, profile, overwrite, ocr_langs):
        return {"file": str(path), "status": "failed", "error": "boom"}

    monkeypatch.setattr("kbparser.cli._parse_one", fake_parse_one)

    rc = main(["parse", str(indir)])

    assert rc == 1
    outdir = tmp_path / "kb-parse-out"
    manifest = json.loads((outdir / "manifest.json").read_text())
    assert [r["status"] for r in manifest["results"]] == ["failed", "failed"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && venv/bin/pytest tests/test_smoke_cli.py -q`
Expected: FAIL
- `test_cli_directory_default_out_uses_parent` fails because output lands in `in/kb-parse-out`
- `test_cli_batch_manifest_written_even_if_all_files_fail` fails with missing `manifest.json` or `FileNotFoundError`

- [ ] **Step 3: Write minimal implementation**

Update `kbparser/cli.py` so directory inputs use the parent directory for the default output path, while explicit `--out` still overrides everything:

```python
def cmd_parse(args: argparse.Namespace) -> int:
    src = Path(args.path).expanduser().resolve()
    if args.out:
        out_dir = Path(args.out).expanduser().resolve()
    else:
        base = src.parent
        out_dir = (base / "kb-parse-out").resolve()
    inputs = _iter_inputs(src)
    if not inputs:
        print(f"no supported files under {src}", file=sys.stderr)
        return 2

    ocr_langs = args.lang or os.environ.get("KBPARSER_OCR_LANGS") or None
    results = [
        _parse_one(p, out_dir, args.profile, args.overwrite, ocr_langs)
        for p in inputs
    ]

    if len(inputs) > 1 or src.is_dir():
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = {"root": str(src), "profile": args.profile, "results": results}
        with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && venv/bin/pytest tests/test_smoke_cli.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_smoke_cli.py kbparser/cli.py
git commit -m "fix: harden cli batch output"
```

### Task 2: Separate OCR skipped warnings from OCR-applied warnings

**Files:**
- Modify: `kbparser/model.py:23-31`
- Modify: `kbparser/parsers/pdf.py:58-85,246-295`
- Test: `tests/test_pdf_ocr.py`
- Test: `tests/test_model.py`

- [ ] **Step 1: Write the failing tests**

Add these tests to `tests/test_pdf_ocr.py`:

```python
def test_scanned_without_tesseract_emits_missing_binary_warning(scanned_pdf: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("kbparser.parsers.pdf.find_tesseract", lambda: None)

    d = _parse(scanned_pdf)

    assert d.parse.ocr_used is False
    assert any(
        w.code == "ocr_skipped_missing_binary"
        and (w.scope or {}).get("pages_missing_ocr") == [1]
        for w in d.warnings
    )
    assert not any(w.code == "ocr_applied_to_pages" for w in d.warnings)


def test_scanned_empty_ocr_result_emits_empty_result_warning(scanned_pdf: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("kbparser.parsers.pdf.find_tesseract", lambda: "/fake/tesseract")
    monkeypatch.setattr("kbparser.parsers.pdf.ocr_page", lambda *args, **kwargs: [])

    d = _parse(scanned_pdf)

    assert d.parse.ocr_used is False
    assert any(
        w.code == "ocr_skipped_empty_result"
        and (w.scope or {}).get("pages_missing_ocr") == [1]
        for w in d.warnings
    )
    assert not any(w.code == "ocr_applied_to_pages" for w in d.warnings)
```

Add this test to `tests/test_model.py`:

```python
from kbparser.model import Document, Parse, Source, Warning


def test_warning_accepts_ocr_skipped_codes():
    w1 = Warning(code="ocr_skipped_missing_binary", message="missing")
    w2 = Warning(code="ocr_skipped_empty_result", message="empty")
    assert w1.code == "ocr_skipped_missing_binary"
    assert w2.code == "ocr_skipped_empty_result"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && venv/bin/pytest tests/test_pdf_ocr.py tests/test_model.py -q`
Expected: FAIL
- Pydantic rejects new warning codes
- PDF parser still emits `ocr_applied_to_pages` for skipped OCR cases

- [ ] **Step 3: Write minimal implementation**

Extend `WarningCode` in `kbparser/model.py`:

```python
WarningCode = Literal[
    "ocr_applied_to_pages",
    "ocr_skipped_missing_binary",
    "ocr_skipped_empty_result",
    "table_structure_uncertain",
    "doc_conversion_lost_styles",
    "formula_not_evaluated",
    "header_footer_filtered_heuristically",
    "heading_inference_low_confidence",
    "parser_stub_used",
]
```

Update `kbparser/parsers/pdf.py` so `_maybe_ocr()` keeps the same return shape but caller maps skipped states to distinct warnings:

```python
        if ocr_skipped:
            missing_binary = _find() is None
            warnings.append(Warning(
                code=(
                    "ocr_skipped_missing_binary"
                    if missing_binary else
                    "ocr_skipped_empty_result"
                ),
                message=(
                    "Page(s) lack a text layer but Tesseract is not installed. "
                    "Install via `brew install tesseract` / `apt install tesseract-ocr` "
                    "to recover text."
                    if missing_binary else
                    "Tesseract produced no output for page(s); OCR effectively failed."
                ),
                scope={"pages_missing_ocr": ocr_skipped},
            ))
```

Keep `ocr_applied_to_pages` only for pages in `ocr_applied_pages`, which are appended only when OCR returned non-empty text.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && venv/bin/pytest tests/test_pdf_ocr.py tests/test_model.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_pdf_ocr.py tests/test_model.py kbparser/model.py kbparser/parsers/pdf.py
git commit -m "fix: split ocr warning states"
```

### Task 3: Preserve formula raw_value in Excel tables

**Files:**
- Modify: `kbparser/parsers/excel.py:376-438`
- Test: `tests/test_xls_parser.py`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_xls_parser.py`:

```python
def test_formula_cells_preserve_formula_and_cached_display(basic_xls: Path):
    d = _parse(basic_xls)
    summary = next(t for t in d.tables if t.sheet == "Summary")

    formula_cells = [cell for row in summary.rows for cell in row if cell.formula]
    assert formula_cells, "expected at least one formula cell in Summary sheet"

    cell = formula_cells[0]
    assert cell.raw_value == cell.formula
    assert cell.display_value is not None
    assert cell.text == cell.display_value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && venv/bin/pytest tests/test_xls_parser.py::test_formula_cells_preserve_formula_and_cached_display -q`
Expected: FAIL with `assert None == '=...'` on `raw_value`

- [ ] **Step 3: Write minimal implementation**

Update `kbparser/parsers/excel.py` inside `_build_table()`:

```python
            raw = cell_f.value if cell_f is not None else None
            display = _cell_text(cell_c)
            formula: str | None = None
            if isinstance(raw, str) and raw.startswith("="):
                formula = raw
                had_formula = True
            text = display if display is not None else _cell_text(cell_f)
            cells.append(TableCell(
                row=ri,
                col=ci,
                text=text,
                raw_value=raw,
                display_value=display,
                formula=formula,
                row_span=row_span,
                col_span=col_span,
            ))
```

This preserves:
- `display_value=None` when no cached/display value exists
- `display_value=""` only if `_cell_text()` ever returns empty string for a real cached empty string
- `raw_value=formula_string` for formula cells

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && venv/bin/pytest tests/test_xls_parser.py::test_formula_cells_preserve_formula_and_cached_display -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_xls_parser.py kbparser/parsers/excel.py
git commit -m "fix: preserve excel formula raw values"
```

### Task 4: Run final regression verification

**Files:**
- Modify: none
- Test: `tests/test_smoke_cli.py`
- Test: `tests/test_pdf_ocr.py`
- Test: `tests/test_model.py`
- Test: `tests/test_xls_parser.py`

- [ ] **Step 1: Run targeted regression suite**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && venv/bin/pytest tests/test_smoke_cli.py tests/test_pdf_ocr.py tests/test_model.py tests/test_xls_parser.py -q`
Expected: PASS

- [ ] **Step 2: Run full suite**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && venv/bin/pytest -q`
Expected: PASS (existing baseline was 73 passed, 3 skipped)

- [ ] **Step 3: Review diff for scope control**

Run:

```bash
cd "/Users/username/Desktop/llm-kb-parser"
git diff -- kbparser/cli.py kbparser/model.py kbparser/parsers/pdf.py kbparser/parsers/excel.py tests/test_smoke_cli.py tests/test_pdf_ocr.py tests/test_model.py tests/test_xls_parser.py
```

Expected: only 4 scoped fixes + matching tests

- [ ] **Step 4: Commit verification batch**

```bash
git add kbparser/cli.py kbparser/model.py kbparser/parsers/pdf.py kbparser/parsers/excel.py tests/test_smoke_cli.py tests/test_pdf_ocr.py tests/test_model.py tests/test_xls_parser.py
git commit -m "test: verify reviewer regression fixes"
```
