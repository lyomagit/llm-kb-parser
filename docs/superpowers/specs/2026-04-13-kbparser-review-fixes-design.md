# kbparser Reviewer Fixes Design

**Goal:** Закрыть 4 замечания code review точечными изменениями, с regression tests на каждый дефект.

**Scope:** Только 4 подтверждённых проблемы: batch manifest directory creation, default `--out` for directory input, OCR skipped warning codes, Excel formula `raw_value` preservation.

## Current Problems

1. `kbparser/cli.py`
   - Для directory input default output path сейчас вычисляется как `<input_dir>/kb-parse-out`, а не `<input_parent>/kb-parse-out`.
   - При batch run, где все файлы падают до первого успешного write, `manifest.json` может писаться в несуществующий `out_dir`.

2. `kbparser/model.py` + `kbparser/parsers/pdf.py`
   - Warning schema не содержит отдельного code для OCR skipped / OCR failed-without-output.
   - PDF parser эмитит `ocr_applied_to_pages` даже для skipped/failed OCR cases, из-за чего теряется смысл warning.

3. `kbparser/parsers/excel.py`
   - Formula cells кладут `raw_value=None`, из-за чего downstream не может отличить formula cell от blank cell по canonical JSON.

## Design

### 1. CLI output path + manifest safety
- В `cmd_parse()` вычислять default `out_dir` так:
  - file input -> `<file_parent>/kb-parse-out`
  - dir input -> `<dir_parent>/kb-parse-out`
- Перед записью `manifest.json` гарантированно вызвать `out_dir.mkdir(parents=True, exist_ok=True)`.
- Не менять остальное поведение CLI.

### 2. OCR warning separation
- Расширить `WarningCode` новыми кодами для OCR skipped states:
  - `ocr_skipped_missing_binary`
  - `ocr_skipped_empty_result`
- В PDF parser:
  - `ocr_applied_to_pages` использовать только когда OCR реально дал текст.
  - При отсутствии `tesseract` эмитить `ocr_skipped_missing_binary`.
  - При пустом OCR результате эмитить `ocr_skipped_empty_result`.
- Scope по страницам сохранить в warning scope.

### 3. Excel formula preservation
- В `_build_table()` для formula cell:
  - `formula` = formula string
  - `raw_value` = original formula string
  - `display_value` = cached/display result
  - `text` оставить как display text, fallback к formula/raw text при отсутствии display.
- Не менять semantics non-formula cells.

## Tests

1. `tests/test_cli.py` или существующий CLI-focused test file:
   - directory input without `--out` -> output dir equals `<input_parent>/kb-parse-out`
   - batch where all parses fail still writes `manifest.json` and returns exit code 1

2. `tests/test_pdf_parser.py`
   - OCR candidate pages + missing tesseract -> warning code `ocr_skipped_missing_binary`
   - OCR candidate pages + empty OCR result -> warning code `ocr_skipped_empty_result`
   - existing `ocr_applied_to_pages` behavior remains for successful OCR

3. `tests/test_xls_parser.py` or `tests/test_excel_parser.py`
   - formula cell preserves `raw_value` as formula string and `display_value` as cached result

## Verification
- Run targeted pytest for new/changed tests first.
- Then run full suite: `venv/bin/pytest`.
- No extra refactor unless tests force it.
