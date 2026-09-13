"""Golden tests for PDF parser against reportlab-generated fixture."""
from __future__ import annotations

from pathlib import Path

import pytest

from kbparser.parsers.base import ParseContext
from kbparser.parsers.pdf import PDFParser
from kbparser.records import build_records
from kbparser.validation import validate

from .fixtures_gen.build_pdf import build_basic


@pytest.fixture(scope="module")
def basic_pdf(tmp_path_factory) -> Path:
    return build_basic(tmp_path_factory.mktemp("pdf") / "basic.pdf")


def _parse(path: Path):
    return PDFParser().parse(ParseContext(path=path, profile="fidelity"))


def test_pages(basic_pdf: Path):
    d = _parse(basic_pdf)
    assert len(d.pages) == 2
    assert all(p.width > 0 and p.height > 0 for p in d.pages)


def test_metadata(basic_pdf: Path):
    d = _parse(basic_pdf)
    assert d.metadata.get("title") == "PDF Test Report"
    assert d.metadata.get("author") == "kbparser-fixture"


def test_header_footer_filtered(basic_pdf: Path):
    d = _parse(basic_pdf)
    texts = [(b.text or "") for b in d.blocks]
    joined = " | ".join(texts)
    assert "Confidential" not in joined
    assert "Page 1" not in joined
    assert "Page 2" not in joined
    assert any(w.code == "header_footer_filtered_heuristically" for w in d.warnings)


def test_heading_hierarchy(basic_pdf: Path):
    d = _parse(basic_pdf)
    titles = [s.title for s in d.sections]
    levels = [s.level for s in d.sections]
    assert titles == ["PDF Test Report", "Overview", "Methods", "Results"]
    # 24pt title is L1, 18pt H1s become L2 relative to it.
    assert levels == [1, 2, 2, 2]
    root = d.sections[0]
    for s in d.sections[1:]:
        assert s.parent_id == root.id


def test_block_types(basic_pdf: Path):
    d = _parse(basic_pdf)
    counts = {}
    for b in d.blocks:
        counts[b.type] = counts.get(b.type, 0) + 1
    assert counts["heading"] == 4
    assert counts["paragraph"] >= 4
    assert counts["table_ref"] == 1


def test_table_shape(basic_pdf: Path):
    d = _parse(basic_pdf)
    assert len(d.tables) == 1
    t = d.tables[0]
    assert t.page == 2
    assert t.columns == ["Metric", "Before", "After"]
    assert len(t.rows) == 3
    assert [c.text for c in t.rows[1]] == ["Precision", "0.72", "0.91"]
    assert [c.text for c in t.rows[2]] == ["Recall", "0.65", "0.88"]


def test_table_attached_to_results_section(basic_pdf: Path):
    d = _parse(basic_pdf)
    results = next(s for s in d.sections if s.title == "Results")
    assert d.tables[0].section_id == results.id


def test_section_page_span(basic_pdf: Path):
    d = _parse(basic_pdf)
    by_title = {s.title: s for s in d.sections}
    assert by_title["Overview"].page_start == 1
    assert by_title["Methods"].page_start == 1
    assert by_title["Results"].page_start == 2


def test_blocks_have_bbox(basic_pdf: Path):
    d = _parse(basic_pdf)
    non_refs = [b for b in d.blocks if b.type != "table_ref"]
    assert all(b.bbox and len(b.bbox) == 4 for b in non_refs)


def test_validation_passes(basic_pdf: Path):
    validate(_parse(basic_pdf))


def test_deterministic_ids(basic_pdf: Path):
    a = _parse(basic_pdf)
    b = _parse(basic_pdf)
    assert a.id == b.id
    assert [s.id for s in a.sections] == [s.id for s in b.sections]
    assert [blk.id for blk in a.blocks] == [blk.id for blk in b.blocks]
    assert [t.id for t in a.tables] == [t.id for t in b.tables]


def test_root_section_fallback_when_no_headings(monkeypatch, basic_pdf: Path):
    from kbparser.parsers import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "_assign_heading_levels", lambda pages, body_size: None)
    d = _parse(basic_pdf)

    assert len(d.sections) == 1
    assert d.sections[0].page_start == 1
    assert d.sections[0].page_end == 2
    assert all(b.section_id == d.sections[0].id for b in d.blocks if b.type != "heading")

    records = build_records(d)
    assert len(records) > 0
    assert any(r.type == "chunk" for r in records)


