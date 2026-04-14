import json
from pathlib import Path

from kbparser import __version__
from kbparser.cli import main
from kbparser.versioning import RECORDS_VERSION, SCHEMA_VERSION

from .fixtures_gen.build_docx import build_basic as build_docx
from .fixtures_gen.build_pdf import build_basic as build_pdf
from .fixtures_gen.build_xlsx import build_basic as build_xlsx


def test_batch_manifest_uses_shared_versions(tmp_path: Path):
    indir = tmp_path / "in"
    indir.mkdir()
    build_pdf(indir / "a.pdf")
    build_docx(indir / "b.docx")
    build_xlsx(indir / "c.xlsx")
    outdir = tmp_path / "out"

    rc = main(["parse", str(indir), "--out", str(outdir)])
    assert rc == 0

    manifest = json.loads((outdir / "manifest.json").read_text())
    assert manifest["kbparser_version"] == __version__
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["records_version"] == RECORDS_VERSION

    results = {Path(r["file"]).name: r for r in manifest["results"]}
    assert set(results) == {"a.pdf", "b.docx", "c.xlsx"}
    assert all(r["status"] in {"success", "partial"} for r in results.values())
    assert all(r["status"] != "failed" for r in results.values())
    assert results["a.pdf"]["warning_codes"] == ["header_footer_filtered_heuristically"]
    assert results["b.docx"]["warning_codes"] == []
    assert results["c.xlsx"]["warning_codes"] == ["formula_not_evaluated"]



def test_single_file_output_uses_shared_versions(tmp_path: Path):
    infile = build_pdf(tmp_path / "sample.pdf")
    outdir = tmp_path / "out"

    rc = main(["parse", str(infile), "--out", str(outdir)])
    assert rc == 0

    payload = json.loads(next(outdir.glob("*.json")).read_text())
    assert payload["parser_version"] == __version__
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["records_version"] == RECORDS_VERSION



def test_makefile_exposes_smoke_target():
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    assert "\nsmoke:\n" in makefile
