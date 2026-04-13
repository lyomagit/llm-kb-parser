"""Golden tests for XLS (legacy) parser."""
from __future__ import annotations

from pathlib import Path

import pytest
import xlwt

from kbparser.parsers.base import ParseContext
from kbparser.parsers.excel import ExcelParser, _SimpleCell, _build_table
from kbparser.records import build_records
from kbparser.validation import validate

from .fixtures_gen.build_xls import build_basic


@pytest.fixture(scope="module")
def basic_xls(tmp_path_factory) -> Path:
    return build_basic(tmp_path_factory.mktemp("xls") / "basic.xls")


def _parse(path: Path):
    return ExcelParser().parse(ParseContext(path=path, profile="fidelity"))


def test_source_format(basic_xls: Path):
    d = _parse(basic_xls)
    assert d.source.format == "xls"


def test_formula_cell_uses_cached_display_value():
    grid_f = {
        (1, 1): _SimpleCell(row=1, column=1, value="=A1+1"),
    }
    grid_c = {
        (1, 1): _SimpleCell(row=1, column=1, value=2),
    }
    table, had_formula = _build_table(
        "tid",
        "sid",
        "Sheet1",
        None,
        None,
        grid_f,
        grid_c,
        {},
        1,
        1,
        1,
        1,
    )
    assert had_formula is True
    cell = table.rows[0][0]
    assert cell.formula == "=A1+1"
    assert cell.raw_value == "=A1+1"
    assert cell.display_value == "2"
    assert cell.text == "2"


def test_formula_cell_falls_back_to_formula_text_when_display_value_missing():
    grid_f = {
        (1, 1): _SimpleCell(row=1, column=1, value="=A1+1"),
    }
    grid_c = {
        (1, 1): _SimpleCell(row=1, column=1, value=None),
    }
    table, had_formula = _build_table(
        "tid",
        "sid",
        "Sheet1",
        None,
        None,
        grid_f,
        grid_c,
        {},
        1,
        1,
        1,
        1,
    )
    assert had_formula is True
    cell = table.rows[0][0]
    assert cell.formula == "=A1+1"
    assert cell.raw_value == "=A1+1"
    assert cell.display_value is None
    assert cell.text == "=A1+1"


def test_formula_cell_preserves_empty_display_value():
    grid_f = {
        (1, 1): _SimpleCell(row=1, column=1, value="=A1+1"),
    }
    grid_c = {
        (1, 1): _SimpleCell(row=1, column=1, value=""),
    }
    table, had_formula = _build_table(
        "tid",
        "sid",
        "Sheet1",
        None,
        None,
        grid_f,
        grid_c,
        {},
        1,
        1,
        1,
        1,
    )
    assert had_formula is True
    cell = table.rows[0][0]
    assert cell.formula == "=A1+1"
    assert cell.raw_value == "=A1+1"
    assert cell.display_value == ""
    assert cell.text == ""


def test_sheets_and_visibility(basic_xls: Path):
    d = _parse(basic_xls)
    assert [s.sheet_name for s in d.sheets] == ["Sales", "Summary", "Archive", "Types"]
    assert [s.visibility for s in d.sheets] == ["visible", "visible", "hidden", "visible"]


def test_regions(basic_xls: Path):
    d = _parse(basic_xls)
    sales = next(s for s in d.sheets if s.sheet_name == "Sales")
    assert [(r.kind, r.range) for r in sales.regions] == [
        ("data_table", "A1:D5"),
        ("note", "A7:A7"),
    ]
    note = sales.regions[1]
    assert note.text == "Note: preliminary figures."


def test_merged_title(basic_xls: Path):
    d = _parse(basic_xls)
    sales = next(t for t in d.tables if t.sheet == "Sales")
    assert len(sales.rows[0]) == 1
    assert sales.rows[0][0].col_span == 4
    assert sales.rows[0][0].text == "Q1 Sales Report"


def test_summary_table(basic_xls: Path):
    d = _parse(basic_xls)
    summary = next(t for t in d.tables if t.sheet == "Summary")
    assert summary.columns == ["Metric", "Value"]
    assert summary.rows[2][0].text == "Total Revenue"
    assert summary.rows[2][1].text == "30.6"


def test_validation_and_records(basic_xls: Path):
    d = _parse(basic_xls)
    records = build_records(d)
    validate(d, records)
    kinds = {r.type for r in records}
    assert "table" in kinds
    assert "sheet_region" in kinds


def test_date_bool_cells(basic_xls: Path):
    d = _parse(basic_xls)
    types_sheet = next(s for s in d.sheets if s.sheet_name == "Types")
    assert types_sheet.table_ids
    tbl = next(t for t in d.tables if t.id == types_sheet.table_ids[0])
    # Row 1 carries the date, bool, and int.
    row1 = tbl.rows[1]
    # Date should be ISO-formatted.
    assert row1[0].text is not None and row1[0].text.startswith("2026-04-13")
    # Bool should be textualised.
    assert row1[1].text in ("True", "1")
    assert row1[2].text == "42"


def test_deterministic(basic_xls: Path):
    a = _parse(basic_xls)
    b = _parse(basic_xls)
    assert a.id == b.id
    assert [s.id for s in a.sheets] == [s.id for s in b.sheets]
    assert [t.id for t in a.tables] == [t.id for t in b.tables]
