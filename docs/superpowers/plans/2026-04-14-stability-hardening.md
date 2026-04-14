# Stability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden `kbparser` by centralizing version ownership, fixing parse timestamp lifecycle, classifying OCR soft-failures, making DOC conversion failures explicit, and adding Makefile-backed repo smoke verification.

**Architecture:** Add one tiny shared versioning module, keep the current CLI/parser/export flow, and fix the parser lifecycle with a small `finalize_parse()` helper instead of a broad model refactor. OCR stays soft and page-scoped inside the PDF path; DOC conversion stays hard-fail inside the DOC path; smoke verification stays local via pytest and `make smoke`.

**Tech Stack:** Python 3.11+, setuptools, pytest, python-docx, openpyxl, xlrd, PyMuPDF (`fitz`), pdfplumber, pytesseract, LibreOffice CLI

---

## File Map

### Create
- `src/kbparser/versioning.py` — single source of truth for `PACKAGE_VERSION`, `SCHEMA_VERSION`, `RECORDS_VERSION`
- `tests/test_stability_hardening.py` — regression tests for version consistency and parse timestamp lifecycle
- `tests/test_repo_smoke.py` — repo-level smoke tests for manifest/output version wiring and Makefile target presence

### Modify
- `pyproject.toml:5-33` — move package version to dynamic attr lookup
- `src/kbparser/__init__.py:1-2` — re-export package version from shared versioning module
- `src/kbparser/cli.py:13-21,113-119,198-199` — consume shared version constants for manifest and doctor output
- `src/kbparser/export.py:7-19` — remove `export -> cli` back-edge; consume shared version constants directly
- `src/kbparser/model.py:30-40` — add new OCR warning codes
- `src/kbparser/parsers/base.py:53-112` — add `finalize_parse()` and stop stamping a real `finished_at` during parse setup
- `src/kbparser/parsers/docx.py:18-60` — source version from shared owner and finalize parse before return
- `src/kbparser/parsers/excel.py:23-175` — source version from shared owner and finalize parse before return
- `src/kbparser/parsers/pdf.py:29-80,241-296` — translate typed OCR runtime outcomes into reason-specific warnings and finalize parse before return
- `src/kbparser/parsers/ocr.py:20-91` — add OCR timeout/error classification boundary
- `src/kbparser/parsers/doc.py:35-151` — add typed DOC conversion exceptions, source version from shared owner, and finalize outer parse metadata before return
- `tests/test_pdf_ocr.py:35-92` — add OCR timeout/error regression cases
- `tests/test_doc_parser.py:35-86` — add typed DOC conversion failure regression cases
- `Makefile:1-24` — add `smoke` target using repo-local commands

---

### Task 1: Centralize version ownership

**Files:**
- Create: `src/kbparser/versioning.py`
- Create: `tests/test_stability_hardening.py`
- Modify: `pyproject.toml:5-33`
- Modify: `src/kbparser/__init__.py:1-2`
- Modify: `src/kbparser/cli.py:13-21,113-119,198-199`
- Modify: `src/kbparser/export.py:7-19`
- Modify: `src/kbparser/parsers/docx.py:18-27`
- Modify: `src/kbparser/parsers/excel.py:23-37`
- Modify: `src/kbparser/parsers/pdf.py:29-47`
- Modify: `src/kbparser/parsers/doc.py:21-49`
- Test: `tests/test_stability_hardening.py`

- [ ] **Step 1: Write the failing version-consistency tests**

`tests/test_stability_hardening.py`

```python
from kbparser import __version__
from kbparser.export import to_output
from kbparser.model import Document, Parse, Source
from kbparser.parsers.doc import DOCParser
from kbparser.parsers.docx import DOCXParser
from kbparser.parsers.excel import ExcelParser
from kbparser.parsers.pdf import PDFParser
from kbparser.versioning import PACKAGE_VERSION, RECORDS_VERSION, SCHEMA_VERSION


def _doc() -> Document:
    src = Source(
        path="/tmp/sample.pdf",
        filename="sample.pdf",
        format="pdf",
        mime_type="application/pdf",
        sha256="0" * 64,
        size_bytes=1,
        modified_at="2026-04-14T00:00:00+00:00",
    )
    parse = Parse(
        parser="pdf",
        parser_version=PACKAGE_VERSION,
        started_at="2026-04-14T00:00:00+00:00",
        finished_at="2026-04-14T00:00:00+00:00",
    )
    return Document(id="doc_sample", source=src, metadata={}, parse=parse)


def test_parser_versions_match_package_version():
    assert PACKAGE_VERSION == __version__
    assert DOCParser.version == PACKAGE_VERSION
    assert DOCXParser.version == PACKAGE_VERSION
    assert ExcelParser.version == PACKAGE_VERSION
    assert PDFParser.version == PACKAGE_VERSION


def test_to_output_uses_shared_version_constants():
    out = to_output(_doc())
    assert out.parser_version == PACKAGE_VERSION
    assert out.schema_version == SCHEMA_VERSION
    assert out.records_version == RECORDS_VERSION
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_stability_hardening.py::test_parser_versions_match_package_version tests/test_stability_hardening.py::test_to_output_uses_shared_version_constants -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'kbparser.versioning'`.

