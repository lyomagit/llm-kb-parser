"""Tests for structure-aware record builder."""
from __future__ import annotations

import pytest

from kbparser.model import Block, Document, Parse, Section, Source, Table, TableCell
from kbparser.parsers.base import ParseContext
from kbparser.parsers.docx import DOCXParser
from kbparser.parsers.excel import ExcelParser
from kbparser.parsers.pdf import PDFParser
from kbparser.records import build_records
from kbparser.validation import validate

from .fixtures_gen.build_docx import build_basic as build_docx
from .fixtures_gen.build_pdf import build_basic as build_pdf
from .fixtures_gen.build_xlsx import build_basic as build_xlsx

# ----- helpers -----

def _src() -> Source:
    return Source(
        path="/tmp/x.pdf", filename="x.pdf", format="pdf", mime_type="application/pdf",
        sha256="0" * 64, size_bytes=1, modified_at="2026-04-13T00:00:00+00:00",
    )


def _parse_obj() -> Parse:
    return Parse(
        parser="t", parser_version="0",
        started_at="2026-04-13T00:00:00+00:00",
        finished_at="2026-04-13T00:00:01+00:00",
    )


# ----- unit -----

def test_empty_doc_no_records():
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj())
    assert build_records(doc) == []


def test_section_with_heading_and_para():
    sec = Section(id="sec_a", title="Intro", level=1, path=["Intro"], block_ids=["blk_h", "blk_p"])
    heading = Block(id="blk_h", type="heading", section_id="sec_a", order=0, text="Intro")
    para = Block(id="blk_p", type="paragraph", section_id="sec_a", order=1, text="Some body.")
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj(), sections=[sec], blocks=[heading, para])
    records = build_records(doc)
    types = [r.type for r in records]
    assert "chunk" in types
    assert "section_summary_seed" in types
    chunk = next(r for r in records if r.type == "chunk")
    assert "Intro" in chunk.text and "Some body." in chunk.text
    assert "sec_a" in chunk.source_node_ids
    assert "blk_h" in chunk.source_node_ids
    assert "blk_p" in chunk.source_node_ids


def test_oversized_section_splits():
    long_text = "word " * 400
    blocks = [
        Block(id=f"blk_{i}", type="paragraph", section_id="sec_a", order=i, text=long_text)
        for i in range(5)
    ]
    sec = Section(
        id="sec_a", title="Big", level=1, path=["Big"],
        block_ids=[b.id for b in blocks],
    )
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj(), sections=[sec], blocks=blocks)
    records = build_records(doc, max_chars=1200)
    chunks = [r for r in records if r.type == "chunk"]
    assert len(chunks) >= 2
    assert all(r.metadata.get("segment_total") == len(chunks) for r in chunks)
    assert all(c.char_count <= 2000 for c in chunks)  # soft bound


def test_single_oversized_block_hard_splits():
    huge = "lorem ipsum " * 2000  # ~22k chars, one block
    blk = Block(id="blk_big", type="paragraph", section_id="sec_a", order=0, text=huge)
    sec = Section(
        id="sec_a", title="Giant", level=1, path=["Giant"],
        block_ids=["blk_big"],
    )
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj(), sections=[sec], blocks=[blk])
    records = build_records(doc, max_chars=1200)
    chunks = [r for r in records if r.type == "chunk"]
    assert len(chunks) >= 10  # 22k / 1.2k ≈ 18, allowing boundary slack
    # hard bound: no chunk should be more than ~2x budget
    assert all(c.char_count <= 2500 for c in chunks)
    # lineage preserved — each chunk references the original block id
    assert all("blk_big" in c.source_node_ids for c in chunks)


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

    records = build_records(doc)

    prose = [r for r in records if r.type == "chunk"]
    refs = [r for r in records if r.type == "reference_chunk"]

    assert len(prose) >= 2
    assert refs
    assert all((r.char_count or 0) <= 1600 for r in prose)
    assert all("https://example.com" not in (r.text or "") for r in prose)




def test_level2_section_has_no_summary_seed():
    top = Section(id="sec_a", title="Top", level=1, path=["Top"])
    sub = Section(id="sec_b", title="Sub", level=2, parent_id="sec_a", path=["Top", "Sub"])
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj(), sections=[top, sub])
    records = build_records(doc)
    seeds = [r for r in records if r.type == "section_summary_seed"]
    # top has no blocks → empty seed text → skipped; sub is L2 → skipped
    assert seeds == []


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


def test_reference_like_source_code_block_stays_reference_not_diagram():
    sec = Section(
        id="sec_a",
        title="Links",
        level=1,
        path=["Links"],
        block_ids=["blk_h", "blk_ref"],
    )
    blocks = [
        Block(id="blk_h", type="heading", section_id="sec_a", order=0, text="Links"),
        Block(
            id="blk_ref",
            type="paragraph",
            section_id="sec_a",
            order=1,
            text="https://example.com\nhttps://example.org",
            style={"name": "Source Code"},
        ),
    ]
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj(), sections=[sec], blocks=blocks)

    records = build_records(doc, max_chars=1200)

    refs = [r for r in records if r.type == "reference_chunk"]
    diagrams = [r for r in records if r.type == "diagram_chunk"]

    assert refs
    assert not diagrams
    assert any("example.com" in (r.text or "") for r in refs)




