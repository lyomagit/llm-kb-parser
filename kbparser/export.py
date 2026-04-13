"""Deterministic JSON writer."""
from __future__ import annotations

import json
from pathlib import Path

from .model import Document, Output, Record


def to_output(doc: Document, records: list[Record] | None = None) -> Output:
    return Output(document=doc, records=list(records or []))


def write_json(out: Output, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = out.model_dump(mode="json", exclude_none=False)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    return path
