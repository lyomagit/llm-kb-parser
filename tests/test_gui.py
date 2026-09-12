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
        output_format="md",
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
        "--format",
        "md",
        "--overwrite",
    ]


def test_build_parse_args_omits_empty_optional_values(tmp_path: Path):
    source = tmp_path / "source.docx"

    args = build_parse_args(
        source=source,
        output_dir=None,
        profile="fidelity",
        ocr_langs="",
        output_format="both",
        overwrite=False,
    )

    assert args == ["parse", str(source), "--profile", "fidelity", "--format", "both"]


def test_setup_tools_text_includes_status_and_tools_folder(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("kbparser.gui.app_tools_dir", lambda: tmp_path / "tools")
    monkeypatch.setattr("kbparser.gui.dependency_status_text", lambda: "Current status\nLibreOffice: PASS\nTesseract OCR: WARN")

    text = setup_tools_text()

    assert "Current status" in text
    assert "LibreOffice: PASS" in text
    assert "Tesseract OCR: WARN" in text
    assert str(tmp_path / "tools") in text


def test_gui_worker_emits_live_file_events_and_completion(tmp_path: Path):
    import queue
    import threading

    from kbparser.gui import KBParserApp

    from .fixtures_gen.build_docx import build_basic

    source = build_basic(tmp_path / "source.docx")
    app = KBParserApp.__new__(KBParserApp)
    app.queue = queue.Queue()
    app.cancel_event = threading.Event()
    app.run_cli(["parse", str(source), "--out", str(tmp_path / "out")], tmp_path / "out")
    events = list(app.queue.queue)
    assert any(kind == "file" and data["status"] == "processing" for kind, data in events)
    assert any(kind == "log" and "[success]" in data for kind, data in events)
    assert events[-1][0] == "done"
    assert events[-1][1]["code"] == 0


def test_gui_cancelled_worker_completes_without_writing_document(tmp_path: Path):
    import queue
    import threading

    from kbparser.gui import KBParserApp

    from .fixtures_gen.build_docx import build_basic

    source = build_basic(tmp_path / "source.docx")
    app = KBParserApp.__new__(KBParserApp)
    app.queue = queue.Queue()
    app.cancel_event = threading.Event()
    app.cancel_event.set()
    app.run_cli(["parse", str(source), "--out", str(tmp_path / "out")], tmp_path / "out")
    assert list(app.queue.queue)[-1] == ("done", {"code": 130, "output_dir": tmp_path / "out"})
    assert not (tmp_path / "out/source.docx.json").exists()
