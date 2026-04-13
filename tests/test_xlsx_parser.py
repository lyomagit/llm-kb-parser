"""Golden tests for XLSX parser."""
from __future__ import annotations

from pathlib import Path

import pytest

from kbparser.parsers.base import ParseContext
from kbparser.parsers.excel import ExcelParser
from kbparser.validation import validate

from .fixtures_gen.build_xlsx import build_basic


@pytest.fixture(scope="module")
def basic_xlsx(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("xlsx") / "basic.xlsx"
    return build_basic(out)


def _parse(path: Path):
    return ExcelParser().parse(ParseContext(path=path, profile="fidelity"))


def test_workbook_sheets(basic_xlsx: Path):
    d = _parse(basic_xlsx)
    assert [s.sheet_name for s in d.sheets] == ["Sales", "Summary", "Archive"]
    assert [s.visibility for s in d.sheets] == ["visible", "visible", "hidden"]
    assert [s.index for s in d.sheets] == [0, 1, 2]


def test_used_ranges(basic_xlsx: Path):
    d = _parse(basic_xlsx)
    ranges = {s.sheet_name: s.used_range for s in d.sheets}
    assert ranges["Sales"] == "A1:D7"
    assert ranges["Summary"] == "A1:B3"


def test_regions(basic_xlsx: Path):
    d = _parse(basic_xlsx)
    sales = next(s for s in d.sheets if s.sheet_name == "Sales")
    kinds = [(r.kind, r.range) for r in sales.regions]
    assert kinds == [("data_table", "A1:D5"), ("note", "A7:A7")]
    note = sales.regions[1]
    assert note.text == "Note: preliminary figures."

    summary = next(s for s in d.sheets if s.sheet_name == "Summary")
    assert [(r.kind, r.range) for r in summary.regions] == [("data_table", "A1:B3")]


def test_tables_count_and_link(basic_xlsx: Path):
    d = _parse(basic_xlsx)
    assert len(d.tables) == 2
    sales_sheet = next(s for s in d.sheets if s.sheet_name == "Sales")
    assert len(sales_sheet.table_ids) == 1
    sales_table = next(t for t in d.tables if t.id == sales_sheet.table_ids[0])
    assert sales_table.sheet == "Sales"


def test_merged_title_col_span(basic_xlsx: Path):
    d = _parse(basic_xlsx)
    sales = next(t for t in d.tables if t.sheet == "Sales")
    # Row 0 is the merged title: single cell spanning 4 columns.
    assert len(sales.rows[0]) == 1
    assert sales.rows[0][0].col_span == 4
    assert sales.rows[0][0].text == "Q1 Sales Report"


def test_formula_captured(basic_xlsx: Path):
    d = _parse(basic_xlsx)
    sales = next(t for t in d.tables if t.sheet == "Sales")
    # Rows 2..4 have formulas in last column (D3..D5).
    for row_i in (2, 3, 4):
        last = sales.rows[row_i][-1]
        assert last.formula is not None and last.formula.startswith("=")
    codes = {w.code for w in d.warnings}
    assert "formula_not_evaluated" in codes


def test_summary_table_headers(basic_xlsx: Path):
    d = _parse(basic_xlsx)
    summary = next(t for t in d.tables if t.sheet == "Summary")
    assert summary.columns == ["Metric", "Value"]
    assert summary.rows[1][0].text == "Total Units"
    assert summary.rows[1][1].text == "22"


def test_validation_passes(basic_xlsx: Path):
    validate(_parse(basic_xlsx))


def test_deterministic_ids(basic_xlsx: Path):
    a = _parse(basic_xlsx)
    b = _parse(basic_xlsx)
    assert a.id == b.id
    assert [s.id for s in a.sheets] == [s.id for s in b.sheets]
    assert [t.id for t in a.tables] == [t.id for t in b.tables]
