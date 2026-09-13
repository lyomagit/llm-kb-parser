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
from kbparser.parsers.ocr import OCREngineError, OCRTimeout, find_tesseract
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


def test_scanned_with_ocr_timeout_emits_timeout_warning(monkeypatch, scanned_pdf: Path):
    from kbparser.parsers import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "find_tesseract", lambda: "/fake/tesseract")

    def boom(*args, **kwargs):
        raise OCRTimeout("timed out")

    monkeypatch.setattr(pdf_mod, "ocr_page", boom)
    d = _parse(scanned_pdf)
    assert d.parse.ocr_used is False
    assert any(
        w.code == "ocr_skipped_timeout"
        and (w.scope or {}).get("pages_missing_ocr") == [1]
        for w in d.warnings
    )
    validate(d)


def test_scanned_with_ocr_error_emits_error_warning(monkeypatch, scanned_pdf: Path):
    from kbparser.parsers import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "find_tesseract", lambda: "/fake/tesseract")

    def boom(*args, **kwargs):
        raise OCREngineError("ocr engine failed")

    monkeypatch.setattr(pdf_mod, "ocr_page", boom)
    d = _parse(scanned_pdf)
    assert d.parse.ocr_used is False
    assert any(
        w.code == "ocr_skipped_error"
        and (w.scope or {}).get("pages_missing_ocr") == [1]
        for w in d.warnings
    )
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


def test_text_lite_scan_reports_unextracted_page(scanned_pdf: Path):
    doc = _parse(scanned_pdf, profile="text-lite")
    assert any(w.code == "ocr_skipped_by_profile" and w.scope == {"pages_missing_ocr": [1]}
               for w in doc.warnings)


def test_ocr_does_not_duplicate_or_replace_existing_native_text(monkeypatch, tmp_path: Path):
    import fitz

    from kbparser.parsers import pdf as pdf_mod
    from kbparser.parsers.ocr import OCRResult

    path = tmp_path / "mixed.pdf"
    with fitz.open() as source:
        page = source.new_page()
        page.insert_text((50, 70), "Native title", fontsize=20)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
        pix.clear_with(255)
        page.insert_image(fitz.Rect(50, 150, 300, 300), pixmap=pix)
        source.save(path)
    monkeypatch.setattr(pdf_mod, "find_tesseract", lambda: "/fake/tesseract")
    monkeypatch.setattr(pdf_mod, "ocr_page", lambda *args, **kwargs: [
        OCRResult("NATIVE TlTLE", (50, 48, 160, 77)),
        OCRResult("Native title", (50, 48, 500, 77)),
        OCRResult("Image-only text", (50, 170, 250, 190)),
    ])
    doc = _parse(path)
    text = " ".join(b.text or "" for b in doc.blocks)
    assert "Native title" in text
    assert text.count("Native title") == 1
    assert "NATIVE TlTLE" not in text
    assert "Image-only text" in text
