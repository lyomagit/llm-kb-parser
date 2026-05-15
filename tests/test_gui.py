from pathlib import Path

from kbparser.gui import build_parse_args


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
