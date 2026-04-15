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