- [ ] **Step 3: Implement shared version ownership**

`src/kbparser/versioning.py`

```python
PACKAGE_VERSION = "0.2.0"
SCHEMA_VERSION = "1.0"
RECORDS_VERSION = "1.0"

__all__ = ["PACKAGE_VERSION", "SCHEMA_VERSION", "RECORDS_VERSION"]
```

`src/kbparser/__init__.py`

```python
from .versioning import PACKAGE_VERSION as __version__

__all__ = ["__version__"]
```

`pyproject.toml`

```toml
[project]
name = "kbparser"
dynamic = ["version"]
description = "Local document → KB-ready JSON parser for LLM knowledge-base ingestion."
requires-python = ">=3.11"
readme = "README.md"
license = {text = "MIT"}
dependencies = [
  "pydantic>=2.0",
  "python-docx>=1.1",
  "openpyxl>=3.1",
  "pymupdf>=1.24",
  "pdfplumber>=0.11",
  "xlrd>=2.0",
  "pytesseract>=0.3",
  "Pillow>=10.0",
]

[tool.setuptools.dynamic]
version = {attr = "kbparser.__version__"}
```

`src/kbparser/export.py`

```python
"""Deterministic JSON writer with versioned output."""
from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .model import Document, Output, Record
from .versioning import RECORDS_VERSION, SCHEMA_VERSION


def to_output(doc: Document, records: list[Record] | None = None) -> Output:
    return Output(
        schema_version=SCHEMA_VERSION,
        records_version=RECORDS_VERSION,
        parser_version=__version__,
        document=doc,
        records=list(records or []),
    )
```

`src/kbparser/cli.py` import and version snippets

```python
from . import __version__
from .dispatcher import SUPPORTED, UnsupportedFormat, dispatch
from .export import to_output, write_json
from .records import build_records
from .validation import ValidationError, validate
from .versioning import RECORDS_VERSION, SCHEMA_VERSION
```

```python
        manifest = {
            "kbparser_version": __version__,
            "schema_version": SCHEMA_VERSION,
            "records_version": RECORDS_VERSION,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "root": str(src),
            "profile": args.profile,
            "results": results,
        }
```

```python
    checks.append(("kbparser", "PASS", f"v{__version__} (schema {SCHEMA_VERSION}, records {RECORDS_VERSION})"))
```

`src/kbparser/parsers/docx.py`

```python
from ..versioning import PACKAGE_VERSION
from ..ids import block_id, section_id, table_id
from ..model import Block, Document, Section, Table, TableCell, Warning
from .base import ParseContext, build_source_and_parse


class DOCXParser:
    name = "docx"
    version = PACKAGE_VERSION
    formats = ("docx",)
```

`src/kbparser/parsers/excel.py`

```python
from ..versioning import PACKAGE_VERSION
from ..ids import region_id, sheet_id, table_id
from ..model import Document, Sheet, SheetRegion, Table, TableCell, Warning
from .base import ParseContext, build_source_and_parse


class ExcelParser:
    name = "excel"
    version = PACKAGE_VERSION
    formats = ("xlsx", "xls")
```

`src/kbparser/parsers/pdf.py`

```python
from ..versioning import PACKAGE_VERSION
from ..ids import block_id, section_id, table_id
from ..model import (
    Block,
    Document,
    Page,
    Provenance,
    Section,
    Table,
    TableCell,
    Warning,
)
from .base import ParseContext, build_source_and_parse
from .ocr import find_tesseract, ocr_page


class PDFParser:
    name = "pdf"
    version = PACKAGE_VERSION
    formats = ("pdf",)
```

`src/kbparser/parsers/doc.py`

```python
from ..versioning import PACKAGE_VERSION
from ..ids import block_id, section_id, table_id
from ..model import Document, Warning
from .base import ParseContext, build_source_and_parse
from .docx import DOCXParser


class DOCParser:
    name = "doc"
    version = PACKAGE_VERSION
    formats = ("doc",)
```

- [ ] **Step 4: Run the version tests to verify they pass**

Run:

```bash
pytest tests/test_stability_hardening.py::test_parser_versions_match_package_version tests/test_stability_hardening.py::test_to_output_uses_shared_version_constants -v
```

Expected: PASS for both tests.

- [ ] **Step 5: Verify packaging still builds with dynamic versioning**

Run:

```bash
python -m build
```

