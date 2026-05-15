from pathlib import Path

from kbparser.gui import build_parse_args, setup_tools_text


def test_build_parse_args_includes_selected_options(tmp_path: Path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "out"

    args = build_parse_args(
        source=source,
        output_dir=output,
        profile="balanced",
        ocr_langs="rus+eng",
        overwrite=True,
    )

    assert args == [
        "parse",
        str(source),
        "--out",
        str(output),
        "--profile",
        "balanced",
        "--lang",
        "rus+eng",
        "--overwrite",
    ]


def test_build_parse_args_omits_empty_optional_values(tmp_path: Path):
    source = tmp_path / "source.docx"

    args = build_parse_args(
        source=source,
        output_dir=None,
        profile="fidelity",
        ocr_langs="",
        overwrite=False,
    )

    assert args == ["parse", str(source), "--profile", "fidelity"]


def test_setup_tools_text_includes_status_and_tools_folder(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("kbparser.gui.app_tools_dir", lambda: tmp_path / "tools")
    monkeypatch.setattr("kbparser.gui.dependency_status_text", lambda: "Current status\nLibreOffice: PASS\nTesseract OCR: WARN")

    text = setup_tools_text()

    assert "Current status" in text
    assert "LibreOffice: PASS" in text
    assert "Tesseract OCR: WARN" in text
    assert str(tmp_path / "tools") in text