def test_pdf_preamble_is_preserved_before_first_heading(tmp_path: Path):
    import fitz

    path = tmp_path / "preamble.pdf"
    with fitz.open() as source:
        page = source.new_page()
        page.insert_text((50, 100), "Important introductory conditions.", fontsize=11)
        page.insert_text((50, 150), "Details", fontsize=20)
        page.insert_text((50, 190), "Detailed explanation. " * 3, fontsize=11)
        source.save(path)
    doc = _parse(path)
    assert all(block.section_id for block in doc.blocks)
    assert any("introductory conditions" in (r.text or "") for r in build_records(doc))


def test_pdf_column_order_between_full_width_blocks(tmp_path: Path):
    import fitz

    path = tmp_path / "columns.pdf"
    with fitz.open() as source:
        page = source.new_page(width=612, height=792)
        page.insert_text((45, 70), "Spanning heading across both columns of this page", fontsize=18)
        for x, y, label in [(45, 110, "LEFT_FIRST"), (330, 110, "RIGHT_FIRST"),
                            (45, 245, "LEFT_SECOND"), (330, 245, "RIGHT_SECOND")]:
            page.insert_textbox(fitz.Rect(x, y, x + 235, y + 100),
                                label + " This paragraph belongs to a continuous column. " * 3, fontsize=11)
        page.insert_text((45, 410), "Final paragraph across both columns. " * 2, fontsize=11)
        source.save(path)
    text = "\n".join(b.text or "" for b in _parse(path).blocks)
    markers = ["Spanning heading", "LEFT_FIRST", "LEFT_SECOND", "RIGHT_FIRST", "RIGHT_SECOND", "Final paragraph"]
    assert [text.index(marker) for marker in markers] == sorted(text.index(marker) for marker in markers)


def test_pdf_cancellation_is_checked_between_pages(basic_pdf: Path):
    from kbparser.dispatcher import dispatch
    checks = 0
    def cancelled():
        nonlocal checks
        checks += 1
        return checks > 1
    with pytest.raises(Exception, match="Parsing cancelled"):
        dispatch(basic_pdf, cancelled=cancelled)


def test_filled_slide_backgrounds_are_not_tables(tmp_path: Path):
    import fitz

    from kbparser.export import to_markdown, to_output

    path = tmp_path / "slide.pdf"
    sentence = "A complete sentence must survive decorative rectangles and every word beyond their boundary."
    with fitz.open() as source:
        page = source.new_page(width=960, height=540)
        for box in [(0, 0, 490, 540), (0, 0, 140, 540), (0, 0, 490, 75)]:
            page.draw_rect(fitz.Rect(box), color=None, fill=(0.9, 0.95, 1))
        page.insert_text((35, 45), "EDUCATION NETWORK", fontsize=24)
        page.insert_text((35, 130), sentence, fontsize=13)
        source.save(path)
    doc = _parse(path)
    text = to_markdown(to_output(doc, build_records(doc)))
    assert doc.tables == []
    assert sentence in text
    assert "<br>" not in text


def test_stroked_rectangle_cells_remain_a_real_table(tmp_path: Path):
    import fitz

    path = tmp_path / "rectangle-table.pdf"
    with fitz.open() as source:
        page = source.new_page()
        for row, values in enumerate([["Name", "Value"], ["Alpha", "42"], ["Beta", "73"]]):
            for col, text in enumerate(values):
                box = fitz.Rect(50 + col * 150, 100 + row * 30, 200 + col * 150, 130 + row * 30)
                page.draw_rect(box, color=(0, 0, 0), fill=(0.95, 0.95, 0.95))
                page.insert_text((box.x0 + 8, box.y0 + 20), text, fontsize=11)
        source.save(path)
    doc = _parse(path)
    assert len(doc.tables) == 1
    assert [cell.text for cell in doc.tables[0].rows[-1]] == ["Beta", "73"]


