# kbparser handoff — 2026-04-15

## Что это
- Проект: локальный parser документов в KB-ready JSON для LLM/RAG.
- CLI entrypoint: `kbparser.cli:main` (`pyproject.toml:27-28`).
- Команды: `parse`, `doctor` (`src/kbparser/cli.py:92-129`).
- Output model: `document` + `records`, versioned (`src/kbparser/model.py`, `src/kbparser/versioning.py`).

## Живой статус, проверен в этой сессии
- Smoke passed:
  - `"/Users/username/Desktop/llm-kb-parser — копия/venv/bin/python" -m kbparser.cli --version`
  - `"/Users/username/Desktop/llm-kb-parser — копия/venv/bin/python" -m kbparser.cli doctor`
  - `"/Users/username/Desktop/llm-kb-parser — копия/venv/bin/python" -m pytest tests/test_repo_smoke.py -q`
- Full tests passed:
  - `"/Users/username/Desktop/llm-kb-parser — копия/venv/bin/python" -m pytest`
  - result: `110 passed, 2 skipped, 5 warnings`
- Lint/typecheck не прогнаны до green в этой сессии: repo-local venv не содержит `ruff`/`mypy` executables.

## Поддерживаемые форматы
- Прямо поддержаны: `pdf`, `docx`, `doc`, `xlsx`, `xls` (`src/kbparser/dispatcher.py:12-36`).
- Не поддержаны напрямую: `png`, `txt`.
- OCR работает как ветка PDF parser, а не как parser изображений (`src/kbparser/parsers/pdf.py`).

## Что сделали в этой сессии вне repo
Распарсили пакет документов из:
- `/Users/username/Downloads/ldskapustin_docs_tmp`

Артефакты:
- outputs: `/Users/username/Downloads/ldskapustin_docs_tmp/kb-parse-out`
- output count: 18 JSON
- unsupported обходили так:
  - `txt -> docx`
  - `png -> pdf`
- много `partial` из-за OCR/weak text layer на русском до установки `rus`.

## OCR upgrade, выполнен и проверен
До апгрейда:
- `tesseract --list-langs` показывал только `eng`, `osd`, `snum`.

Сделано:
- `brew install tesseract-lang`

После апгрейда:
- `tesseract --list-langs` показывает `rus` среди доступных языков.
- `"/Users/username/Desktop/llm-kb-parser — копия/venv/bin/kbparser" doctor` passed after upgrade.

## Текущие незакоммиченные изменения в repo
`git status --short`:
- `M SKILL.md`
- `M src/kbparser/parsers/pdf.py`
- `M tests/test_pdf_parser.py`

### Что менялось
#### 1) `src/kbparser/parsers/pdf.py:57-61,106-109,151-155`
- metadata читается заранее: `metadata = _pdf_metadata(ctx.path)`.
- добавлен fallback root section, если heading не найден:
  - если `raw_pages` есть и ни один блок не помечен как heading,
  - создается section из `metadata.title` или `ctx.path.stem`.
- это страхует pipeline records/chunker от PDF без headings.

#### 2) `tests/test_pdf_parser.py:113-126`
- добавлен test `test_root_section_fallback_when_no_headings`.
- monkeypatch отключает `_assign_heading_levels`, затем проверяет:
  - есть ровно одна section,
  - section покрывает pages 1..2,
  - non-heading blocks привязаны к section,
  - `build_records(d)` дает непустой результат и есть `chunk`.

#### 3) `SKILL.md:12-27`
- skill обновлен под repo-local runtime.
- теперь Quick Start и doctor используют:
  - `"/Users/username/Desktop/llm-kb-parser — копия/venv/bin/kbparser"`
- явно записано: не предполагать `kbparser` в global PATH.

## Практические команды
### Smoke
```bash
cd "/Users/username/Desktop/llm-kb-parser — копия"
"/Users/username/Desktop/llm-kb-parser — копия/venv/bin/python" -m kbparser.cli --version
"/Users/username/Desktop/llm-kb-parser — копия/venv/bin/python" -m kbparser.cli doctor
"/Users/username/Desktop/llm-kb-parser — копия/venv/bin/python" -m pytest tests/test_repo_smoke.py -q
```

### Full tests
```bash
cd "/Users/username/Desktop/llm-kb-parser — копия"
"/Users/username/Desktop/llm-kb-parser — копия/venv/bin/python" -m pytest
```

### Parse example with Russian OCR
```bash
"/Users/username/Desktop/llm-kb-parser — копия/venv/bin/kbparser" parse <path> --profile fidelity --overwrite --lang rus+eng
```

## Next sensible steps
1. Fresh re-parse scanned Russian docs with `--lang rus+eng`.
2. If нужен clean dev loop, install lint extras into repo venv:
   - `pip install -e ".[dev,lint]"`
3. Если изменения в `pdf.py` и test валидны по intent — commit их отдельно от docs/skill changes.
