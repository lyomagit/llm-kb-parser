"""DOCX parser — phase 2 real implementation.

Strategy:
- Iterate body inner content in document order (Paragraph | Table).
- Heading styles drive section tree; list styles mark list_item blocks.
- Tables are first-class with raw cell text; grid_span captured where available.
- Provenance: source_ids carry originating XML element ids where present.
"""
from __future__ import annotations

import re

from docx import Document as _DocxDocument
from docx.table import Table as _DocxTable
from docx.text.paragraph import Paragraph as _DocxParagraph

from ..ids import block_id, section_id, table_id
from ..model import Block, Document, Section, Table, TableCell, Warning
from ..versioning import PACKAGE_VERSION
from .base import ParseContext, build_source_and_parse, check_cancelled, finalize_parse


class DOCXParser:
    name = "docx"
    version = PACKAGE_VERSION
    formats = ("docx",)

    def parse(self, ctx: ParseContext) -> Document:
        from .base import _iso_now  # type: ignore
        started = _iso_now()
        src, parse, did = build_source_and_parse(
            ctx, "docx", self.name, self.version, started_at=started, confidence=0.9
        )

        docx_obj = _DocxDocument(str(ctx.path))
        metadata = _core_props(docx_obj)

        state = _BuildState(document_id=did)
        warnings: list[Warning] = []

        for item in _iter_body(docx_obj):
            check_cancelled(ctx.cancelled)
            if isinstance(item, _DocxParagraph):
                _handle_paragraph(item, state)
            elif isinstance(item, _DocxTable):
                _handle_table(item, state, warnings)

        # Introductory content also needs a section when headings occur later.
        orphan_blocks = [blk for blk in state.blocks if blk.section_id is None]
        if orphan_blocks:
            fallback_title = metadata.get("title") or ctx.path.stem
            root = state.push_section(1, str(fallback_title))
            state.sections.remove(root)
            state.sections.insert(0, root)
            for blk in orphan_blocks:
                blk.section_id = root.id
                root.block_ids.append(blk.id)
            for table in state.tables:
                if table.section_id is None:
                    table.section_id = root.id

        return Document(
            id=did,
            source=src,
            metadata=metadata,
            parse=finalize_parse(parse),
            warnings=warnings,
            sections=state.sections,
            blocks=state.blocks,
            tables=state.tables,
        )


# ----- internals -----

def _iter_body(docx_obj):
    """Yield Paragraph | Table in body order."""
    if hasattr(docx_obj, "iter_inner_content"):
        yield from docx_obj.iter_inner_content()
        return
    # Fallback for older python-docx — parallel iteration by XML order.
    from docx.oxml.ns import qn
    body = docx_obj.element.body
    paras = iter(docx_obj.paragraphs)
    tables = iter(docx_obj.tables)
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield next(paras)
        elif child.tag == qn("w:tbl"):
            yield next(tables)


def _core_props(docx_obj) -> dict:
    cp = docx_obj.core_properties

    def _maybe_iso(v):
        if v is None:
            return None
        iso = getattr(v, "isoformat", None)
        return iso() if callable(iso) else str(v)

    out = {
        "title": cp.title or None,
        "author": cp.author or None,
        "subject": cp.subject or None,
        "keywords": cp.keywords or None,
        "created": _maybe_iso(cp.created),
        "modified": _maybe_iso(cp.modified),
    }
    return {k: v for k, v in out.items() if v is not None}


_HEADING_RE = re.compile(r"^Heading\s*(\d+)$", re.IGNORECASE)
_HEADING_ID_RE = re.compile(r"^Heading(\d+)$", re.IGNORECASE)  # python-docx style_id
_LIST_RE = re.compile(r"^List($|\s+(Bullet|Number|Paragraph|Continue))", re.IGNORECASE)


