"""Tabular text with original column positions and source row indices."""
from __future__ import annotations

from ..model import Table, TableCell


def cell_text(cell: TableCell) -> str:
    for value in (cell.display_value, cell.text, cell.raw_value):
        if value is not None:
            return str(value)
    return ""


def table_content(table: Table) -> tuple[list[str], list[tuple[int, list[str]]]]:
    width = max([len(table.columns), *(c.col + c.col_span for row in table.rows for c in row)])
    rows: list[tuple[int, list[str]]] = []
    for index, row in enumerate(table.rows):
        values = [""] * width
        for cell in row:
            values[cell.col] = cell_text(cell)
        rows.append((index, values))
    headers = list(table.columns) + [""] * (width - len(table.columns))
    if rows and any(table.columns) and [cell_text(c) for c in table.rows[0]] == table.columns:
        _, headers = rows.pop(0)
    return headers, rows
