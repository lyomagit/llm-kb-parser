import pytest
from pydantic import ValidationError as PydanticError

from kbparser.model import Document, Parse, Source


def _src() -> Source:
    return Source(
        path="/tmp/x.pdf",
        filename="x.pdf",
        format="pdf",
        mime_type="application/pdf",
        sha256="0" * 64,
        size_bytes=1,
        modified_at="2026-04-13T00:00:00+00:00",
    )


def _parse() -> Parse:
    return Parse(
        parser="t",
        parser_version="0",
        started_at="2026-04-13T00:00:00+00:00",
        finished_at="2026-04-13T00:00:01+00:00",
    )


def test_minimal_doc_ok():
    d = Document(id="doc_x", source=_src(), parse=_parse())
    assert d.id == "doc_x"
    assert d.warnings == []


def test_warning_accepts_ocr_skipped_codes():
    d = Document(
        id="doc_x",
        source=_src(),
        parse=_parse(),
        warnings=[
            {"code": "ocr_skipped_missing_binary", "message": "missing tesseract", "scope": {"pages_missing_ocr": [1]}},
            {"code": "ocr_skipped_empty_result", "message": "empty ocr", "scope": {"pages_missing_ocr": [2]}},
        ],
    )
    assert [w.code for w in d.warnings] == ["ocr_skipped_missing_binary", "ocr_skipped_empty_result"]


def test_extra_fields_forbidden():
    with pytest.raises(PydanticError):
        Document(id="doc_x", source=_src(), parse=_parse(), nope=1)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "code",
    ["ocr_skipped_missing_binary", "ocr_skipped_empty_result"],
)
def test_warning_model_accepts_new_codes(code: str):
    from kbparser.model import Warning

    w = Warning(code=code, message="x")
    assert w.code == code


@pytest.mark.parametrize(
    "record_type",
    ["reference_chunk", "diagram_chunk"],
)
def test_record_model_accepts_new_chunk_types(record_type: str):
    from kbparser.model import Record

    r = Record(
        id="rec_1",
        type=record_type,
        document_id="doc_x",
        text="sample",
        source_node_ids=["sec_1"],
    )
    assert r.type == record_type
