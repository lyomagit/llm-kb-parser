import json
from pathlib import Path

from kbparser.mobile.facade import android_capabilities_json, parse_path_json


def test_android_capabilities_disable_desktop_only_formats():
    payload = json.loads(android_capabilities_json())

    assert payload["supported_formats"] == ["xls", "xlsx"]
    assert payload["disabled_formats"]["doc"]["reason"] == "LibreOffice is not bundled on Android"
    assert payload["disabled_formats"]["ocr"]["replacement"] == "native Android OCR bridge"


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
