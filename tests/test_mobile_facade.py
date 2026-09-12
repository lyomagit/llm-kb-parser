import json
from pathlib import Path

from kbparser.mobile.facade import android_capabilities_json, parse_path_json, parse_path_markdown


def test_android_capabilities_disable_desktop_only_formats():
    payload = json.loads(android_capabilities_json())

    assert payload["supported_formats"] == ["xls", "xlsx"]
    assert payload["disabled_formats"]["doc"]["reason"] == "LibreOffice is provided by the Android office companion"
    assert payload["disabled_formats"]["ocr"]["replacement"] == "native Android OCR bridge"


def test_android_capabilities_advertise_external_office_engine():
    payload = json.loads(android_capabilities_json())

    assert payload["external_engines"]["office"]["package"] == "com.lyomagit.kbparser.officeengine"
    assert payload["external_engines"]["office"]["source"] == "CollaboraOnline/online fork"
    assert payload["external_engines"]["office"]["contract_action"] == "com.lyomagit.kbparser.officeengine.CONVERT"
    assert payload["disabled_formats"]["doc"]["replacement"] == "Android office companion conversion"
    assert payload["disabled_formats"]["docx"]["replacement"] == "Android office companion conversion"
    assert payload["disabled_formats"]["pdf"]["replacement"] == "Android office companion conversion"


def test_parse_path_json_rejects_doc_on_android(tmp_path: Path):
    doc = tmp_path / "legacy.doc"
    doc.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")

    payload = json.loads(parse_path_json(str(doc)))

    assert payload["status"] == "unsupported"
    assert payload["format"] == "doc"
    assert "LibreOffice" in payload["message"]


def test_parse_path_json_parses_xlsx_fixture():
    fixture = Path("fixtures/xlsx/basic.xlsx")

    payload = json.loads(parse_path_json(str(fixture), profile="balanced"))

    assert payload["status"] == "success"
    assert payload["format"] == "xlsx"
    assert payload["source"]["filename"] == "basic.xlsx"
    assert payload["backend"] == "mobile-lightweight-excel"
    assert payload["sheets"]
    assert payload["records"]


def test_parse_path_markdown_renders_xlsx_fixture():
    fixture = Path("fixtures/xlsx/basic.xlsx")

    markdown = parse_path_markdown(str(fixture), profile="balanced")

    assert markdown.startswith("# basic.xlsx\n")
    assert "Format: `xlsx`" in markdown
    assert "Backend: `mobile-lightweight-excel`" in markdown
    assert "## Sheet: Sales" in markdown
    assert "| Row |" in markdown


def test_converted_mobile_parse_keeps_original_source_metadata():
    fixture = Path("fixtures/xlsx/basic.xlsx")

    payload = json.loads(
        parse_path_json(
            str(fixture),
            profile="balanced",
            original_source_name="legacy.doc",
            original_source_format="doc",
        )
    )

    assert payload["source"]["filename"] == "legacy.doc"
    assert payload["source"]["original_format"] == "doc"
    assert payload["source"]["converted_filename"] == "basic.xlsx"

    markdown = parse_path_markdown(
        str(fixture),
        profile="balanced",
        original_source_name="legacy.doc",
        original_source_format="doc",
    )
    assert markdown.startswith("# legacy.doc\n")
