# kbparser

Local document → rich JSON and Markdown parser for LLM knowledge-base ingestion.

**Supported input formats:** PDF, DOCX, DOC (via LibreOffice), XLS, XLSX.
**Default output:** JSON + Markdown (`.json` for KB pipelines, `.md` for human review).

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

# Markdown-only export
kbparser parse document.docx --out ./output --format md

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

## Desktop App

The package also ships a small Tkinter desktop app:

```bash
kbparser-gui
```

Version 0.3 adds a Russian interface, per-file results, live logs, cancellation,
and a Markdown/JSON text preview. Cancellation is checked between PDF pages,
OCR operations, and document/workbook items; an active external conversion
finishes before cancellation takes effect.

Exports preserve introductory text and table positions. Existing outputs are
reused only after checking their content identity and parse settings; name
collisions receive stable suffixes, and writes use atomic replacement. Derived
table records contain row spans and repeat headers across row groups. A single
row larger than the record budget stays intact and is marked `oversized_row`.

macOS builds require Tcl/Tk 8.6.13 or newer. Tk 8.6.12 can ignore input until
the window moves ([CPython #110218](https://github.com/python/cpython/issues/110218)).
The build validates its toolkit and writes the actual package version into
the app bundle. Updating the host Python does not update an already bundled app.

For distributable builds, install the build extras and run:

```bash
pip install ".[dev,build]"
python scripts/build_apps.py
```

The build writes self-contained PyInstaller artifacts under `dist/apps/`:

- `kbparser` / `kbparser.exe` — command-line parser
- `KBParser.app` on macOS, or `KBParser.exe` on Windows — desktop app

Set `KBPARSER_DIST_ROOT=/tmp/kbparser-apps` to write the build output outside
the repository, which is useful on macOS when the checkout lives in a synced
Desktop/iCloud folder.

GitHub Actions also builds Windows and macOS archives from `.github/workflows/build-apps.yml`.

Note: the bundled apps include Python and Python package dependencies. For
legacy `.doc` and scanned-PDF OCR, the app now detects LibreOffice/Tesseract
from system paths, explicit env overrides, or a portable `tools/` sidecar next
to the app.

## Android

Android is a separate Kotlin/Compose + Chaquopy app, not a PyInstaller build.
The app lives under `android/` and embeds Python 3.13 with a narrow mobile
facade:

- Local now: `.xls`, `.xlsx` through `kbparser.mobile.facade`, rendered as
  Markdown for the Android UI.
- Companion path now: `.doc`, `.docx`, `.pdf`, `.rtf` are routed through the
  external office engine contract `com.lyomagit.kbparser.officeengine`.
- Still external: OCR should be native Android OCR later, not `pytesseract`.
- Reason: desktop PyMuPDF, LibreOffice, Tkinter, and Tesseract CLI are not
  Android-safe assumptions inside the main APK.

Build the debug APK with:

```bash
ANDROID_HOME="$HOME/Library/Android/sdk" \
ANDROID_SDK_ROOT="$HOME/Library/Android/sdk" \
./android/gradlew -p android :app:assembleDebug
```

The generated artifact is `android/app/build/outputs/apk/debug/app-debug.apk`.
GitHub Actions also has `.github/workflows/android.yml` for the debug APK.

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
| LibreOffice | `.doc` parsing (converted to `.docx`) | macOS: `brew install --cask libreoffice`; Windows: official 64-bit stable installer |
| Tesseract | OCR on scanned PDF pages | macOS: `brew install tesseract tesseract-lang`; Windows: UB Mannheim 64-bit installer |

Run `kbparser doctor` to verify these are available. The desktop app also has a
**Setup tools** button with download links and portable sidecar layout.

Robust discovery order:

1. Explicit env overrides: `KBPARSER_LIBREOFFICE`, `KBPARSER_TESSERACT`, and `TESSDATA_PREFIX`.
2. `KBPARSER_TOOLS_DIR`, for example a shared tools directory.
3. Portable `tools/` next to the packaged app.
4. User tools folder:
   - macOS: `~/Library/Application Support/KBParser/tools`
   - Windows: `%LOCALAPPDATA%\KBParser\tools`
5. Standard system locations and `PATH`.

Portable sidecar examples:

- `tools/LibreOffice/program/soffice.exe`
- `tools/LibreOffice.app/Contents/MacOS/soffice`
- `tools/Tesseract-OCR/tesseract.exe`
- `tools/Tesseract-OCR/tessdata/rus.traineddata`

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
