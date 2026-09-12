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
RTF_BYTES = b"{\\rtf1\\ansi\\deff0 text}"


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


def test_detect_doc_allows_rtf_payload_for_libreoffice(tmp_path: Path):
    p = _write(tmp_path / "renamed-rtf.doc", RTF_BYTES)

    assert detect_format(p) == "doc"


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
    assert (outdir / "sample.pdf.md").exists()


def test_cli_parse_markdown_only(tmp_path: Path):
    infile = build_basic_pdf(tmp_path / "sample.pdf")
    outdir = tmp_path / "out"

    rc = main(["parse", str(infile), "--out", str(outdir), "--format", "md"])

    assert rc == 0
    assert not (outdir / "sample.pdf.json").exists()
    markdown = outdir / "sample.pdf.md"
    assert markdown.exists()
    assert markdown.read_text(encoding="utf-8").startswith("# sample.pdf\n")


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


def test_repeat_parse_reuses_verified_output_without_parsing(tmp_path: Path, monkeypatch, capsys):
    source = build_basic(tmp_path / "source.docx")
    args = ["parse", str(source), "--out", str(tmp_path / "out")]
    assert main(args) == 0
    def unexpected_parse(*args, **kwargs):
        raise AssertionError("unchanged document was parsed again")
    monkeypatch.setattr("kbparser.cli.dispatch", unexpected_parse)
    assert main(args) == 0
    assert "[skipped]" in capsys.readouterr().out


@pytest.mark.parametrize("output_format", ["json", "md", "both"])
def test_separate_runs_do_not_confuse_same_named_files(tmp_path: Path, output_format: str):
    from docx import Document as DocxDoc
    output = tmp_path / "out"
    for directory, marker in [("one", "FIRST_SOURCE"), ("two", "SECOND_SOURCE")]:
        parent = tmp_path / directory
        parent.mkdir()
        doc = DocxDoc()
        doc.add_paragraph(marker)
        source = parent / "same.docx"
        doc.save(source)
        assert main(["parse", str(source), "--out", str(output), "--format", output_format]) == 0
    extension = "*.md" if output_format == "md" else "*.json"
    files = list(output.glob(extension))
    assert len(files) == 2
    for marker in ["FIRST_SOURCE", "SECOND_SOURCE"]:
        assert sum(marker in path.read_text() for path in files) == 1


def test_corrupt_output_is_preserved_and_rebuilt_at_new_path(tmp_path: Path):
    source = build_basic(tmp_path / "source.docx")
    output = tmp_path / "out"
    output.mkdir()
    old = output / "source.docx.json"
    old.write_text('{"interrupted":')
    assert main(["parse", str(source), "--out", str(output), "--format", "json"]) == 0
    assert old.read_text() == '{"interrupted":'
    fresh = [p for p in output.glob("*.json") if p != old]
    assert len(fresh) == 1
    assert json.loads(fresh[0].read_text())["document"]["source"]["sha256"]


def test_different_profile_is_not_skipped(tmp_path: Path):
    source = build_basic(tmp_path / "source.docx")
    output = tmp_path / "out"
    for profile in ["fidelity", "text-lite"]:
        assert main(["parse", str(source), "--out", str(output), "--profile", profile]) == 0
    assert {json.loads(p.read_text())["document"]["parse"]["profile"]
            for p in output.glob("*.json")} == {"fidelity", "text-lite"}


def test_empty_scan_is_not_reported_as_success(tmp_path: Path, capsys):
    source = Path(__file__).parents[1] / "fixtures/pdf/scanned.pdf"
    assert main(["parse", str(source), "--out", str(tmp_path), "--profile", "text-lite"]) == 0
    assert "[partial]" in capsys.readouterr().out
    data = json.loads((tmp_path / "scanned.pdf.json").read_text())
    assert any(w["code"] == "empty_extraction" for w in data["document"]["warnings"])


def test_batch_progress_and_cancellation_preserve_finished_outputs(tmp_path: Path):
    source = tmp_path / "input"
    source.mkdir()
    build_basic(source / "a.docx")
    build_basic(source / "b.docx")
    events = []
    def cancelled():
        return any(e["status"] in {"success", "partial"} for e in events)
    rc = main(["parse", str(source), "--out", str(tmp_path / "out")],
              cancelled=cancelled, progress=events.append)
    assert rc == 130
    assert [e["status"] for e in events] == ["processing", "success", "cancelled"]
    assert (tmp_path / "out/a.docx.json").exists()
    assert not (tmp_path / "out/b.docx.json").exists()
    manifest = json.loads((tmp_path / "out/manifest.json").read_text())
    assert [r["status"] for r in manifest["results"]] == ["success", "cancelled"]


@pytest.mark.parametrize("output_format", ["both", "md"])
def test_cached_partial_result_keeps_warning_status(tmp_path: Path, capsys, output_format: str):
    source = Path(__file__).parents[1] / "fixtures/pdf/scanned.pdf"
    args = ["parse", str(source), "--out", str(tmp_path), "--profile", "text-lite", "--format", output_format]
    assert main(args) == 0
    capsys.readouterr()
    events = []
    assert main(args, progress=events.append) == 0
    assert events[-1]["status"] == "partial"
    assert "empty_extraction" in events[-1]["warning_codes"]
