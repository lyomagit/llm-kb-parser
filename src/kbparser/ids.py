"""Deterministic IDs. Same input + profile => same IDs across runs."""
from __future__ import annotations

import hashlib
from pathlib import Path


def _short(h: str, n: int = 12) -> str:
    return h[:n]


def sha256_file(path: str | Path, chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _hash(*parts: str) -> str:
    joined = "\x1f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def doc_id(sha256: str, profile: str) -> str:
    return f"doc_{_short(_hash(sha256, profile))}"


def section_id(document_id: str, path: list[str], order: int) -> str:
    return f"sec_{_short(_hash(document_id, '/'.join(path), str(order)))}"


def block_id(document_id: str, section_ref: str, order: int, text_anchor: str = "") -> str:
    return f"blk_{_short(_hash(document_id, section_ref, str(order), text_anchor))}"


def table_id(document_id: str, location: str, order: int) -> str:
    return f"tbl_{_short(_hash(document_id, location, str(order)))}"


def sheet_id(document_id: str, sheet_name: str, index: int) -> str:
    return f"sht_{_short(_hash(document_id, sheet_name, str(index)))}"


def region_id(sheet_ref: str, range_a1: str) -> str:
    return f"rgn_{_short(_hash(sheet_ref, range_a1))}"


def asset_id(document_id: str, kind: str, order: int) -> str:
    return f"ast_{_short(_hash(document_id, kind, str(order)))}"


def record_id(document_id: str, kind: str, lineage: list[str], policy: str = "v1") -> str:
    return f"rec_{_short(_hash(document_id, kind, '|'.join(lineage), policy))}"
