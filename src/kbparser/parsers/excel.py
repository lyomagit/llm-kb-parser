"""Excel (xlsx/xls) parser.

Phase 3: real XLSX support via openpyxl. XLS still stubbed (phase 5).

Strategy:
- Load workbook twice (formula view + cached-values view) to capture both.
- Per sheet: detect logical regions via flood-fill over non-empty cells
  (merged rectangles count as occupied). Rectangular regions >= 2x2 become
  data tables; others become note regions.
- TableCell carries raw_value, display_value, formula, row_span/col_span.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import struct

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from ..ids import region_id, sheet_id, table_id
from ..model import Document, Sheet, SheetRegion, Table, TableCell, Warning
from ..versioning import PACKAGE_VERSION
from .base import ParseContext, build_source_and_parse, finalize_parse


class ExcelParser:
    name = "excel"
    version = PACKAGE_VERSION
    formats = ("xlsx", "xls")

    def parse(self, ctx: ParseContext) -> Document:
        fmt = ctx.path.suffix.lower().lstrip(".")
        if fmt == "xls":
            return _parse_xls(ctx, self.name, self.version)
        return _parse_xlsx(ctx, self.name, self.version)


@dataclass
class _SheetInput:
    name: str
    index: int
    visibility: str
    used_range: str | None
    grid_f: dict[tuple[int, int], Any]  # formula view
    grid_c: dict[tuple[int, int], Any]  # cached values view
    merges: dict[tuple[int, int], "_MergeInfo"]


def _parse_xlsx(ctx: ParseContext, parser_name: str, parser_version: str) -> Document:
    from .base import _iso_now  # type: ignore

    started = _iso_now()
    src, parse, did = build_source_and_parse(
        ctx, "xlsx", parser_name, parser_version, started_at=started, confidence=0.9,
    )

    wb_f = load_workbook(str(ctx.path), data_only=False, read_only=False)
    wb_c = load_workbook(str(ctx.path), data_only=True, read_only=False)

    metadata = _workbook_metadata(wb_f)
    sheet_inputs: list[_SheetInput] = []
    for idx, name in enumerate(wb_f.sheetnames):
        ws_f = wb_f[name]
        ws_c = wb_c[name]
        sheet_inputs.append(_SheetInput(
            name=name, index=idx,
            visibility=_visibility(ws_f),
            used_range=_used_range(ws_f),
            grid_f=_sheet_grid(ws_f),
            grid_c=_sheet_grid(ws_c),
            merges=_merge_index(ws_f),
        ))

    return _assemble_document(src, parse, did, metadata, sheet_inputs)


def _parse_xls(ctx: ParseContext, parser_name: str, parser_version: str) -> Document:
    from .base import _iso_now  # type: ignore
    import xlrd

    started = _iso_now()
    src, parse, did = build_source_and_parse(
        ctx, "xls", parser_name, parser_version, started_at=started, confidence=0.85,
    )

    book = xlrd.open_workbook(str(ctx.path), formatting_info=True, on_demand=True, use_mmap=False)
    metadata: dict = {}  # xlrd exposes limited metadata; skip for parity.

    sheet_inputs: list[_SheetInput] = []
    for idx, sh in enumerate(book.sheets()):
        formula_cells = _xls_formula_cells(book, sh)
        sheet_inputs.append(_SheetInput(
            name=sh.name,
            index=idx,
            visibility=_xls_visibility(sh),
            used_range=_xls_used_range(sh),
            grid_f=_xls_grid(sh, book=book, formula_cells=formula_cells, formula_mode=True),
            grid_c=_xls_grid(sh, book=book, formula_cells=formula_cells, formula_mode=False),
            merges=_xls_merge_index(sh),
        ))

    return _assemble_document(src, parse, did, metadata, sheet_inputs)


def _assemble_document(src, parse, did: str, metadata: dict, sheet_inputs: list[_SheetInput]) -> Document:
    sheets: list[Sheet] = []
    tables: list[Table] = []
    warnings: list[Warning] = []
    formula_seen = False

    for si in sheet_inputs:
        sid = sheet_id(did, si.name, si.index)
        regions: list[SheetRegion] = []
        sheet_tables: list[Table] = []

        components = _flood_fill_components(si.grid_f, si.merges)
        for order, comp in enumerate(components):
            r0, c0, r1, c1 = _bbox(comp)
            rng = f"{get_column_letter(c0)}{r0}:{get_column_letter(c1)}{r1}"
            height = r1 - r0 + 1
            width = c1 - c0 + 1

            if height >= 2 and width >= 2:
                tid = table_id(did, f"sheet:{sid}:{rng}", order)
                tbl, had_formula = _build_table(
                    tid, sid, si.name, None, None,
                    si.grid_f, si.grid_c, si.merges, r0, c0, r1, c1,
                )
                tables.append(tbl)
                sheet_tables.append(tbl)
                formula_seen = formula_seen or had_formula
                regions.append(SheetRegion(
                    id=region_id(sid, rng), kind="data_table", range=rng, table_id=tid,
                ))
            else:
                texts = [
                    _cell_text(si.grid_f.get((r, c))) or ""
                    for r in range(r0, r1 + 1)
                    for c in range(c0, c1 + 1)
                ]
                joined = " ".join(t for t in texts if t).strip()
                regions.append(SheetRegion(
                    id=region_id(sid, rng),
                    kind="note",
                    range=rng,
                    text=joined or None,
                ))

        sheets.append(Sheet(
            id=sid,
            sheet_name=si.name,
            index=si.index,
            visibility=si.visibility,  # type: ignore[arg-type]
            used_range=si.used_range,
            table_ids=[t.id for t in sheet_tables],
            regions=regions,
        ))

    if formula_seen:
        warnings.append(Warning(
            code="formula_not_evaluated",
            message="Formulas captured as strings; cached values used when available.",
        ))

    return Document(
        id=did,
        source=src,
        metadata=metadata,
        parse=finalize_parse(parse),
        warnings=warnings,
        sheets=sheets,
        tables=tables,
    )


# ----- xls adapters -----

@dataclass
class _SimpleCell:
    row: int
    column: int
    value: Any


@dataclass(frozen=True)
class _FormulaCellInfo:
    formula: str
    display_value: Any


def _xls_formula_cells(book, sh) -> dict[tuple[int, int], _FormulaCellInfo]:
    import xlrd
    from xlrd.formula import FMLA_TYPE_CELL, decompile_formula

    raw = getattr(book, "filestr", None)
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        return {}
    pos = getattr(sh, "_position", None)
    if not isinstance(pos, int):
        return {}

    out: dict[tuple[int, int], _FormulaCellInfo] = {}
    end = len(raw)
    while pos + 4 <= end:
        opcode, length = struct.unpack_from("<HH", raw, pos)
        data = raw[pos + 4:pos + 4 + length]
        pos += 4 + length
        if opcode == 0x000A:  # EOF
            break
        if opcode not in (0x0006, 0x0206, 0x0406):
            continue
        if len(data) < 22:
            continue
        rowx, colx = struct.unpack_from("<HH", data, 0)
        result_str = data[6:14]
        flags = struct.unpack_from("<H", data, 14)[0]
        fmlalen = struct.unpack_from("<H", data, 20)[0]
        try:
            formula = decompile_formula(
                book, data[22:], fmlalen, FMLA_TYPE_CELL, browx=rowx, bcolx=colx, blah=0, r1c1=0,
            )
        except Exception:
            continue
        if result_str[6:8] == b"\xFF\xFF":
            first_byte = result_str[0]
            if first_byte == 0:
                display_value = ""
            elif first_byte == 1:
                display_value = bool(result_str[2])
            elif first_byte == 2:
                display_value = xlrd.error_text_from_code.get(int(result_str[2]), f"#ERR{result_str[2]}")
            elif first_byte == 3:
                display_value = ""
            else:
                display_value = None
        else:
            display_value = struct.unpack_from("<d", result_str, 0)[0]
            if float(display_value).is_integer():
                display_value = int(display_value)
        out[(rowx + 1, colx + 1)] = _FormulaCellInfo(formula=formula, display_value=display_value)
    return out


def _xls_visibility(sh) -> str:
    v = getattr(sh, "visibility", 0)
    return {0: "visible", 1: "hidden", 2: "very_hidden"}.get(int(v), "visible")


def _xls_used_range(sh) -> str | None:
    if sh.nrows == 0 or sh.ncols == 0:
        return None
    return f"A1:{get_column_letter(sh.ncols)}{sh.nrows}"


def _xls_grid(
    sh,
    book=None,
    formula_cells: dict[tuple[int, int], _FormulaCellInfo] | None = None,
    formula_mode: bool = False,
) -> dict[tuple[int, int], _SimpleCell]:
    import xlrd
    grid: dict[tuple[int, int], _SimpleCell] = {}
    formula_cells = formula_cells or {}
    for r in range(sh.nrows):
        for c in range(sh.ncols):
            formula_info = formula_cells.get((r + 1, c + 1))
            ctype = sh.cell_type(r, c)
            if ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK) and formula_info is None:
                continue
            v = sh.cell_value(r, c)
            if v is None or v == "":
                if formula_info is None:
                    continue
            if formula_info is not None:
                v = formula_info.formula if formula_mode else formula_info.display_value
            elif ctype == xlrd.XL_CELL_NUMBER and float(v).is_integer():
                v = int(v)
            elif ctype == xlrd.XL_CELL_DATE and book is not None:
                try:
                    t = xlrd.xldate_as_tuple(v, book.datemode)
                    import datetime as _dt
                    y, mo, d, hh, mm, ss = t
                    if y == 0 and mo == 0 and d == 0:
                        v = _dt.time(hh, mm, ss).isoformat()
                    else:
                        v = _dt.datetime(y, mo, d, hh, mm, ss).isoformat()
                except Exception:
                    pass  # leave as float fallback
            elif ctype == xlrd.XL_CELL_BOOLEAN:
                v = bool(v)
            elif ctype == xlrd.XL_CELL_ERROR:
                try:
                    v = xlrd.error_text_from_code.get(int(v), f"#ERR{v}")
                except Exception:
                    pass
            grid[(r + 1, c + 1)] = _SimpleCell(row=r + 1, column=c + 1, value=v)
    return grid


def _xls_merge_index(sh) -> dict[tuple[int, int], _MergeInfo]:
    """xlrd merged_cells is (rlo, rhi, clo, chi) with rhi/chi exclusive (0-based)."""
    out: dict[tuple[int, int], _MergeInfo] = {}
    for rlo, rhi, clo, chi in sh.merged_cells:
        r0, c0 = rlo + 1, clo + 1
        r1, c1 = rhi, chi  # 1-based inclusive end
        info = _MergeInfo(anchor=(r0, c0), r0=r0, c0=c0, r1=r1, c1=c1)
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                out[(r, c)] = info
    return out


# ----- helpers -----

def _workbook_metadata(wb) -> dict:
    p = wb.properties

    def _maybe_iso(v):
        if v is None:
            return None
        if isinstance(v, _dt.datetime):
            return v.isoformat()
        return str(v) if v else None

    out = {
        "title": p.title,
        "creator": p.creator,
        "description": p.description,
        "keywords": p.keywords,
        "created": _maybe_iso(p.created),
        "modified": _maybe_iso(p.modified),
    }
    return {k: v for k, v in out.items() if v}


def _visibility(ws) -> str:
    state = getattr(ws, "sheet_state", "visible") or "visible"
    return state if state in ("visible", "hidden", "very_hidden") else "visible"


def _used_range(ws) -> str | None:
    dim = ws.calculate_dimension()
    if not dim or dim in ("A1", "A1:A1") and ws.max_row == 1 and ws.max_column == 1:
        # still return A1 to be explicit
        return dim or None
    return dim


def _sheet_grid(ws) -> dict[tuple[int, int], Any]:
    grid: dict[tuple[int, int], Any] = {}
    for row in ws.iter_rows():
        for cell in row:
            v = cell.value
            if v is None:
                continue
            if isinstance(v, str) and v == "":
                continue
            grid[(cell.row, cell.column)] = cell
    return grid


@dataclass(frozen=True)
class _MergeInfo:
    anchor: tuple[int, int]
    r0: int
    c0: int
    r1: int
    c1: int


def _merge_index(ws) -> dict[tuple[int, int], _MergeInfo]:
    out: dict[tuple[int, int], _MergeInfo] = {}
    for mr in ws.merged_cells.ranges:
        info = _MergeInfo(
            anchor=(mr.min_row, mr.min_col),
            r0=mr.min_row, c0=mr.min_col, r1=mr.max_row, c1=mr.max_col,
        )
        for r in range(mr.min_row, mr.max_row + 1):
            for c in range(mr.min_col, mr.max_col + 1):
                out[(r, c)] = info
    return out


def _occupied(
    grid: dict[tuple[int, int], Any],
    merges: dict[tuple[int, int], _MergeInfo],
) -> set[tuple[int, int]]:
    cells = set(grid.keys())
    for (r, c), info in merges.items():
        anchor = info.anchor
        if anchor in grid:
            cells.add((r, c))
    return cells


def _flood_fill_components(
    grid: dict[tuple[int, int], Any],
    merges: dict[tuple[int, int], _MergeInfo],
) -> list[set[tuple[int, int]]]:
    occ = _occupied(grid, merges)
    seen: set[tuple[int, int]] = set()
    comps: list[set[tuple[int, int]]] = []
    for start in sorted(occ):
        if start in seen:
            continue
        stack = [start]
        comp: set[tuple[int, int]] = set()
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            comp.add(node)
            r, c = node
            for nb in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if nb in occ and nb not in seen:
                    stack.append(nb)
        comps.append(comp)
    comps.sort(key=lambda s: (min(r for r, _ in s), min(c for _, c in s)))
    return comps


def _bbox(cells: set[tuple[int, int]]) -> tuple[int, int, int, int]:
    rs = [r for r, _ in cells]
    cs = [c for _, c in cells]
    return min(rs), min(cs), max(rs), max(cs)


def _cell_text(cell) -> str | None:
    if cell is None:
        return None
    v = cell.value
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, _dt.datetime):
        return v.isoformat()
    return str(v)


def _build_table(
    tid: str,
    sheet_ref: str,
    sheet_name: str,
    _ws_f, _ws_c,  # kept positional for call-site symmetry; not used internally
    grid_f: dict[tuple[int, int], Any],
    grid_c: dict[tuple[int, int], Any],
    merges: dict[tuple[int, int], _MergeInfo],
    r0: int, c0: int, r1: int, c1: int,
) -> tuple[Table, bool]:
    rows: list[list[TableCell]] = []
    had_formula = False
    emitted: set[tuple[int, int]] = set()

    for ri, r in enumerate(range(r0, r1 + 1)):
        cells: list[TableCell] = []
        for ci, c in enumerate(range(c0, c1 + 1)):
            if (r, c) in emitted:
                continue
            mi = merges.get((r, c))
            if mi is not None and (r, c) != mi.anchor:
                # non-anchor merged cell — skip, emitted by anchor
                continue
            row_span = 1
            col_span = 1
            if mi is not None:
                row_span = mi.r1 - mi.r0 + 1
                col_span = mi.c1 - mi.c0 + 1
                for rr in range(mi.r0, mi.r1 + 1):
                    for cc in range(mi.c0, mi.c1 + 1):
                        emitted.add((rr, cc))
            cell_f = grid_f.get((r, c))
            cell_c = grid_c.get((r, c))
            raw = cell_f.value if cell_f is not None else None
            display = _cell_text(cell_c)
            formula: str | None = None
            if isinstance(raw, str) and raw.startswith("="):
                formula = raw
                had_formula = True
                # raw_value for formula: formula text; display_value: cached result.
            text = display if display is not None else _cell_text(cell_f)
            raw_value = formula if formula is not None else raw
            cells.append(TableCell(
                row=ri,
                col=ci,
                text=text,
                raw_value=raw_value,
                display_value=display,
                formula=formula,
                row_span=row_span,
                col_span=col_span,
            ))
        rows.append(cells)

    # header: first row texts
    columns = [(c.text or "") for c in rows[0]] if rows else []
    tbl = Table(
        id=tid,
        section_id=None,
        sheet=sheet_name,
        columns=columns,
        rows=rows,
    )
    return tbl, had_formula
