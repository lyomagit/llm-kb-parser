"""Phase 1 smoke: dispatcher + CLI roundtrip with stub parsers.

Uses fake byte files with correct magic headers — stubs don't actually parse.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kbparser.cli import _status_marker, main
from kbparser.dispatcher import UnsupportedFormat, detect_format, dispatch

from .fixtures_gen.build_docx import build_basic
from .fixtures_gen.build_pdf import build_basic as build_basic_pdf


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + b"0" * 256
ZIP_BYTES = b"PK\x03\x04" + b"0" * 256
OLE_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 256


@pytest.mark.parametrize(
    "name,data,fmt",
    [
        ("a.pdf", PDF_BYTES, "pdf"),
        ("a.docx", ZIP_BYTES, "docx"),
        ("a.xlsx", ZIP_BYTES, "xlsx"),
        ("a.doc", OLE_BYTES, "doc"),
        ("a.xls", OLE_BYTES, "xls"),
    ],
)
def test_detect_format(tmp_path: Path, name: str, data: bytes, fmt: str):
    p = _write(tmp_path / name, data)
    assert detect_format(p) == fmt


def test_detect_mismatched_magic(tmp_path: Path):
    p = _write(tmp_path / "a.pdf", b"not a pdf")
    with pytest.raises(UnsupportedFormat):
        detect_format(p)


def test_detect_unsupported_ext(tmp_path: Path):
    p = _write(tmp_path / "a.txt", b"hi")
    with pytest.raises(UnsupportedFormat):
        detect_format(p)


def test_dispatch_docx_returns_valid_document(tmp_path: Path):
    p = build_basic(tmp_path / "a.docx")
    doc = dispatch(p, profile="fidelity")
    assert doc.id.startswith("doc_")
    assert doc.source.format == "docx"
    assert doc.parse.profile == "fidelity"
    assert doc.parse.parser == "docx"


def test_cli_parse_single_file(tmp_path: Path, capsys):
    infile = build_basic_pdf(tmp_path / "sample.pdf")
    outdir = tmp_path / "out"
    rc = main(["parse", str(infile), "--out", str(outdir), "--profile", "fidelity"])
    assert rc == 0
    files = list(outdir.glob("*.json"))
    assert len(files) == 1
    assert files[0].name == "sample.pdf.json"
    payload = json.loads(files[0].read_text())
    assert "document" in payload and "records" in payload
    assert payload["document"]["source"]["format"] == "pdf"


def test_cli_output_filename_uses_source_filename(tmp_path: Path):
    infile = build_basic_pdf(tmp_path / "Путь выздоровления.pdf")
    outdir = tmp_path / "out"

    rc = main(["parse", str(infile), "--out", str(outdir)])

    assert rc == 0
    assert (outdir / "Путь выздоровления.pdf.json").exists()


def test_cli_output_filename_sanitizes_reserved_chars(tmp_path: Path):
    infile = build_basic_pdf(tmp_path / "bad:name?.pdf")
    outdir = tmp_path / "out"

    rc = main(["parse", str(infile), "--out", str(outdir)])

    assert rc == 0
    assert (outdir / "bad_name_.pdf.json").exists()


def test_cli_duplicate_source_names_get_stable_suffixes(tmp_path: Path):
    indir = tmp_path / "in"
    one = indir / "one"
    two = indir / "two"
    one.mkdir(parents=True)
    two.mkdir(parents=True)
    build_basic_pdf(one / "sample.pdf")
    build_basic_pdf(two / "sample.pdf")
    outdir = tmp_path / "out"

    rc = main(["parse", str(indir), "--out", str(outdir)])

    assert rc == 0
    files = sorted(p.name for p in outdir.glob("*.json") if p.name != "manifest.json")
    assert len(files) == 2
    assert all(name.startswith("sample.pdf__") and name.endswith(".json") for name in files)


def test_cli_deterministic_output_filename(tmp_path: Path):
    infile = build_basic_pdf(tmp_path / "sample.pdf")
    out1 = tmp_path / "o1"
    out2 = tmp_path / "o2"
    main(["parse", str(infile), "--out", str(out1)])
    main(["parse", str(infile), "--out", str(out2)])
    ids1 = {p.name for p in out1.glob("*.json")}
    ids2 = {p.name for p in out2.glob("*.json")}
    assert ids1 == ids2


def test_cli_default_out_dir_for_directory_input(tmp_path: Path):
    indir = tmp_path / "in"
    indir.mkdir()
    build_basic_pdf(indir / "a.pdf")

    rc = main(["parse", str(indir)])

    assert rc == 0
    assert (tmp_path / "kb-parse-out").exists()
    assert (indir / "kb-parse-out").exists() is False
    assert any((tmp_path / "kb-parse-out").glob("*.json"))


def test_cli_batch_all_fail_writes_manifest_and_returns_1(tmp_path: Path, monkeypatch):
    indir = tmp_path / "in"
    indir.mkdir()
    build_basic_pdf(indir / "a.pdf")
    build_basic(indir / "b.docx")
    outdir = tmp_path / "out"

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("kbparser.cli.dispatch", boom)

    rc = main(["parse", str(indir), "--out", str(outdir)])

    assert rc == 1
    manifest = json.loads((outdir / "manifest.json").read_text())
    assert len(manifest["results"]) == 2
    assert all(r["status"] == "failed" for r in manifest["results"])


class _FakeStream:
    def __init__(self, encoding: str):
        self.encoding = encoding


def test_doctor_status_marker_falls_back_for_legacy_windows_encoding():
    assert _status_marker("PASS", _FakeStream("cp1252")) == "OK"
    assert _status_marker("WARN", _FakeStream("cp1252")) == "!"
    assert _status_marker("FAIL", _FakeStream("cp1252")) == "X"


def test_doctor_status_marker_keeps_symbols_for_utf8():
    assert _status_marker("PASS", _FakeStream("utf-8")) == "✓"
