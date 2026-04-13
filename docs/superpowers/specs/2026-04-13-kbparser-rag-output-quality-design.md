# kbparser RAG Output Quality Design

**Goal:** Сделать derived `records` пригодными для чистого KB/RAG ingest без потери данных из canonical `document`.

**Subproject:** Только records-layer quality cleanup. Parser portability, CLI, canonical `document`, OCR, Excel, table extraction и другие дефекты вне scope.

## Problem Statement

Текущее качество canonical `document` приемлемо, но derived `records` шумят для retrieval:
- prose chunks получаются слишком длинными;
- heading-only sections могут давать мусорный `chunk`;
- bibliography / citation / URL-dump content смешивается с prose;
- Mermaid / code-like blocks смешиваются с prose;
- table-wrapper sections дают prose noise рядом с отдельным `table` record.

Главный принцип этого дизайна: **не drop, а separate + label**.

## Architecture

1. Canonical `document` остаётся faithful и не меняется.
2. Меняется только derived `records` generation в `kbparser/records/chunker.py`.
3. Records становятся retrieval-oriented представлением с явным разделением типов контента.
4. Все content classes сохраняются, но попадают в разные record types.

## Files In Scope

- Modify: `kbparser/model.py`
- Modify: `kbparser/records/chunker.py`
- Modify: `tests/test_chunker.py`
- Modify: `tests/test_model.py`

## Output Model Changes

Текущий `RecordType` расширяется так, чтобы различать retrieval classes:
- `chunk` — prose-only content
- `reference_chunk` — bibliography / citation / URL-dump content
- `diagram_chunk` — mermaid / code-like / source-code-like content
- `table` — table linearization, как сейчас
- `section_summary_seed` — без расширения scope
- `sheet_region` — без изменений

## Chunking Rules

### 1. Prose chunks
- Содержат heading + prose body, если prose body есть.
- Не создаются, если section содержит только heading без prose body.
- Не включают `table_ref`, bibliography blocks, mermaid/code-like blocks.
- Целевой размер prose chunk: примерно 300–1200 chars.
- Hard split допустим только как fallback после semantic boundaries.

### 2. Reference chunks
- Содержат bibliography / citation lists / URL dumps.
- Не смешиваются с prose chunks.
- Должны сохранять исходный контент и lineage.

### 3. Diagram chunks
- Содержат Mermaid / flowchart / code-like blocks / source-code-styled text.
- Не смешиваются с prose chunks.
- Должны сохранять исходный контент и lineage.

### 4. Table records
- Остаются first-class records.
- Table-wrapper section (`heading + table_ref only`) не должна создавать prose noise.

## Heuristics

Эвристики должны быть явными и локализованными в `chunker.py`.

### Reference-like block
Block считается reference-like, если выполняется одно или несколько условий:
- высокая плотность URL;
- строки вида `[12] ...`, `[12] https://...`;
- короткие citation-style paragraphs подряд;
- список ссылок/источников в хвосте раздела.

### Diagram/code-like block
Block считается diagram/code-like, если выполняется одно или несколько условий:
- style name `Source Code`;
- текст начинается с `flowchart`, `graph`, `sequenceDiagram`, `pie title`;
- content выглядит как diagram/code syntax, а не prose.

### Prose-like block
Всё смысловое narrative content, не попавшее в reference-like или diagram/code-like.

## Acceptance Criteria

### Functional
1. `chunk` records содержат только prose-like content.
2. `reference_chunk` records содержат bibliography / citation / URL-dump content.
3. `diagram_chunk` records содержат mermaid / code-like content.
4. `table` records не регрессируют.
5. Section с одним heading и без prose body не создаёт prose `chunk`.
6. Section-обёртка над table не создаёт prose noise.
7. Reference-heavy tail не смешивается с main prose chunk.
8. Mermaid/code-like block не смешивается с prose chunk.
9. Long mixed section больше не даёт giant prose chunk уровня 4k+ chars.

### Data safety
10. Canonical `document` не теряет контент.
11. Reference/code-like content не drop'ается — только separate + label.
12. `source_node_ids` и `source_table_ids` остаются валидными.
13. `validate(doc, records)` проходит.

## Tests Required

В `tests/test_model.py`:
- model acceptance for `reference_chunk`
- model acceptance for `diagram_chunk`

В `tests/test_chunker.py`:
- no heading-only prose chunk
- separate reference chunk from prose
- separate diagram chunk from prose
- no prose noise for table-wrapper section
- long mixed section splits cleanly and keeps non-prose out of prose chunks

## Non-Goals

- Не менять parser extraction rules.
- Не менять canonical `document` schema кроме расширения `RecordType`.
- Не менять CLI или portability behavior.
- Не вводить новые table semantics.

## Verification

1. Run targeted tests for `tests/test_model.py` and `tests/test_chunker.py`.
2. Run full suite.
3. Re-parse representative DOCX and verify:
   - bibliography no longer inside prose chunks;
   - Mermaid/code-like content appears separately;
   - giant mixed prose chunk disappears;
   - tables still emit `table` records.
