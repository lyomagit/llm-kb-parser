"""Structure-aware record builder.

Implements spec §13-14. Record types:
- chunk: section-scoped text, split by structure first, token budget second.
- table: one per Table entity, linearized text preview + structured lineage.
- section_summary_seed: short anchor text per top-level section.
- sheet_region: one per non-table region in workbook sheets.

Lineage: every record.source_node_ids references real section/block/table/sheet ids,
so the validator passes.
"""
from __future__ import annotations

import re
from collections import defaultdict

from ..ids import record_id
from ..model import Block, Document, Record, RecordType, Section, Table
from ..normalize.tables import table_content

DEFAULT_MAX_CHARS = 1200  # retrieval-oriented chunk budget
DEFAULT_POLICY = "v2"
_CHARS_PER_TOKEN = 4
_REFERENCE_RE = re.compile(r"^\[\d+\]")
_URL_RE = re.compile(r"https?://")
_DIAGRAM_PREFIXES = ("flowchart", "graph", "sequenceDiagram", "pie title")


def build_records(
    doc: Document,
    policy: str = DEFAULT_POLICY,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[Record]:
    records: list[Record] = []
    if doc.sheets:
        records.extend(_records_from_sheets(doc, policy))
    else:
        records.extend(_records_from_sections(doc, policy, max_chars))
    records.extend(_records_from_tables(doc, policy, max_chars))
    return records


# ----- page-based (pdf/docx/doc) -----

def _records_from_sections(doc: Document, policy: str, max_chars: int) -> list[Record]:
    blocks_by_id: dict[str, Block] = {b.id: b for b in doc.blocks}
    tables_by_section: dict[str, list[Table]] = defaultdict(list)
    for t in doc.tables:
        if t.section_id:
            tables_by_section[t.section_id].append(t)

    out: list[Record] = []
    for sec in doc.sections:
        chunks = _chunks_for_section(
            doc, sec, blocks_by_id, tables_by_section.get(sec.id, []),
            policy, max_chars,
        )
        out.extend(chunks)
        seed = _section_summary_seed(doc, sec, blocks_by_id, policy)
        if seed is not None:
            out.append(seed)
    return out


def _chunks_for_section(
    doc: Document,
    sec: Section,
    blocks_by_id: dict[str, Block],
    linked_tables: list[Table],
    policy: str,
    max_chars: int,
) -> list[Record]:
    blocks = [blocks_by_id[bid] for bid in sec.block_ids if bid in blocks_by_id]
    if not blocks:
        return []

    heading_block = next((b for b in blocks if b.type == "heading"), None)
    body_blocks = [b for b in blocks if b.type != "heading" and b.type != "table_ref"]
    if not body_blocks:
        return []

    reference_blocks = [b for b in body_blocks if _is_reference_like(b)]
    diagram_blocks = [
        b for b in body_blocks
        if not _is_reference_like(b) and _is_diagram_like(b)
    ]
    prose_blocks = [
        b for b in body_blocks
        if not _is_reference_like(b) and not _is_diagram_like(b)
    ]

    records: list[Record] = []
    if prose_blocks:
        records.extend(_records_from_block_group(
            doc,
            sec,
            prose_blocks,
            policy,
            max_chars,
            "chunk",
            heading_block=heading_block,
            include_heading=True,
            linked_tables=linked_tables,
        ))
    if reference_blocks:
        records.extend(_records_from_block_group(
            doc,
            sec,
            reference_blocks,
            policy,
            max_chars,
            "reference_chunk",
        ))
    if diagram_blocks:
        records.extend(_records_from_block_group(
            doc,
            sec,
            diagram_blocks,
            policy,
            max_chars,
            "diagram_chunk",
        ))
    return records


def _records_from_block_group(
    doc: Document,
    sec: Section,
    blocks: list[Block],
    policy: str,
    max_chars: int,
    record_type: RecordType,
    *,
    heading_block: Block | None = None,
    include_heading: bool = False,
    linked_tables: list[Table] | None = None,
) -> list[Record]:
    if not blocks:
        return []

    segments = _split_body(blocks, max_chars)
    records: list[Record] = []
    total = len(segments) or 1

    for idx, seg in enumerate(segments):
        parts: list[str] = []
        node_ids: list[str] = [sec.id]
        seen: set[str] = {sec.id}

        def _add_node(nid: str, seen=seen, node_ids=node_ids):
            if nid and nid not in seen:
                node_ids.append(nid)
                seen.add(nid)

        if include_heading and heading_block is not None and idx == 0:
            parts.append(heading_block.text or "")
            _add_node(heading_block.id)
        for b in seg:
            if b.text:
                parts.append(b.text)
            _add_node(b.id)

        text = "\n\n".join(p for p in parts if p).strip()
        if not text:
            continue

        lineage_ids: list[str] = [sec.id]
        if include_heading and heading_block is not None and idx == 0:
            lineage_ids.append(heading_block.id)
        for b in seg:
            if b.id not in lineage_ids:
                lineage_ids.append(b.id)
        rid = record_id(doc.id, record_type, lineage_ids + [f"seg{idx}"], policy)

        page_blocks = list(seg)
        if include_heading and heading_block is not None and idx == 0:
            page_blocks.append(heading_block)
        page_span = _page_span(page_blocks)
        records.append(Record(
            id=rid,
            type=record_type,
            document_id=doc.id,
            text=text,
            char_count=len(text),
            token_estimate=max(1, len(text) // _CHARS_PER_TOKEN),
            section_path=list(sec.path),
            section_title=sec.title,
            page_span=page_span,
            source_node_ids=node_ids,
            source_table_ids=[t.id for t in (linked_tables or [])] if record_type == "chunk" and idx == total - 1 else [],
            metadata={
                "segment_index": idx,
                "segment_total": total,
                "policy": policy,
            },
        ))

    return records


def _is_reference_like(block: Block) -> bool:
    text = (block.text or "").strip()
    if not text:
        return False
    if _REFERENCE_RE.match(text):
        return True
    return bool(len(text) < 300 and _URL_RE.search(text))


def _is_diagram_like(block: Block) -> bool:
    text = (block.text or "").strip()
    style_name = ((block.style or {}).get("name") or "").strip()
    if not text:
        return False
    if style_name == "Source Code":
        return True
    return text.startswith(_DIAGRAM_PREFIXES)


def _split_body(blocks: list[Block], max_chars: int) -> list[list[Block]]:
    """Group body blocks into segments not exceeding max_chars.

    Boundary priority: list boundaries > paragraph groups > hard split.
    Heading separators are handled one level up (heading always lives with
    first segment).

    A single block whose text exceeds max_chars is pre-split into virtual
    sub-blocks on whitespace so a single oversized paragraph cannot blow the
    chunk budget.
    """
    work: list[Block] = []
    for b in blocks:
        t = b.text or ""
        if len(t) <= max_chars:
            work.append(b)
        else:
            work.extend(_virtual_split_block(b, max_chars))

    segments: list[list[Block]] = []
    current: list[Block] = []
    current_chars = 0

    def flush():
        nonlocal current, current_chars
        if current:
            segments.append(current)
            current = []
            current_chars = 0

    prev_type: str | None = None
    for b in work:
        text_len = len(b.text or "") + 2
        boundary = prev_type is not None and prev_type != b.type
        if current_chars + text_len > max_chars and current or boundary and current_chars > max_chars * 0.7:
            flush()
        current.append(b)
        current_chars += text_len
        prev_type = b.type
    flush()
    return segments or [[]]


def _virtual_split_block(b: Block, max_chars: int) -> list[Block]:
    """Split b.text into multiple Block shells preserving section_id, type, id.

    The produced blocks share the original id so record lineage stays truthful
    (segment_index + source_node_ids(b.id) still point at the original block).
    """
    text = b.text or ""
    pieces: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            # step back to the previous whitespace boundary to avoid cutting words
            back = text.rfind(" ", start, end)
            if back > start + max_chars // 2:
                end = back
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        start = max(end, start + 1)
    if len(pieces) <= 1:
        return [b]
    # Build shallow copies sharing id/type so lineage remains stable.
    out: list[Block] = []
    for piece in pieces:
        out.append(Block(
            id=b.id,
            type=b.type,
            section_id=b.section_id,
            page=b.page,
            sheet=b.sheet,
            order=b.order,
            text=piece,
            style=b.style,
            bbox=b.bbox,
            provenance=b.provenance,
        ))
    return out


def _page_span(blocks: list[Block]) -> list[int] | None:
    pages = [b.page for b in blocks if b.page is not None]
    if not pages:
        return None
    return [min(pages), max(pages)]


def _section_summary_seed(
    doc: Document,
    sec: Section,
    blocks_by_id: dict[str, Block],
    policy: str,
) -> Record | None:
    if sec.level != 1:
        return None
    head = sec.title or ""
    first_para: str | None = None
    for bid in sec.block_ids:
        b = blocks_by_id.get(bid)
        if b is None or b.type in ("heading", "table_ref"):
            continue
        if b.text:
            first_para = b.text
            break
    # Require body content; a title-only seed is too weak as a summary anchor.
    if not first_para:
        return None
    text = f"{head}\n{first_para[:400]}".strip()
    if not text:
        return None
    return Record(
        id=record_id(doc.id, "section_summary_seed", [sec.id], policy),
        type="section_summary_seed",
        document_id=doc.id,
        text=text,
        char_count=len(text),
        token_estimate=max(1, len(text) // _CHARS_PER_TOKEN),
        section_path=list(sec.path),
        section_title=sec.title,
        source_node_ids=[sec.id],
        metadata={"policy": policy},
    )


# ----- tables -----

def _records_from_tables(doc: Document, policy: str, max_chars: int) -> list[Record]:
    out: list[Record] = []
    for t in doc.tables:
        headers, rows = table_content(t)
        prefix = "\n".join(s for s in [t.title, " | ".join(headers) if any(headers) else None] if s)
        groups: list[list[tuple[int, str]]] = []
        group: list[tuple[int, str]] = []
        size = len(prefix)
        for row_index, values in rows:
            line = " | ".join(values)
            if group and size + len(line) + 1 > max_chars:
                groups.append(group)
                group, size = [], len(prefix)
            group.append((row_index, line))
            size += len(line) + 1
        if group or not groups:
            groups.append(group)
        lineage = [t.id] + ([t.section_id] if t.section_id else [])
        for index, group in enumerate(groups):
            text = "\n".join(s for s in [prefix, *(line for _, line in group)] if s).strip()
            out.append(Record(
                id=record_id(doc.id, "table", lineage + [f"seg{index}"], policy),
                type="table",
                document_id=doc.id,
                text=text,
                char_count=len(text) if text else 0,
                token_estimate=max(1, (len(text) // _CHARS_PER_TOKEN) if text else 1),
                section_title=_section_title(doc, t.section_id),
                page_span=[t.page, t.page] if t.page is not None else None,
                sheet_name=t.sheet,
                source_node_ids=[sid for sid in [t.section_id] if sid],
                source_table_ids=[t.id],
                metadata={
                    "rows": len(t.rows),
                    "cols": len(t.columns),
                    "has_formula": any(c.formula for row in t.rows for c in row),
                    "policy": policy,
                    "row_span": [group[0][0], group[-1][0]] if group else None,
                    "segment_index": index,
                    "segment_total": len(groups),
                    "oversized_row": len(text) > max_chars,
                },
            ))
    return out


def _section_title(doc: Document, section_id: str | None) -> str | None:
    if section_id is None:
        return None
    for s in doc.sections:
        if s.id == section_id:
            return s.title
    return None


# ----- sheet regions -----

def _records_from_sheets(doc: Document, policy: str) -> list[Record]:
    out: list[Record] = []
    for sh in doc.sheets:
        for rg in sh.regions:
            if rg.kind == "data_table":
                # handled by table record via t.sheet name; skip duplicate here.
                continue
            text = rg.text or ""
            if not text.strip():
                continue
            out.append(Record(
                id=record_id(doc.id, "sheet_region", [sh.id, rg.id], policy),
                type="sheet_region",
                document_id=doc.id,
                text=text,
                char_count=len(text),
                token_estimate=max(1, len(text) // _CHARS_PER_TOKEN),
                sheet_name=sh.sheet_name,
                source_node_ids=[sh.id],
                metadata={
                    "kind": rg.kind,
                    "range": rg.range,
                    "policy": policy,
                },
            ))
    return out
