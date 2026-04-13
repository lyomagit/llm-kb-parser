---
name: llm-kb-parser
description: Parse local documents (PDF, DOCX, DOC, XLS, XLSX) into rich JSON for LLM knowledge-base ingestion.
---

# kbparser

Parse documents into structured JSON with canonical model + retrieval-oriented records.

## Quick Start

```bash
kbparser parse <path> [--out <dir>] [--profile fidelity|balanced|text-lite] [--overwrite] [--lang rus+eng]
```

## Environment Check

```bash
kbparser doctor
```

## Output Structure

- `document`: canonical sections, blocks, tables, pages, sheets, warnings
- `records`: `chunk`, `reference_chunk`, `diagram_chunk`, `table`, `section_summary_seed`, `sheet_region`
- Versioned: `schema_version`, `records_version`, `parser_version` in every output

## Optional Dependencies

- **LibreOffice** — required for `.doc` format
- **Tesseract** — required for OCR on scanned PDFs; set language via `--lang` or `KBPARSER_OCR_LANGS`
