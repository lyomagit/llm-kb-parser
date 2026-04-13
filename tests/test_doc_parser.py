"""Tests for DOC legacy parser.

When LibreOffice is absent: asserts DocConverterMissing is raised with a
clear actionable message and CLI returns failed status.

When LibreOffice is present: converts the DOCX fixture saved as .doc to
exercise the full round-trip.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kbparser.parsers.base import ParseContext
from kbparser.parsers.doc import DOCParser, DocConverterMissing, _find_soffice
from kbparser.cli import main

from .fixtures_gen.build_docx import build_basic as build_docx


SOFFICE = _find_soffice()


def _minimal_doc_bytes() -> bytes:
    """Empty-ish OLE container bytes. Not a valid DOC, but triggers dispatch."""
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512


def _write_fake_doc(path: Path) -> Path:
    path.write_bytes(_minimal_doc_bytes())
    return path


@pytest.mark.skipif(SOFFICE is not None, reason="soffice present; tested on happy path")
def test_missing_soffice_raises(tmp_path: Path):
    src = _write_fake_doc(tmp_path / "a.doc")
    parser = DOCParser()
    with pytest.raises(DocConverterMissing) as exc:
        parser.parse(ParseContext(path=src, profile="fidelity"))
    msg = str(exc.value)
    assert "LibreOffice" in msg
    assert "brew" in msg or "apt" in msg


@pytest.mark.skipif(SOFFICE is not None, reason="soffice present; tested on happy path")
def test_cli_reports_failed_when_no_soffice(tmp_path: Path):
    src = _write_fake_doc(tmp_path / "a.doc")
    out = tmp_path / "out"
    rc = main(["parse", str(src), "--out", str(out)])
    assert rc == 1
    # No output file should be written for a hard failure.
    assert not list(out.glob("*.json"))


@pytest.mark.skipif(SOFFICE is None, reason="soffice not installed")
def test_doc_ids_deterministic_across_runs(tmp_path: Path):
    docx_path = build_docx(tmp_path / "source.docx")
    doc_path = tmp_path / "source.doc"
    doc_path.write_bytes(docx_path.read_bytes())

    a = DOCParser().parse(ParseContext(path=doc_path, profile="fidelity"))
    b = DOCParser().parse(ParseContext(path=doc_path, profile="fidelity"))
    assert a.id == b.id
    assert [s.id for s in a.sections] == [s.id for s in b.sections]
    assert [blk.id for blk in a.blocks] == [blk.id for blk in b.blocks]
    assert [t.id for t in a.tables] == [t.id for t in b.tables]


@pytest.mark.skipif(SOFFICE is None, reason="soffice not installed")
def test_doc_roundtrip_via_libreoffice(tmp_path: Path):
    # Use a real DOCX fixture and feed it renamed to .doc → soffice should
    # still accept it (it sniffs content). If not, this test will fail
    # meaningfully and the environment is responsible for producing a true .doc.
    docx_path = build_docx(tmp_path / "source.docx")
    doc_path = tmp_path / "source.doc"
    doc_path.write_bytes(docx_path.read_bytes())

    d = DOCParser().parse(ParseContext(path=doc_path, profile="fidelity"))
    assert d.source.format == "doc"
    assert d.parse.conversion_used is True
    assert d.parse.conversion_info is not None
    assert d.parse.conversion_info["from_format"] == "doc"
    assert any(w.code == "doc_conversion_lost_styles" for w in d.warnings)
    assert len(d.sections) >= 1