Expected: PASS with both sdist and wheel artifacts under `dist/`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/kbparser/versioning.py src/kbparser/__init__.py src/kbparser/cli.py src/kbparser/export.py src/kbparser/parsers/doc.py src/kbparser/parsers/docx.py src/kbparser/parsers/excel.py src/kbparser/parsers/pdf.py tests/test_stability_hardening.py
git commit -m "fix: centralize version ownership"
```

### Task 2: Fix parse timestamp lifecycle

**Files:**
- Modify: `src/kbparser/parsers/base.py:53-112`
- Modify: `src/kbparser/parsers/docx.py:29-60`
- Modify: `src/kbparser/parsers/excel.py:51-76,79-104,107-175`
- Modify: `src/kbparser/parsers/pdf.py:49-140`
- Modify: `src/kbparser/parsers/doc.py:51-99`
- Modify: `tests/test_stability_hardening.py`
- Test: `tests/test_stability_hardening.py`

- [ ] **Step 1: Add failing timestamp-lifecycle tests**

Append to `tests/test_stability_hardening.py`:

```python
from kbparser.parsers.base import ParseContext, build_source_and_parse, finalize_parse
from .fixtures_gen.build_docx import build_basic as build_docx


def test_build_source_and_parse_keeps_finished_at_equal_to_started_at_until_finalize(tmp_path):
    sample = tmp_path / "sample.docx"
    sample.write_bytes(b"PK\x03\x04" + b"0" * 128)
    ctx = ParseContext(path=sample, profile="fidelity")

    _, parse, _ = build_source_and_parse(
        ctx,
        "docx",
        "docx",
        PACKAGE_VERSION,
        started_at="2026-04-14T00:00:00+00:00",
    )

    assert parse.started_at == "2026-04-14T00:00:00+00:00"
    assert parse.finished_at == "2026-04-14T00:00:00+00:00"

    finalize_parse(parse)
    assert parse.finished_at >= parse.started_at


def test_docx_parser_finalizes_parse_metadata(tmp_path):
    docx_path = build_docx(tmp_path / "sample.docx")
    doc = DOCXParser().parse(ParseContext(path=docx_path, profile="fidelity"))

    assert doc.parse.started_at
    assert doc.parse.finished_at
    assert doc.parse.finished_at >= doc.parse.started_at
    assert doc.parse.parser_version == PACKAGE_VERSION
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_stability_hardening.py::test_build_source_and_parse_keeps_finished_at_equal_to_started_at_until_finalize tests/test_stability_hardening.py::test_docx_parser_finalizes_parse_metadata -v
```

Expected: FAIL on `assert parse.finished_at == "2026-04-14T00:00:00+00:00"` because `build_source_and_parse()` stamps a real finish time too early.

- [ ] **Step 3: Implement parse finalization**

`src/kbparser/parsers/base.py`

```python
def build_source_and_parse(
    ctx: ParseContext,
    fmt: str,
    parser_name: str,
    parser_version: str,
    *,
    started_at: str,
    ocr_used: bool = False,
    conversion_used: bool = False,
    confidence: float = 1.0,
    conversion_info: dict | None = None,
) -> tuple[Source, Parse, str]:
    p = ctx.path
    sha = sha256_file(p)
    src = Source(
        path=str(p.resolve()),
        filename=p.name,
        format=fmt,
        mime_type=_mime(p, fmt),
        sha256=sha,
        size_bytes=p.stat().st_size,
        modified_at=_iso_mtime(p),
    )
    parse = Parse(
        parser=parser_name,
        parser_version=parser_version,
        started_at=started_at,
        finished_at=started_at,
        ocr_used=ocr_used,
        conversion_used=conversion_used,
        confidence=confidence,
        profile=ctx.profile,
        conversion_info=conversion_info,
    )
    return src, parse, doc_id(sha, ctx.profile)


def finalize_parse(parse: Parse) -> Parse:
    parse.finished_at = _iso_now()
    return parse
```

`src/kbparser/parsers/base.py` `empty_document()` tail

```python
    return Document(
        id=did,
        source=src,
        metadata={},
        parse=finalize_parse(parse),
        warnings=[Warning(code=warning_code, message=warning_message)],
    )
```

`src/kbparser/parsers/base.py` export list

```python
__all__ = ["Parser", "ParseContext", "build_source_and_parse", "finalize_parse", "empty_document"]
```

`src/kbparser/parsers/docx.py`

```python
from .base import ParseContext, build_source_and_parse, finalize_parse
```

```python
        doc = Document(
            id=did,
            source=src,
            metadata=metadata,
            parse=finalize_parse(parse),
            warnings=warnings,
            sections=state.sections,
            blocks=state.blocks,
            tables=state.tables,
        )
        return doc
