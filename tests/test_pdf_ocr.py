"""Tests for OCR branch of PDFParser.

When tesseract is absent: parser produces a `pages_missing_ocr` warning and
completes without failure.

When tesseract is present: OCR runs and recovers body text from the scanned
fixture; `parse.ocr_used` is True; warning `ocr_applied_to_pages` emitted.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kbparser.parsers.base import ParseContext
from kbparser.parsers.ocr import find_tesseract
from kbparser.parsers.pdf import PDFParser
from kbparser.validation import validate

from .fixtures_gen.build_scanned_pdf import build_basic as build_scanned


TESSERACT = find_tesseract()


@pytest.fixture(scope="module")
def scanned_pdf(tmp_path_factory) -> Path:
    return build_scanned(tmp_path_factory.mktemp("scanned") / "scanned.pdf")


def _parse(path: Path, profile: str = "fidelity"):
    return PDFParser().parse(ParseContext(path=path, profile=profile))


def test_scanned_without_tesseract_emits_skipped_warning(monkeypatch, scanned_pdf: Path):
    from kbparser.parsers import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "find_tesseract", lambda: None)
    d = _parse(scanned_pdf)
    assert d.parse.ocr_used is False
    assert any(
        w.code == "ocr_skipped_missing_binary"
        and (w.scope or {}).get("pages_missing_ocr") == [1]
        for w in d.warnings
    )
    assert not any(w.code == "ocr_applied_to_pages" for w in d.warnings)
    validate(d)


@pytest.mark.skipif(TESSERACT is None, reason="tesseract not installed")
def test_scanned_with_tesseract_recovers_text(scanned_pdf: Path):
    d = _parse(scanned_pdf)
    assert d.parse.ocr_used is True
    assert any(
        w.code == "ocr_applied_to_pages"
        and (w.scope or {}).get("pages") == [1]
        for w in d.warnings
    )
    joined = " ".join((b.text or "") for b in d.blocks).lower()
    # Tesseract should recover at least part of known strings.
    assert "scanned" in joined or "document" in joined
    assert len(d.blocks) >= 1
    validate(d)


def test_scanned_with_empty_ocr_result_emits_skipped_warning(monkeypatch, scanned_pdf: Path):
    from kbparser.parsers import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "find_tesseract", lambda: "/fake/tesseract")
    monkeypatch.setattr(pdf_mod, "ocr_page", lambda *args, **kwargs: [])
    d = _parse(scanned_pdf)
    assert d.parse.ocr_used is False
    assert any(
        w.code == "ocr_skipped_empty_result"
        and (w.scope or {}).get("pages_missing_ocr") == [1]
        for w in d.warnings
    )
    assert not any(w.code == "ocr_applied_to_pages" for w in d.warnings)
    validate(d)


@pytest.mark.skipif(TESSERACT is None, reason="tesseract not installed")
def test_text_lite_profile_skips_ocr(scanned_pdf: Path):
    d = _parse(scanned_pdf, profile="text-lite")
    assert d.parse.ocr_used is False
    # text-lite intentionally does not OCR; no warning about applied OCR.
    assert not any(
        w.code == "ocr_applied_to_pages"
        and (w.scope or {}).get("pages")
        for w in d.warnings
    )
