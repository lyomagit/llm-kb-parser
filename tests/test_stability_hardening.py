from kbparser import __version__
from kbparser.export import to_output
from kbparser.model import Document, Parse, Source
from kbparser.parsers.base import ParseContext, build_source_and_parse
from kbparser.parsers.doc import DOCParser
from kbparser.parsers.docx import DOCXParser
from kbparser.parsers.excel import ExcelParser
from kbparser.parsers.pdf import PDFParser
from kbparser.versioning import PACKAGE_VERSION, RECORDS_VERSION, SCHEMA_VERSION

from .fixtures_gen.build_docx import build_basic as build_docx


def test_build_source_and_parse_keeps_finished_at_equal_to_started_at_until_finalize(tmp_path):
    sample = tmp_path / "sample.docx"
    sample.write_bytes(b"PK\x03\x04" + b"0" * 128)
    ctx = ParseContext(path=sample, profile="fidelity")

    _, parse, _ = build_source_and_parse(
        ctx,
        "docx",
        "docx",
        PACKAGE_VERSION,
        started_at="2026-04-14T00:00:00+00:00",
    )

    assert parse.started_at == "2026-04-14T00:00:00+00:00"
    assert parse.finished_at == "2026-04-14T00:00:00+00:00"



def test_docx_parser_finalizes_parse_metadata(tmp_path):
    docx_path = build_docx(tmp_path / "sample.docx")
    doc = DOCXParser().parse(ParseContext(path=docx_path, profile="fidelity"))

    assert doc.parse.started_at
    assert doc.parse.finished_at
    assert doc.parse.finished_at >= doc.parse.started_at
    assert doc.parse.parser_version == PACKAGE_VERSION





def _doc() -> Document:
    src = Source(
        path="/tmp/sample.pdf",
        filename="sample.pdf",
        format="pdf",
        mime_type="application/pdf",
        sha256="0" * 64,
        size_bytes=1,
        modified_at="2026-04-14T00:00:00+00:00",
    )
    parse = Parse(
        parser="pdf",
        parser_version=PACKAGE_VERSION,
        started_at="2026-04-14T00:00:00+00:00",
        finished_at="2026-04-14T00:00:00+00:00",
    )
    return Document(id="doc_sample", source=src, metadata={}, parse=parse)


def test_parser_versions_match_package_version():
    assert __version__ == PACKAGE_VERSION
    assert DOCParser.version == PACKAGE_VERSION
    assert DOCXParser.version == PACKAGE_VERSION
    assert ExcelParser.version == PACKAGE_VERSION
    assert PDFParser.version == PACKAGE_VERSION


def test_to_output_uses_shared_version_constants():
    out = to_output(_doc())
    assert out.parser_version == PACKAGE_VERSION
    assert out.schema_version == SCHEMA_VERSION
    assert out.records_version == RECORDS_VERSION
