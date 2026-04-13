# kbparser

Local document → rich JSON parser for LLM knowledge-base ingestion.

**Supported formats:** PDF, DOCX, DOC (via LibreOffice), XLS, XLSX.

## Install

```bash
# Clone and install in a virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Verify environment
kbparser doctor
```

## Usage

```bash
# Parse a single file
kbparser parse document.pdf

# Parse with options
kbparser parse document.docx --out ./output --profile fidelity --overwrite

# Parse a directory (batch mode)
kbparser parse ./documents/ --out ./output

# OCR for scanned PDFs
kbparser parse scanned.pdf --lang rus+eng
# or via environment variable:
KBPARSER_OCR_LANGS=rus+eng kbparser parse scanned.pdf

# Check runtime dependencies
kbparser doctor

# Version info
kbparser --version
```

## Output

Each parsed document produces a JSON file containing:

- **`document`** — canonical representation: source metadata, sections, blocks, tables, pages, sheets, assets, relationships, warnings
- **`records`** — retrieval-oriented projections for RAG/KB pipelines: `chunk`, `reference_chunk`, `diagram_chunk`, `table`, `section_summary_seed`, `sheet_region`

Output includes versioning fields: `schema_version`, `records_version`, `parser_version`.

Batch mode additionally writes `manifest.json` with per-file results, timings, record counts, and runtime metadata.

## Profiles

| Profile | Description |
|---------|-------------|
| `fidelity` | Maximum extraction fidelity (default) |
| `balanced` | Balance between fidelity and chunk cleanliness |
| `text-lite` | Minimal extraction, text-focused |

## Optional Dependencies

| Dependency | Required for | Install |
|------------|-------------|---------|
| LibreOffice | `.doc` parsing (converted to `.docx`) | `brew install libreoffice` or system package |
| Tesseract | OCR on scanned PDF pages | `brew install tesseract` + language packs |

Run `kbparser doctor` to verify these are available.

## Layout

```
src/kbparser/
├── __init__.py          # package version
├── cli.py               # CLI entrypoint + doctor command
├── dispatcher.py        # format detection → parser dispatch
├── export.py            # deterministic JSON writer
├── ids.py               # deterministic ID generation (SHA-256)
├── model.py             # canonical pydantic schema
├── normalize/           # normalization utilities
├── parsers/
│   ├── base.py          # parser protocol + shared helpers
│   ├── docx.py          # DOCX parser
│   ├── doc.py           # DOC parser (LibreOffice conversion)
│   ├── pdf.py           # PDF parser (pymupdf + pdfplumber + OCR)
│   ├── excel.py         # XLS/XLSX parser (openpyxl + xlrd)
│   └── ocr.py           # Tesseract OCR helper
├── records/
│   └── chunker.py       # records/chunk builder
└── validation/
    └── validator.py     # structural validation
```

## Development

```bash
pip install -e ".[dev,lint]"
pytest                   # run tests
ruff check src/ tests/   # lint
mypy src/kbparser/       # type check
```