def test_lossy_table_candidate_falls_back_to_original_text(monkeypatch, basic_pdf: Path):
    import pdfplumber.table

    monkeypatch.setattr(pdfplumber.table.Table, "extract", lambda *args, **kwargs: [
        ["Metric", "Before", "After"], ["Precision", "0.72", None], ["Recall", "0.65", None],
    ])
    doc = _parse(basic_pdf)
    assert not doc.tables
    text = " ".join(b.text or "" for b in doc.blocks)
    assert "0.91" in text and "0.88" in text
    assert any(w.code == "table_structure_uncertain" for w in doc.warnings)


def test_table_removal_preserves_spans_outside_its_bounds():
    from kbparser.parsers.pdf import _PdfBlock, _PdfPage, _Span, _strip_spans_inside_tables

    caption = _Span("Caption outside table", 11, "Regular", (50, 90, 250, 99))
    cells = _Span("Table data", 11, "Regular", (50, 110, 250, 150))
    block = _PdfBlock("Caption outside table Table data", (50, 90, 250, 150), spans=[caption, cells])
    page = _PdfPage(1, 600, 800, blocks=[block])
    _strip_spans_inside_tables([page], {1: [{"bbox": (40, 105, 300, 160), "rows": []}]})
    assert [b.text for b in page.blocks] == ["Caption outside table"]


def test_wide_pdf_keeps_page_sections_and_numeric_cards(tmp_path: Path):
    import fitz

    from kbparser.export import to_markdown, to_output

    path = tmp_path / "presentation.pdf"
    with fitz.open() as source:
        for title, number in [("First topic", "178"), ("Second topic", "257")]:
            page = source.new_page(width=960, height=540)
            page.insert_text((40, 50), title, fontsize=28)
            page.insert_text((40, 125), "Large callout", fontsize=36)
            page.insert_text((40, 170), number, fontsize=48)
            page.insert_text((160, 160), "educational organizations", fontsize=16)
        source.save(path)
    doc = _parse(path)
    records = build_records(doc)
    assert [s.title for s in doc.sections] == ["First topic", "Second topic"]
    assert [s.page_start for s in doc.sections] == [1, 2]
    text = to_markdown(to_output(doc, records))
    assert "## Страница 1 — First topic" in text
    assert "## Страница 2 — Second topic" in text
    assert "178" in text and "257" in text
    assert all(any(number in (r.text or "") for r in records if r.type == "chunk") for number in ["178", "257"])


def test_slide_columns_keep_their_own_labels(tmp_path: Path):
    import fitz

    path = tmp_path / "categories.pdf"
    with fitz.open() as source:
        for _ in range(2):
            page = source.new_page(width=960, height=540)
            page.insert_text((40, 50), "Categories", fontsize=28)
            for y, label in [(120, "GROUP"), (165, "ONE"), (210, "TWO")]:
                for x, side in [(60, "LEFT"), (540, "RIGHT")]:
                    page.insert_text((x, y), f"{side}_{label} belongs to this category of items.", fontsize=14)
        source.save(path)
    doc = _parse(path)
    text = "\n".join(b.text or "" for b in doc.blocks if b.page == 1)
    labels = ["LEFT_GROUP", "LEFT_ONE", "LEFT_TWO", "RIGHT_GROUP", "RIGHT_ONE", "RIGHT_TWO"]
    assert [text.index(label) for label in labels] == sorted(text.index(label) for label in labels)


def test_columns_tolerate_minor_text_overhang_and_a_single_sidebar():
    from kbparser.parsers.pdf import _reading_order

    overhang = [
        ((60, 110, 575, 130), "block", "left heading"),
        ((60, 150, 530, 170), "block", "left text"),
        ((540, 105, 880, 125), "block", "right heading"),
        ((540, 145, 880, 165), "block", "right text"),
    ]
    assert [v[2] for v in _reading_order(overhang, 960)] == ["left heading", "left text", "right heading", "right text"]
    sidebar = [
        ((60, 110, 400, 130), "block", "paragraph start"),
        ((60, 150, 400, 170), "block", "paragraph end"),
        ((650, 130, 900, 160), "block", "sidebar"),
    ]
    assert [v[2] for v in _reading_order(sidebar, 960)] == ["paragraph start", "paragraph end", "sidebar"]
