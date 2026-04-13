# kbparser RAG Output Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать derived `records` из kbparser чистыми для KB/RAG ingest через разделение prose/reference/diagram content без потери данных из canonical `document`.

**Architecture:** Меняется только records-layer: canonical `document` остаётся faithful, а `kbparser/records/chunker.py` начинает классифицировать body blocks и выпускать разные record types. `chunk` остаётся prose-only, bibliography/URL dumps уходят в `reference_chunk`, Mermaid/code-like content уходит в `diagram_chunk`, а `table` records продолжают жить отдельно без wrapper-noise.

**Tech Stack:** Python 3.11+, pydantic v2, pytest.

---

## File Map

- Modify: `kbparser/model.py` — расширить `RecordType` для новых derived record classes.
- Modify: `kbparser/records/chunker.py` — добавить block classification, smaller prose chunk budget, separate builders for prose/reference/diagram records.
- Modify: `tests/test_model.py` — model acceptance tests for new record types.
- Modify: `tests/test_chunker.py` — regression tests for no heading-only noise, separate reference/diagram records, table-wrapper behavior, long mixed section splitting.

### Task 1: Extend record model for labeled retrieval classes

**Files:**
- Modify: `kbparser/model.py:21`
- Test: `tests/test_model.py`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_model.py`:

```python
@pytest.mark.parametrize(
    "record_type",
    ["reference_chunk", "diagram_chunk"],
)
def test_record_model_accepts_new_chunk_types(record_type: str):
    from kbparser.model import Record

    r = Record(
        id="rec_1",
        type=record_type,
        document_id="doc_x",
        text="sample",
        source_node_ids=["sec_1"],
    )
    assert r.type == record_type
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest tests/test_model.py::test_record_model_accepts_new_chunk_types -q`
Expected: FAIL with pydantic validation error for unsupported `RecordType`

- [ ] **Step 3: Write minimal implementation**

Update `kbparser/model.py`:

```python
RecordType = Literal[
    "chunk",
    "reference_chunk",
    "diagram_chunk",
    "table",
    "section_summary_seed",
    "sheet_region",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest tests/test_model.py::test_record_model_accepts_new_chunk_types -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kbparser/model.py tests/test_model.py
git commit -m "feat: add labeled rag record types"
```

### Task 2: Prevent heading-only prose noise and table-wrapper prose noise

**Files:**
- Modify: `kbparser/records/chunker.py:60-131`
- Test: `tests/test_chunker.py`

- [ ] **Step 1: Write the failing tests**

Add these tests to `tests/test_chunker.py`:

```python
def test_heading_only_section_emits_no_prose_chunk():
    sec = Section(id="sec_a", title="Only heading", level=1, path=["Only heading"], block_ids=["blk_h"])
    heading = Block(id="blk_h", type="heading", section_id="sec_a", order=0, text="Only heading")
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj(), sections=[sec], blocks=[heading])

    records = build_records(doc, max_chars=1200)

    assert not any(r.type == "chunk" for r in records)


