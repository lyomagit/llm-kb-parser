"""Determinism tests: same input → same output (excluding timestamps)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kbparser.cli import main
from kbparser.dispatcher import dispatch
from kbparser.export import to_output
from kbparser.records import build_records

from .fixtures_gen.build_docx import build_basic as build_docx
from .fixtures_gen.build_pdf import build_basic as build_pdf
from .fixtures_gen.build_xlsx import build_basic as build_xlsx


def _strip_timestamps(d: dict) -> dict:
    """Recursively remove timestamp fields for comparison."""
    skip = {"started_at", "finished_at", "modified_at"}
    if isinstance(d, dict):
        return {k: _strip_timestamps(v) for k, v in d.items() if k not in skip}
    if isinstance(d, list):
        return [_strip_timestamps(v) for v in d]
    return d


@pytest.mark.parametrize("builder,fmt", [
    (build_docx, "docx"),
    (build_pdf, "pdf"),
    (build_xlsx, "xlsx"),
])
def test_parse_determinism(tmp_path: Path, builder, fmt):
    """Parse same fixture twice, output must be identical (minus timestamps)."""
    fixture = builder(tmp_path / f"test.{fmt}")

    doc1 = dispatch(fixture, profile="fidelity")
    records1 = build_records(doc1)
    out1 = to_output(doc1, records1)

    doc2 = dispatch(fixture, profile="fidelity")
    records2 = build_records(doc2)
    out2 = to_output(doc2, records2)

    j1 = _strip_timestamps(out1.model_dump(mode="json"))
    j2 = _strip_timestamps(out2.model_dump(mode="json"))

    assert j1 == j2, f"Non-deterministic output for {fmt}"


@pytest.mark.parametrize("builder,fmt", [
    (build_docx, "docx"),
    (build_pdf, "pdf"),
    (build_xlsx, "xlsx"),
])
def test_record_ids_stable(tmp_path: Path, builder, fmt):
    """Record IDs must be identical across two runs."""
    fixture = builder(tmp_path / f"test.{fmt}")

    doc1 = dispatch(fixture, profile="fidelity")
    ids1 = [r.id for r in build_records(doc1)]

    doc2 = dispatch(fixture, profile="fidelity")
    ids2 = [r.id for r in build_records(doc2)]

    assert ids1 == ids2, f"Record IDs not stable for {fmt}"


def test_cli_output_determinism(tmp_path: Path):
    """Full CLI roundtrip: same input → same JSON bytes (minus timestamps)."""
    infile = build_pdf(tmp_path / "sample.pdf")
    out1 = tmp_path / "o1"
    out2 = tmp_path / "o2"

    main(["parse", str(infile), "--out", str(out1)])
    main(["parse", str(infile), "--out", str(out2)])

    files1 = sorted(out1.glob("*.json"))
    files2 = sorted(out2.glob("*.json"))
    assert len(files1) == 1
    assert len(files2) == 1

    j1 = _strip_timestamps(json.loads(files1[0].read_text()))
    j2 = _strip_timestamps(json.loads(files2[0].read_text()))
    assert j1 == j2
