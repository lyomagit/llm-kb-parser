import pytest

from kbparser.model import Block, Document, Parse, Section, Source
from kbparser.validation import ValidationError, validate


def _doc(**kw) -> Document:
    src = Source(
        path="/tmp/x.pdf",
        filename="x.pdf",
        format="pdf",
        mime_type="application/pdf",
        sha256="0" * 64,
        size_bytes=1,
        modified_at="2026-04-13T00:00:00+00:00",
    )
    parse = Parse(
        parser="t",
        parser_version="0",
        started_at="2026-04-13T00:00:00+00:00",
        finished_at="2026-04-13T00:00:01+00:00",
    )
    return Document(id="doc_x", source=src, parse=parse, **kw)


def test_empty_doc_validates():
    validate(_doc())


def test_block_missing_section_fails():
    doc = _doc(blocks=[Block(id="blk_1", type="paragraph", section_id="sec_missing")])
    with pytest.raises(ValidationError):
        validate(doc)


def test_section_cycle_fails():
    sections = [
        Section(id="sec_a", parent_id="sec_b"),
        Section(id="sec_b", parent_id="sec_a"),
    ]
    doc = _doc(sections=sections)
    with pytest.raises(ValidationError):
        validate(doc)


def test_section_block_ref_ok():
    section = Section(id="sec_a", block_ids=["blk_1"])
    block = Block(id="blk_1", type="paragraph", section_id="sec_a", order=0)
    validate(_doc(sections=[section], blocks=[block]))