def test_table_wrapper_section_emits_no_prose_chunk_but_keeps_table_record():
    sec = Section(id="sec_a", title="Table Section", level=1, path=["Table Section"], block_ids=["blk_h", "blk_tref"])
    heading = Block(id="blk_h", type="heading", section_id="sec_a", order=0, text="Table Section")
    table_ref = Block(id="blk_tref", type="table_ref", section_id="sec_a", order=1, text="[table tbl_1]")
    table = Table(
        id="tbl_1",
        section_id="sec_a",
        columns=["A", "B"],
        rows=[
            [TableCell(row=0, col=0, text="A"), TableCell(row=0, col=1, text="B")],
            [TableCell(row=1, col=0, text="1"), TableCell(row=1, col=1, text="2")],
        ],
    )
    doc = Document(
        id="doc_x",
        source=_src(),
        parse=_parse_obj(),
        sections=[sec],
        blocks=[heading, table_ref],
        tables=[table],
    )

    records = build_records(doc, max_chars=1200)

    assert not any(r.type == "chunk" for r in records)
    assert any(r.type == "table" for r in records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest tests/test_chunker.py::test_heading_only_section_emits_no_prose_chunk tests/test_chunker.py::test_table_wrapper_section_emits_no_prose_chunk_but_keeps_table_record -q`
Expected: FAIL because current chunker emits heading-only prose chunk

- [ ] **Step 3: Write minimal implementation**

Update `_chunks_for_section()` in `kbparser/records/chunker.py` so prose chunks require actual prose-like body blocks.

Core rule to implement:

```python
    heading_block = next((b for b in blocks if b.type == "heading"), None)
    body_blocks = [b for b in blocks if b.type not in ("heading", "table_ref")]
    if not body_blocks:
        return []
```

Then ensure the prose path only runs when at least one prose-like body block exists. Do not attach heading-only text to an otherwise empty chunk.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest tests/test_chunker.py::test_heading_only_section_emits_no_prose_chunk tests/test_chunker.py::test_table_wrapper_section_emits_no_prose_chunk_but_keeps_table_record -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kbparser/records/chunker.py tests/test_chunker.py
git commit -m "fix: drop prose noise from empty sections"
```

### Task 3: Separate reference chunks from prose chunks

**Files:**
- Modify: `kbparser/records/chunker.py:40-176`
- Test: `tests/test_chunker.py`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_chunker.py`:

```python
def test_reference_blocks_emit_reference_chunk_not_prose_chunk():
    sec = Section(
        id="sec_a",
        title="References",
        level=1,
        path=["References"],
        block_ids=["blk_h", "blk_p", "blk_r1", "blk_r2"],
    )
    blocks = [
        Block(id="blk_h", type="heading", section_id="sec_a", order=0, text="References"),
        Block(id="blk_p", type="paragraph", section_id="sec_a", order=1, text="Short explanatory intro."),
        Block(id="blk_r1", type="paragraph", section_id="sec_a", order=2, text="[1] https://example.com/a"),
        Block(id="blk_r2", type="paragraph", section_id="sec_a", order=3, text="[2] https://example.com/b"),
    ]
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj(), sections=[sec], blocks=blocks)

    records = build_records(doc, max_chars=1200)

    prose = [r for r in records if r.type == "chunk"]
    refs = [r for r in records if r.type == "reference_chunk"]

    assert prose
    assert refs
    assert all("https://example.com" not in (r.text or "") for r in prose)
    assert any("https://example.com/a" in (r.text or "") for r in refs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest tests/test_chunker.py::test_reference_blocks_emit_reference_chunk_not_prose_chunk -q`
Expected: FAIL because current chunker places references inside prose `chunk`

- [ ] **Step 3: Write minimal implementation**

In `kbparser/records/chunker.py`:
1. Add a helper like `_is_reference_like(block: Block) -> bool`
2. Detect URL/citation-style blocks
3. Split section body into prose-like and reference-like groups
4. Emit `Record(type="reference_chunk", ...)` for reference groups
5. Keep prose path free of reference blocks

A minimal sketch for the helper:

```python
import re

_REFERENCE_RE = re.compile(r"^\[\d+\]")
_URL_RE = re.compile(r"https?://")


def _is_reference_like(block: Block) -> bool:
    text = (block.text or "").strip()
    if not text:
        return False
    if _REFERENCE_RE.match(text):
        return True
    if text.count("http://") + text.count("https://") >= 1 and len(text) < 300:
        return True
    return False
```

Then build `reference_chunk` records using the same lineage discipline as prose chunks.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest tests/test_chunker.py::test_reference_blocks_emit_reference_chunk_not_prose_chunk -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kbparser/records/chunker.py tests/test_chunker.py
git commit -m "feat: separate reference chunks from prose"
```

### Task 4: Separate diagram/code-like chunks from prose chunks

**Files:**
- Modify: `kbparser/records/chunker.py:40-176`
- Test: `tests/test_chunker.py`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_chunker.py`:

```python
def test_mermaid_like_block_emits_diagram_chunk_not_prose_chunk():
    sec = Section(
        id="sec_a",
        title="Diagram",
        level=1,
        path=["Diagram"],
        block_ids=["blk_h", "blk_p", "blk_d"],
    )
    blocks = [
        Block(id="blk_h", type="heading", section_id="sec_a", order=0, text="Diagram"),
        Block(id="blk_p", type="paragraph", section_id="sec_a", order=1, text="This section explains the org chart."),
        Block(
            id="blk_d",
            type="paragraph",
            section_id="sec_a",
            order=2,
            text="flowchart TB\nA[CEO] --> B[Ops]",
            style={"name": "Source Code"},
        ),
    ]
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj(), sections=[sec], blocks=blocks)

    records = build_records(doc, max_chars=1200)

    prose = [r for r in records if r.type == "chunk"]
    diagrams = [r for r in records if r.type == "diagram_chunk"]

    assert prose
    assert diagrams
    assert all("flowchart TB" not in (r.text or "") for r in prose)
    assert any("flowchart TB" in (r.text or "") for r in diagrams)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest tests/test_chunker.py::test_mermaid_like_block_emits_diagram_chunk_not_prose_chunk -q`
Expected: FAIL because current chunker puts mermaid text into prose `chunk`

- [ ] **Step 3: Write minimal implementation**

In `kbparser/records/chunker.py`:
1. Add helper `_is_diagram_like(block: Block) -> bool`
2. Treat `style.name == "Source Code"` and text prefixes like `flowchart`, `graph`, `sequenceDiagram`, `pie title` as diagram/code-like
3. Emit `Record(type="diagram_chunk", ...)`
4. Keep these blocks out of prose chunks

Minimal sketch:

```python
_DIAGRAM_PREFIXES = ("flowchart", "graph", "sequenceDiagram", "pie title")