def test_table_record_present_with_lineage():
    sec = Section(id="sec_a", title="S", level=1, path=["S"])
    t = Table(
        id="tbl_1", section_id="sec_a", page=1, columns=["A", "B"],
        rows=[
            [TableCell(row=0, col=0, text="A"), TableCell(row=0, col=1, text="B")],
            [TableCell(row=1, col=0, text="1"), TableCell(row=1, col=1, text="2")],
        ],
    )
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj(), sections=[sec], tables=[t])
    records = build_records(doc)
    table_recs = [r for r in records if r.type == "table"]
    assert len(table_recs) == 1
    tr = table_recs[0]
    assert "tbl_1" in tr.source_table_ids
    assert "sec_a" in tr.source_node_ids
    assert "A | B" in (tr.text or "")
    assert "1 | 2" in (tr.text or "")


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


# ----- end-to-end on fixtures -----

@pytest.fixture(scope="module")
def docx_doc(tmp_path_factory):
    p = build_docx(tmp_path_factory.mktemp("d") / "x.docx")
    return DOCXParser().parse(ParseContext(path=p, profile="fidelity"))


@pytest.fixture(scope="module")
def xlsx_doc(tmp_path_factory):
    p = build_xlsx(tmp_path_factory.mktemp("x") / "x.xlsx")
    return ExcelParser().parse(ParseContext(path=p, profile="fidelity"))


@pytest.fixture(scope="module")
def pdf_doc(tmp_path_factory):
    p = build_pdf(tmp_path_factory.mktemp("p") / "x.pdf")
    return PDFParser().parse(ParseContext(path=p, profile="fidelity"))


def test_docx_records_validate(docx_doc):
    records = build_records(docx_doc)
    validate(docx_doc, records)
    types = {r.type for r in records}
    assert "chunk" in types
    assert "table" in types
    assert "section_summary_seed" in types


def test_xlsx_records_validate(xlsx_doc):
    records = build_records(xlsx_doc)
    validate(xlsx_doc, records)
    types = {r.type for r in records}
    assert "table" in types
    assert "sheet_region" in types
    # No page-based chunks for workbooks.
    assert "chunk" not in types


def test_pdf_records_validate(pdf_doc):
    records = build_records(pdf_doc)
    validate(pdf_doc, records)
    types = {r.type for r in records}
    assert "chunk" in types
    assert "table" in types
    chunk_sections = [r.section_title for r in records if r.type == "chunk"]
    assert "Results" in chunk_sections


def test_record_ids_deterministic(docx_doc):
    a = build_records(docx_doc)
    b = build_records(docx_doc)
    assert [r.id for r in a] == [r.id for r in b]


def test_lineage_all_refs_valid(docx_doc, pdf_doc, xlsx_doc):
    for d in (docx_doc, pdf_doc, xlsx_doc):
        records = build_records(d)
        validate(d, records)
        node_ids = {s.id for s in d.sections} | {b.id for b in d.blocks} | {t.id for t in d.tables} | {sh.id for sh in d.sheets}
        for r in records:
            for nid in r.source_node_ids:
                assert nid in node_ids, f"{r.id} refs {nid}"


def test_pdf_chunk_has_page_span(pdf_doc):
    records = build_records(pdf_doc)
    chunks = [r for r in records if r.type == "chunk"]
    assert chunks
    assert any(r.page_span is not None for r in chunks)


def test_docx_table_linked_via_last_chunk(docx_doc):
    records = build_records(docx_doc)
    chunks_with_table = [r for r in records if r.type == "chunk" and r.source_table_ids]
    # Our fixture's table lives under "Materials" — its chunk should reference it.
    assert chunks_with_table
    assert all(r.section_title in ("Materials", "Introduction", "Methods", "Conclusion")
               for r in chunks_with_table)


def test_large_table_records_repeat_headers_and_keep_every_row():
    table = Table(id="tbl_big", columns=["Key", "Value"], rows=[
        [TableCell(row=0, col=0, text="Key"), TableCell(row=0, col=1, text="Value")],
        *[[TableCell(row=i, col=0, text=f"item-{i:03d}"),
           TableCell(row=i, col=1, text="Data " * 8)] for i in range(1, 101)],
    ])
    doc = Document(id="doc_x", source=_src(), parse=_parse_obj(), tables=[table])
    records = [r for r in build_records(doc, max_chars=300) if r.type == "table"]
    assert len(records) > 1
    assert all(r.char_count <= 300 and r.text.startswith("Key | Value\n") for r in records)
    assert all(r.source_table_ids == [table.id] for r in records)
    assert len({r.id for r in records}) == len(records)
    assert [i for r in records for i in range(r.metadata["row_span"][0], r.metadata["row_span"][1] + 1)] == list(range(1, 101))
    for i in range(1, 101):
        assert sum(f"item-{i:03d}" in r.text for r in records) == 1
    assert len(doc.tables[0].rows) == 101
    validate(doc, records)