class _BuildState:
    def __init__(self, document_id: str):
        self.document_id = document_id
        self.sections: list[Section] = []
        self.blocks: list[Block] = []
        self.tables: list[Table] = []
        self.section_stack: list[Section] = []  # ancestors incl. current
        self.section_order = 0
        self.block_order = 0
        self.table_order = 0

    def current_section_id(self) -> str | None:
        return self.section_stack[-1].id if self.section_stack else None

    def section_path_from_stack(self) -> list[str]:
        return [s.title or f"sec{s.level}" for s in self.section_stack]

    def push_section(self, level: int, title: str) -> Section:
        while self.section_stack and self.section_stack[-1].level >= level:
            self.section_stack.pop()
        parent_id = self.current_section_id()
        path = self.section_path_from_stack() + [title or f"sec{level}"]
        sid = section_id(self.document_id, path, self.section_order)
        self.section_order += 1
        sec = Section(
            id=sid,
            title=title or None,
            level=level,
            parent_id=parent_id,
            path=path,
        )
        self.sections.append(sec)
        self.section_stack.append(sec)
        return sec

    def add_block(self, btype: str, text: str | None, style_name: str | None = None) -> Block:
        sec_id = self.current_section_id() or ""
        anchor = (text or "")[:40]
        bid = block_id(self.document_id, sec_id, self.block_order, anchor)
        self.block_order += 1
        blk = Block(
            id=bid,
            type=btype,  # type: ignore[arg-type]
            section_id=sec_id or None,
            order=self.block_order,
            text=text,
            style={"name": style_name} if style_name else None,
        )
        self.blocks.append(blk)
        if self.section_stack:
            self.section_stack[-1].block_ids.append(bid)
        return blk

    def add_table(self, tbl: Table) -> None:
        self.tables.append(tbl)


def _handle_paragraph(p, state: _BuildState) -> None:
    text = p.text or ""
    style = p.style if p.style is not None else None
    style_name = (getattr(style, "name", "") or "") if style else ""
    style_id = (getattr(style, "style_id", "") or "") if style else ""

    # Detect heading via localized display name OR English style_id.
    m = _HEADING_RE.match(style_name) or _HEADING_ID_RE.match(style_id)
    if m:
        level = int(m.group(1))
        state.push_section(level, text.strip())
        state.add_block("heading", text, style_name or style_id)
        return

    if style_name and _LIST_RE.match(style_name):
        state.add_block("list_item", text, style_name)
        return

    if not text.strip():
        return  # drop empty paragraphs

    state.add_block("paragraph", text, style_name or None)


def _handle_table(tbl, state: _BuildState, warnings: list[Warning]) -> None:
    # python-docx's row.cells repeats the same Cell for every grid column a
    # merge covers (horizontal gridSpan AND vertical vMerge continuations).
    # Dedupe by _tc identity; compute spans by scanning grid.
    grid: list[list] = [list(row.cells) for row in tbl.rows]
    nrows = len(grid)

    rows_out: list[list[TableCell]] = []
    emitted: set[int] = set()

    for ri in range(nrows):
        out_row: list[TableCell] = []
        row_cells = grid[ri]
        ci = 0
        while ci < len(row_cells):
            cell = row_cells[ci]
            tc = cell._tc
            tid_key = id(tc)
            if tid_key in emitted:
                ci += 1
                continue
            # col_span: consecutive same-tc cells to the right in this row
            col_span = 1
            while ci + col_span < len(row_cells) and row_cells[ci + col_span]._tc is tc:
                col_span += 1
            # row_span: subsequent rows with same tc at column ci
            row_span = 1
            while (
                ri + row_span < nrows
                and ci < len(grid[ri + row_span])
                and grid[ri + row_span][ci]._tc is tc
            ):
                row_span += 1
            emitted.add(tid_key)
            out_row.append(TableCell(
                row=ri, col=ci,
                text=(cell.text or None),
                row_span=row_span,
                col_span=col_span,
            ))
            ci += col_span
        rows_out.append(out_row)

    # columns: first row's texts (merged title becomes a single wide header).
    columns = [(c.text or "") for c in rows_out[0]] if rows_out else []

    sec_id = state.current_section_id()
    location = f"section:{sec_id or 'root'}"
    tid = table_id(state.document_id, location, state.table_order)
    state.table_order += 1

    t = Table(id=tid, section_id=sec_id, columns=columns, rows=rows_out)
    state.add_table(t)
    # emit a table_ref block so flow ordering is visible
    state.add_block("table_ref", None, None)
    state.blocks[-1].text = f"[table {tid}]"