def _is_diagram_like(block: Block) -> bool:
    text = (block.text or "").strip()
    style_name = ((block.style or {}).get("name") or "").strip()
    if style_name == "Source Code":
        return True
    return text.startswith(_DIAGRAM_PREFIXES)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest tests/test_chunker.py::test_mermaid_like_block_emits_diagram_chunk_not_prose_chunk -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kbparser/records/chunker.py tests/test_chunker.py
git commit -m "feat: separate diagram chunks from prose"
```

### Task 5: Tighten prose chunk sizing for long mixed sections

**Files:**
- Modify: `kbparser/records/chunker.py:19,134-176`
- Test: `tests/test_chunker.py`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_chunker.py`:

```python
def test_long_mixed_section_splits_prose_cleanly_and_keeps_references_separate():
    long_para = "Paragraph body. " * 120
    sec = Section(
        id="sec_a",
        title="Big mixed",
        level=1,
        path=["Big mixed"],
        block_ids=["blk_h", "blk_p1", "blk_p2", "blk_r1", "blk_r2"],
    )
    blocks = [
        Block(id="blk_h", type="heading", section_id="sec_a", order=0, text="Big mixed"),
        Block(id="blk_p1", type="paragraph", section_id="sec_a", order=1, text=long_para),
        Block(id="blk_p2", type="paragraph", section_id="sec_a", order=2, text=long_para),
        Block(id="blk_r1", type="paragraph", section_id="sec_a", order=3, text="[1] https://example.com/a"),
        Block(id="blk_r2", type="paragraph", section_id="sec_a", order=4, text="[2] https://example.com/b"),
    ]
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj(), sections=[sec], blocks=blocks)

    records = build_records(doc, max_chars=1200)

    prose = [r for r in records if r.type == "chunk"]
    refs = [r for r in records if r.type == "reference_chunk"]

    assert len(prose) >= 2
    assert refs
    assert all((r.char_count or 0) <= 1600 for r in prose)
    assert all("https://example.com" not in (r.text or "") for r in prose)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest tests/test_chunker.py::test_long_mixed_section_splits_prose_cleanly_and_keeps_references_separate -q`
Expected: FAIL because prose/reference separation and current chunk budget are too loose

- [ ] **Step 3: Write minimal implementation**

In `kbparser/records/chunker.py`:
- lower `DEFAULT_MAX_CHARS` from `6000` to `1200`
- keep `_virtual_split_block()` for fallback hard split
- continue grouping prose by structure, but ensure reference/diagram blocks are excluded before prose split

```python
DEFAULT_MAX_CHARS = 1200
```

Do not change canonical `document`. Do not change table record logic.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest tests/test_chunker.py::test_long_mixed_section_splits_prose_cleanly_and_keeps_references_separate -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kbparser/records/chunker.py tests/test_chunker.py
git commit -m "fix: tighten prose chunk sizing for rag"
```

### Task 6: Run regression suite and real-doc verification

**Files:**
- Modify: none
- Test: `tests/test_model.py`
- Test: `tests/test_chunker.py`

- [ ] **Step 1: Run targeted regression suite**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest tests/test_model.py tests/test_chunker.py -q`
Expected: PASS

- [ ] **Step 2: Run full suite**

Run: `cd "/Users/username/Desktop/llm-kb-parser" && ./venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 3: Re-parse representative DOCX and inspect output**

Run:

```bash
cd "/Users/username/Desktop/llm-kb-parser"
./venv/bin/python -m kbparser.cli parse "/Users/username/Downloads/Deep Research Backing Conversation for session None.docx" --overwrite
python3 - <<'PY'
import json
p = '/Users/username/Downloads/kb-parse-out/doc_6a16aa9aba72.json'
with open(p, 'r', encoding='utf-8') as f:
    data = json.load(f)
print(sorted({r['type'] for r in data['records']}))
for r in data['records']:
    if r['type'] == 'chunk' and (r.get('char_count') or 0) > 2000:
        print('oversized_chunk', r['section_title'], r['char_count'])
PY
```

Expected:
- `records` include `chunk`, `reference_chunk`, `diagram_chunk`, `table`
- no giant prose chunk for bibliography-heavy tail section
- bibliography and Mermaid/code-like content appear separately

- [ ] **Step 4: Commit verification batch**

```bash
git add kbparser/model.py kbparser/records/chunker.py tests/test_model.py tests/test_chunker.py
git commit -m "test: verify rag output quality cleanup"
```
