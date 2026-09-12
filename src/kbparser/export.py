"""Deterministic JSON and Markdown writers with versioned output."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import __version__
from .model import Block, Document, Output, Record, Table
from .normalize.tables import table_content
from .validation import ValidationError, validate
from .versioning import RECORDS_VERSION, SCHEMA_VERSION


def to_output(doc: Document, records: list[Record] | None = None) -> Output:
    return Output(
        schema_version=SCHEMA_VERSION,
        records_version=RECORDS_VERSION,
        parser_version=__version__,
        document=doc,
        records=list(records or []),
    )


@contextmanager
def atomic_text(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(out: Output, path: Path) -> Path:
    payload = out.model_dump(mode="json", exclude_none=False)
    with atomic_text(path) as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    return path


def write_markdown(out: Output, path: Path) -> Path:
    text = to_markdown(out)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    codes = ",".join(w.code for w in out.document.warnings) or "-"
    with atomic_text(path) as stream:
        stream.write(f"{text}\n<!-- kbparser-cache {_output_key(out)} {digest} {codes} -->\n")
    return path


def processing_key(path: Path, sha256: str, profile: str, ocr_langs: str | None, *,
                   parser_version: str = __version__, schema_version: str = SCHEMA_VERSION,
                   records_version: str = RECORDS_VERSION) -> str:
    values = [str(path.resolve()), sha256, profile, ocr_langs,
              parser_version, schema_version, records_version]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def _output_key(out: Output) -> str:
    doc = out.document
    return processing_key(Path(doc.source.path), doc.source.sha256, doc.parse.profile,
                          doc.parse.ocr_languages, parser_version=out.parser_version,
                          schema_version=out.schema_version, records_version=out.records_version)


def read_export_key(path: Path) -> str | None:
    return read_export_cache(path)[0]


def read_export_cache(path: Path) -> tuple[str | None, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            out = Output.model_validate_json(text)
            validate(out.document, out.records)
            return _output_key(out), [w.code for w in out.document.warnings]
        body, marker = text.rsplit("\n<!-- kbparser-cache ", 1)
        key, digest, codes, end = marker.strip().split()
        if end == "-->" and hashlib.sha256(body.encode("utf-8")).hexdigest() == digest:
            return key, codes.split(",") if codes != "-" else []
    except (OSError, ValueError, ValidationError):
        pass
    return None, []


def to_markdown(out: Output) -> str:
    doc = out.document
    lines: list[str] = [f"# {_clean_text(doc.source.filename)}", ""]
    lines.extend([
        f"- Format: `{doc.source.format}`",
        f"- Parser: `{doc.parse.parser}`",
        f"- Profile: `{doc.parse.profile}`",
    ])
    if doc.warnings:
        codes = ", ".join(w.code for w in doc.warnings)
        lines.append(f"- Warnings: {codes}")
    lines.append("")

    rendered_tables: set[str] = set()
    tables_by_id = {table.id: table for table in doc.tables}
    if doc.sheets:
        _render_sheets(lines, doc, rendered_tables)
    if doc.sections:
        _render_sections(lines, doc, rendered_tables)
    else:
        _render_blocks(lines, sorted(doc.blocks, key=lambda b: b.order), heading_level=2,
                       tables=tables_by_id, rendered_tables=rendered_tables)

    for table in doc.tables:
        if table.id not in rendered_tables:
            _render_table(lines, table, heading_level=3)
            rendered_tables.add(table.id)

    if not doc.sections and not doc.blocks and not doc.tables and out.records:
        _render_records_fallback(lines, out.records)

    return _normalize_blank_lines(lines).rstrip() + "\n"


def _render_sections(lines: list[str], doc: Document, rendered_tables: set[str]) -> None:
    blocks_by_id = {b.id: b for b in doc.blocks}
    tables_by_id = {table.id: table for table in doc.tables}
    tables_by_section: dict[str | None, list[Table]] = {}
    for table in doc.tables:
        tables_by_section.setdefault(table.section_id, []).append(table)

    for section in doc.sections:
        title = section.title or "Untitled section"
        level = min(max(section.level + 1, 2), 6)
        _append_heading(lines, level, title)
        blocks = [blocks_by_id[b] for b in section.block_ids if b in blocks_by_id]
        if not blocks:
            blocks = [b for b in doc.blocks if b.section_id == section.id]
        _render_blocks(
            lines,
            sorted(blocks, key=lambda b: b.order),
            heading_level=min(level + 1, 6),
            section_title=title,
            tables=tables_by_id,
            rendered_tables=rendered_tables,
        )
        for table in tables_by_section.get(section.id, []):
            if table.id not in rendered_tables:
                _render_table(lines, table, heading_level=min(level + 1, 6))
                rendered_tables.add(table.id)


def _render_sheets(lines: list[str], doc: Document, rendered_tables: set[str]) -> None:
    tables = {table.id: table for table in doc.tables}
    for sheet in doc.sheets:
        _append_heading(lines, 2, sheet.sheet_name)
        if sheet.used_range:
            lines.extend([f"Range: `{sheet.used_range}`", ""])
        for note in sheet.notes:
            lines.extend([_escape_text(note), ""])
        for region in sheet.regions:
            if region.text:
                lines.extend([_escape_text(region.text), ""])
            if region.table_id in tables and region.table_id not in rendered_tables:
                _render_table(lines, tables[region.table_id], heading_level=3)
                rendered_tables.add(region.table_id)
        for tid in sheet.table_ids:
            if tid in tables and tid not in rendered_tables:
                _render_table(lines, tables[tid], heading_level=3)
                rendered_tables.add(tid)


def _render_blocks(
    lines: list[str],
    blocks: list[Block],
    *,
    heading_level: int,
    section_title: str | None = None,
    tables: dict[str, Table] | None = None,
    rendered_tables: set[str] | None = None,
) -> None:
    for block in blocks:
        text = _clean_text(block.text)
        if block.type == "table_ref":
            tid = text.removeprefix("[table ").removesuffix("]")
            if tables and tid in tables and rendered_tables is not None and tid not in rendered_tables:
                _render_table(lines, tables[tid], heading_level=heading_level)
                rendered_tables.add(tid)
            continue
        if not text:
            continue
        if block.type == "heading":
            if section_title and text.strip() == section_title.strip():
                continue
            _append_heading(lines, heading_level, text)
        elif block.type in {"list", "list_item"}:
            lines.append(f"- {_escape_text(text)}")
        else:
            lines.extend([_escape_text(text), ""])


def _render_table(lines: list[str], table: Table, *, heading_level: int) -> None:
    title = table.title or table.summary_text or "Table"
    _append_heading(lines, heading_level, title)

    headers, rows = table_content(table)
    col_count = len(headers)
    if col_count == 0:
        return

    if not any(headers):
        headers = [f"Column {i + 1}" for i in range(col_count)]
    lines.append("| " + " | ".join(_escape_table_cell(h) for h in headers[:col_count]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(col_count)) + " |")
    for _, values in rows:
        lines.append("| " + " | ".join(_escape_table_cell(v) for v in values[:col_count]) + " |")
    lines.append("")


def _render_records_fallback(lines: list[str], records: list[Record]) -> None:
    _append_heading(lines, 2, "Records")
    for record in records:
        if record.text:
            lines.extend([_escape_text(record.text), ""])


def _append_heading(lines: list[str], level: int, text: str) -> None:
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(f"{'#' * min(max(level, 1), 6)} {_clean_text(text)}")
    lines.append("")


def _clean_text(text: object | None) -> str:
    if text is None:
        return ""
    return str(text).replace("\r\n", "\n").replace("\r", "\n").strip()


def _escape_text(text: str) -> str:
    return _clean_text(text).replace("|", "\\|")


def _escape_table_cell(text: str) -> str:
    return _escape_text(text).replace("\n", "<br>")


def _normalize_blank_lines(lines: list[str]) -> str:
    normalized: list[str] = []
    previous_blank = False
    for line in lines:
        blank = line == ""
        if blank and previous_blank:
            continue
        normalized.append(line)
        previous_blank = blank
    return "\n".join(normalized)