```

`src/kbparser/parsers/excel.py`

```python
from .base import ParseContext, build_source_and_parse, finalize_parse
```

```python
def _assemble_document(src, parse, did: str, metadata: dict, sheet_inputs: list[_SheetInput]) -> Document:
    sheets: list[Sheet] = []
    tables: list[Table] = []
    warnings: list[Warning] = []
    formula_seen = False

    for si in sheet_inputs:
        sid = sheet_id(did, si.name, si.index)
        regions: list[SheetRegion] = []
        sheet_tables: list[Table] = []

        components = _flood_fill_components(si.grid_f, si.merges)
        for order, comp in enumerate(components):
            r0, c0, r1, c1 = _bbox(comp)
            rng = f"{get_column_letter(c0)}{r0}:{get_column_letter(c1)}{r1}"
            height = r1 - r0 + 1
            width = c1 - c0 + 1

            if height >= 2 and width >= 2:
                tid = table_id(did, f"sheet:{sid}:{rng}", order)
                tbl, had_formula = _build_table(
                    tid, sid, si.name, None, None,
                    si.grid_f, si.grid_c, si.merges, r0, c0, r1, c1,
                )
                tables.append(tbl)
                sheet_tables.append(tbl)
                formula_seen = formula_seen or had_formula
                regions.append(SheetRegion(
                    id=region_id(sid, rng), kind="data_table", range=rng, table_id=tid,
                ))
            else:
                texts = [
                    _cell_text(si.grid_f.get((r, c))) or ""
                    for r in range(r0, r1 + 1)
                    for c in range(c0, c1 + 1)
                ]
                joined = " ".join(t for t in texts if t).strip()
                regions.append(SheetRegion(
                    id=region_id(sid, rng),
                    kind="note",
                    range=rng,
                    text=joined or None,
                ))

        sheets.append(Sheet(
            id=sid,
            sheet_name=si.name,
            index=si.index,
            visibility=si.visibility,
            used_range=si.used_range,
            table_ids=[t.id for t in sheet_tables],
            regions=regions,
        ))

    if formula_seen:
        warnings.append(Warning(
            code="formula_not_evaluated",
            message="Formulas captured as strings; cached values used when available.",
        ))

    return Document(
        id=did,
        source=src,
        metadata=metadata,
        parse=finalize_parse(parse),
        warnings=warnings,
        sheets=sheets,
        tables=tables,
    )
```

`src/kbparser/parsers/pdf.py`

```python
from .base import ParseContext, build_source_and_parse, finalize_parse
```

```python
        return Document(
            id=did,
            source=src,
            metadata=_pdf_metadata(ctx.path),
            parse=finalize_parse(parse),
            warnings=warnings,
            sections=state.sections,
            blocks=state.blocks,
            tables=tables_out,
            pages=pages_out,
        )
```

`src/kbparser/parsers/doc.py`

```python
from .base import ParseContext, build_source_and_parse, finalize_parse
```

```python
        inner_doc.id = did
        inner_doc.source = src
        inner_doc.parse = finalize_parse(parse)
        inner_doc.parse.conversion_used = True
        inner_doc.parse.conversion_info = {
            "from_format": "doc",
            "to_format": "docx",
            "converter": result.converter,
            "converter_version": result.converter_version,
        }
```

- [ ] **Step 4: Run the timestamp tests to verify they pass**

Run:

```bash
pytest tests/test_stability_hardening.py::test_build_source_and_parse_keeps_finished_at_equal_to_started_at_until_finalize tests/test_stability_hardening.py::test_docx_parser_finalizes_parse_metadata -v
```

Expected: PASS for both tests.

- [ ] **Step 5: Run the existing determinism regression that strips timestamps**

Run:

```bash
pytest tests/test_determinism.py::test_parse_determinism[build_docx-docx] tests/test_determinism.py::test_cli_output_determinism -v
```

Expected: PASS, confirming the lifecycle fix does not break deterministic output beyond timestamps.

- [ ] **Step 6: Commit**

```bash
git add src/kbparser/parsers/base.py src/kbparser/parsers/doc.py src/kbparser/parsers/docx.py src/kbparser/parsers/excel.py src/kbparser/parsers/pdf.py tests/test_stability_hardening.py
git commit -m "fix: finalize parse timestamps"
```

### Task 3: Classify OCR soft-failures

**Files:**
- Modify: `src/kbparser/model.py:30-40`
- Modify: `src/kbparser/parsers/ocr.py:20-91`
- Modify: `src/kbparser/parsers/pdf.py:56-80,241-296`
- Modify: `tests/test_pdf_ocr.py:35-92`
- Test: `tests/test_pdf_ocr.py`

- [ ] **Step 1: Add failing OCR timeout/error tests**

Append to `tests/test_pdf_ocr.py`:

```python
from kbparser.parsers.ocr import OCREngineError, OCRTimeout


