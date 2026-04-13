"""Structural validation for canonical Document + derived records."""
from __future__ import annotations

from ..model import Document, Record


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__(f"{len(errors)} validation error(s):\n- " + "\n- ".join(errors))
        self.errors = errors


def validate(doc: Document, records: list[Record] | None = None) -> None:
    errors: list[str] = []
    records = records or []

    section_ids = {s.id for s in doc.sections}
    block_ids = {b.id for b in doc.blocks}
    table_ids = {t.id for t in doc.tables}
    sheet_ids = {s.id for s in doc.sheets}
    asset_ids = {a.id for a in doc.assets}
    all_ids = section_ids | block_ids | table_ids | sheet_ids | asset_ids

    # -- Duplicate ID detection --
    all_id_list = (
        [s.id for s in doc.sections]
        + [b.id for b in doc.blocks]
        + [t.id for t in doc.tables]
        + [s.id for s in doc.sheets]
        + [a.id for a in doc.assets]
    )
    seen_ids: set[str] = set()
    for eid in all_id_list:
        if eid in seen_ids:
            errors.append(f"duplicate entity ID: {eid}")
        seen_ids.add(eid)

    # Section parent refs + cycle detection.
    parent_of: dict[str, str | None] = {s.id: s.parent_id for s in doc.sections}
    for s in doc.sections:
        if s.parent_id and s.parent_id not in section_ids:
            errors.append(f"section {s.id}: parent_id {s.parent_id} missing")
        for bid in s.block_ids:
            if bid not in block_ids:
                errors.append(f"section {s.id}: block_id {bid} missing")
    for sid in section_ids:
        seen: set[str] = set()
        cur: str | None = sid
        while cur is not None:
            if cur in seen:
                errors.append(f"section {sid}: parent cycle")
                break
            seen.add(cur)
            cur = parent_of.get(cur)

    for b in doc.blocks:
        if b.section_id and b.section_id not in section_ids:
            errors.append(f"block {b.id}: section_id {b.section_id} missing")

    for t in doc.tables:
        if t.section_id and t.section_id not in section_ids:
            errors.append(f"table {t.id}: section_id {t.section_id} missing")
        for ri, row in enumerate(t.rows):
            for c in row:
                if c.row != ri:
                    errors.append(f"table {t.id}: cell row mismatch at {ri},{c.col}")
                if c.row_span < 1 or c.col_span < 1:
                    errors.append(f"table {t.id}: bad span at {c.row},{c.col}")

    for p in doc.pages:
        for bid in p.block_ids:
            if bid not in block_ids:
                errors.append(f"page {p.page_number}: block_id {bid} missing")
        for tid in p.table_ids:
            if tid not in table_ids:
                errors.append(f"page {p.page_number}: table_id {tid} missing")
        for aid in p.image_ids:
            if aid not in asset_ids:
                errors.append(f"page {p.page_number}: image_id {aid} missing")

    for sh in doc.sheets:
        for tid in sh.table_ids:
            if tid not in table_ids:
                errors.append(f"sheet {sh.id}: table_id {tid} missing")
        for rg in sh.regions:
            if rg.table_id and rg.table_id not in table_ids:
                errors.append(f"sheet {sh.id}: region table_id {rg.table_id} missing")

    for r in doc.relationships:
        if r.from_id not in all_ids:
            errors.append(f"relationship: from_id {r.from_id} missing")
        if r.to_id not in all_ids:
            errors.append(f"relationship: to_id {r.to_id} missing")

    # -- Record-level validation --
    record_ids_seen: set[str] = set()
    for rec in records:
        # Duplicate record ID
        if rec.id in record_ids_seen:
            errors.append(f"record {rec.id}: duplicate record ID")
        record_ids_seen.add(rec.id)

        if rec.document_id != doc.id:
            errors.append(f"record {rec.id}: document_id mismatch")
        for nid in rec.source_node_ids:
            if nid not in all_ids:
                errors.append(f"record {rec.id}: source_node_id {nid} missing")
        for tid in rec.source_table_ids:
            if tid not in table_ids:
                errors.append(f"record {rec.id}: source_table_id {tid} missing")

        # char_count consistency
        if rec.text is not None and rec.char_count is not None:
            if rec.char_count != len(rec.text):
                errors.append(
                    f"record {rec.id}: char_count {rec.char_count} != len(text) {len(rec.text)}"
                )

        # No empty prose chunks
        if rec.type == "chunk" and not (rec.text or "").strip():
            errors.append(f"record {rec.id}: chunk record has empty text")

    if errors:
        raise ValidationError(errors)
