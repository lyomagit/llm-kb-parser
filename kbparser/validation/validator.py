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

    for rec in records:
        if rec.document_id != doc.id:
            errors.append(f"record {rec.id}: document_id mismatch")
        for nid in rec.source_node_ids:
            if nid not in all_ids:
                errors.append(f"record {rec.id}: source_node_id {nid} missing")
        for tid in rec.source_table_ids:
            if tid not in table_ids:
                errors.append(f"record {rec.id}: source_table_id {tid} missing")

    if errors:
        raise ValidationError(errors)