def test_scanned_with_ocr_timeout_emits_timeout_warning(monkeypatch, scanned_pdf: Path):
    from kbparser.parsers import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "find_tesseract", lambda: "/fake/tesseract")

    def boom(*args, **kwargs):
        raise OCRTimeout("timed out")

    monkeypatch.setattr(pdf_mod, "ocr_page", boom)
    d = _parse(scanned_pdf)
    assert d.parse.ocr_used is False
    assert any(
        w.code == "ocr_skipped_timeout"
        and (w.scope or {}).get("pages_missing_ocr") == [1]
        for w in d.warnings
    )
    validate(d)



def test_scanned_with_ocr_error_emits_error_warning(monkeypatch, scanned_pdf: Path):
    from kbparser.parsers import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "find_tesseract", lambda: "/fake/tesseract")

    def boom(*args, **kwargs):
        raise OCREngineError("ocr engine failed")

    monkeypatch.setattr(pdf_mod, "ocr_page", boom)
    d = _parse(scanned_pdf)
    assert d.parse.ocr_used is False
    assert any(
        w.code == "ocr_skipped_error"
        and (w.scope or {}).get("pages_missing_ocr") == [1]
        for w in d.warnings
    )
    validate(d)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_pdf_ocr.py::test_scanned_with_ocr_timeout_emits_timeout_warning tests/test_pdf_ocr.py::test_scanned_with_ocr_error_emits_error_warning -v
```

Expected: FAIL with `ImportError` or a warning-code validation failure because `OCRTimeout`, `OCREngineError`, and the new warning codes do not exist yet.

- [ ] **Step 3: Implement OCR runtime classification and PDF warning mapping**

`src/kbparser/model.py`

```python
WarningCode = Literal[
    "ocr_applied_to_pages",
    "ocr_skipped_missing_binary",
    "ocr_skipped_empty_result",
    "ocr_skipped_timeout",
    "ocr_skipped_error",
    "table_structure_uncertain",
    "doc_conversion_lost_styles",
    "formula_not_evaluated",
    "header_footer_filtered_heuristically",
    "heading_inference_low_confidence",
    "parser_stub_used",
]
```

`src/kbparser/parsers/ocr.py`

```python
from dataclasses import dataclass
from pathlib import Path
import shutil

TESSERACT_CANDIDATES = (
    "tesseract",
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
)


class OCRTimeout(RuntimeError):
    pass


class OCREngineError(RuntimeError):
    pass


@dataclass
class OCRResult:
    text: str
    bbox: tuple[float, float, float, float]


def _image_to_data(pytesseract, img, *, lang: str, timeout_seconds: int):
    try:
        return pytesseract.image_to_data(
            img,
            output_type=pytesseract.Output.DICT,
            lang=lang,
            timeout=timeout_seconds,
        )
    except pytesseract.TesseractError:
        if lang != "eng":
            return pytesseract.image_to_data(
                img,
                output_type=pytesseract.Output.DICT,
                timeout=timeout_seconds,
            )
        raise


def ocr_page(
    fitz_page,
    tesseract_bin: str,
    dpi: int = 300,
    lang: str = "eng",
    timeout_seconds: int = 20,
) -> list[OCRResult]:
    import fitz
    import io
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = tesseract_bin

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = fitz_page.get_pixmap(matrix=matrix, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png")))

    try:
        data = _image_to_data(pytesseract, img, lang=lang, timeout_seconds=timeout_seconds)
    except RuntimeError as exc:
        message = str(exc)
        lowered = message.lower()
        if "time" in lowered and "out" in lowered:
            raise OCRTimeout(message) from exc
        raise OCREngineError(message) from exc
    except pytesseract.TesseractError as exc:
        raise OCREngineError(str(exc)) from exc

    lines: dict[tuple[int, int, int], dict] = {}
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x = data["left"][i] / zoom
        y = data["top"][i] / zoom
        w = data["width"][i] / zoom
        h = data["height"][i] / zoom
        entry = lines.setdefault(key, {
            "words": [], "x0": x, "y0": y, "x1": x + w, "y1": y + h,
        })
        entry["words"].append(text)
        entry["x0"] = min(entry["x0"], x)
        entry["y0"] = min(entry["y0"], y)
        entry["x1"] = max(entry["x1"], x + w)
        entry["y1"] = max(entry["y1"], y + h)

    results: list[OCRResult] = []
    for _, info in sorted(lines.items()):
        results.append(OCRResult(
            text=" ".join(info["words"]),
            bbox=(info["x0"], info["y0"], info["x1"], info["y1"]),
        ))
    return results
```

`src/kbparser/parsers/pdf.py`

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
import pdfplumber

from ..ids import block_id, section_id, table_id
from ..model import (
    Block,
    Document,
    Page,
    Provenance,
    Section,
    Table,
    TableCell,
    Warning,
)
from ..versioning import PACKAGE_VERSION
from .base import ParseContext, build_source_and_parse, finalize_parse
from .ocr import OCREngineError, OCRTimeout, find_tesseract, ocr_page
```

```python
@dataclass
class _OCRSummary:
    applied_pages: list[int] = field(default_factory=list)
    missing_binary_pages: list[int] = field(default_factory=list)
    timeout_pages: list[int] = field(default_factory=list)
    error_pages: list[int] = field(default_factory=list)
    empty_pages: list[int] = field(default_factory=list)
```

```python
    ocr = _maybe_ocr(
        ctx.path,
        raw_pages,
        profile=ctx.profile,
        lang=ctx.ocr_langs or "eng",
    )
    if ocr.applied_pages:
        parse.ocr_used = True
        warnings.append(Warning(
            code="ocr_applied_to_pages",
            message=f"OCR applied to {len(ocr.applied_pages)} page(s) with weak text layer.",
            scope={"pages": ocr.applied_pages},
        ))
    if ocr.missing_binary_pages:
        warnings.append(Warning(
            code="ocr_skipped_missing_binary",
            message=(
                "Page(s) lack a text layer but Tesseract is not installed. "
                "Install via `brew install tesseract` / `apt install tesseract-ocr` "
                "to recover text."
            ),
            scope={"pages_missing_ocr": ocr.missing_binary_pages},
        ))
    if ocr.timeout_pages:
        warnings.append(Warning(
            code="ocr_skipped_timeout",
            message="OCR timed out for page(s) with weak text layer; file parsing continued without OCR text.",
            scope={"pages_missing_ocr": ocr.timeout_pages},
        ))
    if ocr.error_pages:
        warnings.append(Warning(
            code="ocr_skipped_error",
            message="OCR failed for page(s) with weak text layer; file parsing continued without OCR text.",
            scope={"pages_missing_ocr": ocr.error_pages},
        ))
    if ocr.empty_pages:
        warnings.append(Warning(
            code="ocr_skipped_empty_result",
            message="Tesseract produced no output for page(s); OCR effectively failed.",
            scope={"pages_missing_ocr": ocr.empty_pages},
        ))
```

```python
def _maybe_ocr(
    path: Path,
    pages: list[_PdfPage],
    *,
    profile: str,
    lang: str = "eng",
) -> _OCRSummary:
    if profile == "text-lite":
        return _OCRSummary()

    candidates = [
        p for p in pages
        if p.total_chars < _OCR_TEXT_THRESHOLD and (p.has_images or p.total_chars == 0)
    ]
    if not candidates:
        return _OCRSummary()

    tesseract = find_tesseract()
    if tesseract is None:
        return _OCRSummary(missing_binary_pages=[p.number for p in candidates])

    import fitz

    summary = _OCRSummary()
    with fitz.open(str(path)) as doc:
        for p in candidates:
            fitz_page = doc[p.number - 1]
            try:
                results = ocr_page(fitz_page, tesseract, lang=lang)
            except OCRTimeout:
                summary.timeout_pages.append(p.number)
                continue
            except OCREngineError:
                summary.error_pages.append(p.number)
                continue

            if not results:
                summary.empty_pages.append(p.number)
                continue

            added_text = False
            for r in results:
                text = r.text.strip()
                if not text:
                    continue
                p.blocks.append(_PdfBlock(
                    text=text,
                    bbox=r.bbox,
                    spans=[_Span(text=text, size=11.0, font="ocr", bbox=r.bbox)],
                    dominant_size=11.0,
                    is_bold=False,
                ))
                p.total_chars += len(text)
                added_text = True
            if not added_text:
                summary.empty_pages.append(p.number)
                continue
            p.blocks.sort(key=lambda b: (round(b.bbox[1], 1), round(b.bbox[0], 1)))
            summary.applied_pages.append(p.number)
    return summary
```

- [ ] **Step 4: Run the OCR regression tests to verify they pass**

Run:

```bash
pytest tests/test_pdf_ocr.py::test_scanned_with_ocr_timeout_emits_timeout_warning tests/test_pdf_ocr.py::test_scanned_with_ocr_error_emits_error_warning tests/test_pdf_ocr.py::test_scanned_with_empty_ocr_result_emits_skipped_warning -v
```

Expected: PASS for all three tests.

- [ ] **Step 5: Run the existing scanned-PDF happy path and no-binary regressions**

Run:

```bash
pytest tests/test_pdf_ocr.py::test_scanned_without_tesseract_emits_skipped_warning tests/test_pdf_ocr.py::test_text_lite_profile_skips_ocr -v
```

Expected: PASS, confirming the new warning taxonomy did not break existing OCR policy.

- [ ] **Step 6: Commit**

```bash
git add src/kbparser/model.py src/kbparser/parsers/ocr.py src/kbparser/parsers/pdf.py tests/test_pdf_ocr.py
git commit -m "fix: classify ocr soft failures"
```

### Task 4: Make DOC conversion failures explicit

**Files:**
- Modify: `src/kbparser/parsers/doc.py:35-151`
- Modify: `tests/test_doc_parser.py:35-86`
- Test: `tests/test_doc_parser.py`

- [ ] **Step 1: Add failing DOC conversion regression tests**

Append to `tests/test_doc_parser.py`:

```python
import subprocess

from kbparser.parsers.doc import (
    DOCParser,
    DocConversionFailed,
    DocConversionNoOutput,
    DocConversionTimeout,
    DocConverterMissing,
    _find_soffice,
)


def test_doc_timeout_raises_typed_error(monkeypatch, tmp_path: Path):
    src = _write_fake_doc(tmp_path / "timeout.doc")
    monkeypatch.setattr("kbparser.parsers.doc._find_soffice", lambda: "/fake/soffice")

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["soffice"], timeout=120)

    monkeypatch.setattr("kbparser.parsers.doc.subprocess.run", slow)
    with pytest.raises(DocConversionTimeout):
        DOCParser().parse(ParseContext(path=src, profile="fidelity"))


def test_doc_missing_output_raises_typed_error(monkeypatch, tmp_path: Path):
    src = _write_fake_doc(tmp_path / "missing-output.doc")
    monkeypatch.setattr("kbparser.parsers.doc._find_soffice", lambda: "/fake/soffice")

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("kbparser.parsers.doc.subprocess.run", lambda *args, **kwargs: Result())
    with pytest.raises(DocConversionNoOutput):
        DOCParser().parse(ParseContext(path=src, profile="fidelity"))


def test_cli_reports_failed_when_doc_conversion_times_out(monkeypatch, tmp_path: Path):
    src = _write_fake_doc(tmp_path / "cli-timeout.doc")
    out = tmp_path / "out"
    monkeypatch.setattr("kbparser.parsers.doc._find_soffice", lambda: "/fake/soffice")

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["soffice"], timeout=120)

    monkeypatch.setattr("kbparser.parsers.doc.subprocess.run", slow)
    rc = main(["parse", str(src), "--out", str(out)])
    assert rc == 1
    assert not list(out.glob("*.json"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_doc_parser.py::test_doc_timeout_raises_typed_error tests/test_doc_parser.py::test_doc_missing_output_raises_typed_error tests/test_doc_parser.py::test_cli_reports_failed_when_doc_conversion_times_out -v
```

Expected: FAIL with `ImportError` because the new typed conversion exception classes do not exist yet.

- [ ] **Step 3: Implement typed DOC conversion failures**

`src/kbparser/parsers/doc.py`

```python
class DocConverterMissing(RuntimeError):
    pass


class DocConversionTimeout(RuntimeError):
    pass


class DocConversionFailed(RuntimeError):
    pass


class DocConversionNoOutput(RuntimeError):
    pass
```

```python
def _convert_to_docx(bin_path: str, src: Path, out_dir: Path) -> _ConversionResult:
    user_install = out_dir / "lo-profile"
    user_install.mkdir(exist_ok=True)
    cmd = [
        bin_path,
        "--headless",
        "--nologo",
        "--nofirststartwizard",
        f"-env:UserInstallation=file://{user_install}",
        "--convert-to",
        "docx",
        "--outdir",
        str(out_dir),
        str(src),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DocConversionTimeout(f"soffice conversion timed out after {int(exc.timeout)}s") from exc
    except OSError as exc:
        raise DocConversionFailed(f"soffice invocation failed: {exc}") from exc

    if res.returncode != 0:
        raise DocConversionFailed(
            f"soffice conversion failed ({res.returncode}): {(res.stderr or res.stdout or '').strip()}"
        )

    out_docx = out_dir / (src.stem + ".docx")
    if not out_docx.exists():
        raise DocConversionNoOutput(f"soffice produced no output for {src}")

    return _ConversionResult(
        docx_path=out_docx,
        converter=Path(bin_path).name,
        converter_version=_soffice_version(bin_path),
    )
```

- [ ] **Step 4: Run the DOC conversion tests to verify they pass**

Run:

```bash
pytest tests/test_doc_parser.py::test_doc_timeout_raises_typed_error tests/test_doc_parser.py::test_doc_missing_output_raises_typed_error tests/test_doc_parser.py::test_cli_reports_failed_when_doc_conversion_times_out -v
```

Expected: PASS for all three tests.

- [ ] **Step 5: Run the existing DOC parser regressions**

Run:

```bash
pytest tests/test_doc_parser.py::test_missing_soffice_raises tests/test_doc_parser.py::test_cli_reports_failed_when_no_soffice -v
```

Expected: PASS, confirming the new typed failures preserve the hard-fail contract.

- [ ] **Step 6: Commit**

```bash
git add src/kbparser/parsers/doc.py tests/test_doc_parser.py
git commit -m "fix: type doc conversion failures"
```

### Task 5: Add Makefile-backed repo smoke verification

**Files:**
- Create: `tests/test_repo_smoke.py`
- Modify: `Makefile:1-24`
- Test: `tests/test_repo_smoke.py`

- [ ] **Step 1: Write the failing repo-smoke tests**

`tests/test_repo_smoke.py`

```python
import json
from pathlib import Path

from kbparser import __version__
from kbparser.cli import main
from kbparser.versioning import RECORDS_VERSION, SCHEMA_VERSION

from .fixtures_gen.build_docx import build_basic as build_docx
from .fixtures_gen.build_pdf import build_basic as build_pdf
from .fixtures_gen.build_xlsx import build_basic as build_xlsx


def test_batch_manifest_uses_shared_versions(tmp_path: Path):
    indir = tmp_path / "in"
    indir.mkdir()
    build_pdf(indir / "a.pdf")
    build_docx(indir / "b.docx")
    build_xlsx(indir / "c.xlsx")
    outdir = tmp_path / "out"

    rc = main(["parse", str(indir), "--out", str(outdir)])
    assert rc == 0

    manifest = json.loads((outdir / "manifest.json").read_text())
    assert manifest["kbparser_version"] == __version__
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["records_version"] == RECORDS_VERSION
    assert [r["status"] for r in manifest["results"]] == ["success", "success", "success"]


def test_single_file_output_uses_shared_versions(tmp_path: Path):
    infile = build_pdf(tmp_path / "sample.pdf")
    outdir = tmp_path / "out"

    rc = main(["parse", str(infile), "--out", str(outdir)])
    assert rc == 0

    payload = json.loads(next(outdir.glob("*.json")).read_text())
    assert payload["parser_version"] == __version__
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["records_version"] == RECORDS_VERSION


def test_makefile_exposes_smoke_target():
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    assert "\nsmoke:\n" in makefile
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_repo_smoke.py::test_makefile_exposes_smoke_target -v
```

Expected: FAIL on `assert "\nsmoke:\n" in makefile` because the target does not exist yet.

- [ ] **Step 3: Implement the smoke target and keep the tests green**

`Makefile`

```make
.PHONY: install test lint typecheck build clean doctor smoke

install:
	pip install -e ".[dev,lint]"

test:
	pytest

lint:
	ruff check src/ tests/

typecheck:
	mypy src/kbparser/

build:
	python -m build

clean:
	rm -rf dist/ build/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

doctor:
	kbparser doctor

smoke:
	python -m kbparser.cli --version
	python -m kbparser.cli doctor
	pytest tests/test_repo_smoke.py -q
```

- [ ] **Step 4: Run the repo-smoke tests to verify they pass**

Run:

```bash
pytest tests/test_repo_smoke.py -v
```

Expected: PASS for all three tests.

- [ ] **Step 5: Run the smoke target exactly as developers will use it**

Run:

```bash
make smoke
```

Expected: PASS. Output includes `kbparser 0.2.0`, doctor results, and a green `tests/test_repo_smoke.py` run.

- [ ] **Step 6: Commit**

```bash
git add Makefile tests/test_repo_smoke.py
git commit -m "test: add repo smoke verification"
```

### Task 6: Run the full regression suite for the hardening branch

**Files:**
- Test: `tests/test_stability_hardening.py`
- Test: `tests/test_pdf_ocr.py`
- Test: `tests/test_doc_parser.py`
- Test: `tests/test_repo_smoke.py`
- Test: `tests/test_determinism.py`
- Test: `tests/test_smoke_cli.py`

- [ ] **Step 1: Run the focused hardening tests together**

Run:

```bash
pytest tests/test_stability_hardening.py tests/test_pdf_ocr.py tests/test_doc_parser.py tests/test_repo_smoke.py -v
```

Expected: PASS for all focused hardening tests.

- [ ] **Step 2: Run the determinism and CLI smoke regressions**

Run:

```bash
pytest tests/test_determinism.py tests/test_smoke_cli.py -v
```

Expected: PASS for both suites.

- [ ] **Step 3: Run the full repository test suite**

Run:

```bash
pytest -q
```

Expected: PASS with existing skips preserved and no new failures.

- [ ] **Step 4: Run the repo smoke target one more time after the full suite**

Run:

```bash
make smoke
```

Expected: PASS.

- [ ] **Step 5: Commit the fully verified branch state**

```bash
git status --short
git commit -m "chore: verify stability hardening" --allow-empty
```

Expected: clean history boundary marking the verified end state.
