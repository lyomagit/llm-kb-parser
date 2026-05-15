from pathlib import Path

from kbparser.runtime_tools import (
    LIBREOFFICE,
    TESSERACT,
    dependency_guidance_text,
    find_tool,
)


def test_find_tool_prefers_explicit_env_path(tmp_path: Path, monkeypatch):
    explicit = tmp_path / "custom-tesseract"
    explicit.write_text("", encoding="utf-8")
    monkeypatch.setenv("KBPARSER_TESSERACT", str(explicit))
    monkeypatch.setenv("PATH", "")

    found = find_tool(TESSERACT)

    assert found == explicit


def test_find_tool_accepts_explicit_env_directory(tmp_path: Path, monkeypatch):
    install_dir = tmp_path / "Tesseract-OCR"
    exe = install_dir / "tesseract"
    install_dir.mkdir()
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("KBPARSER_TESSERACT", str(install_dir))
    monkeypatch.setenv("PATH", "")

    found = find_tool(TESSERACT)

    assert found == exe


def test_find_tool_checks_user_tools_root(tmp_path: Path, monkeypatch):
    soffice = tmp_path / "LibreOffice" / "program" / "soffice"
    soffice.parent.mkdir(parents=True)
    soffice.write_text("", encoding="utf-8")
    monkeypatch.delenv("KBPARSER_LIBREOFFICE", raising=False)
    monkeypatch.setenv("KBPARSER_TOOLS_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", "")

    found = find_tool(LIBREOFFICE)

    assert found == soffice


def test_dependency_guidance_names_versions_and_bundle_locations():
    text = dependency_guidance_text()

    assert "LibreOffice" in text
    assert "Tesseract" in text
    assert "KBPARSER_TOOLS_DIR" in text
    assert "KBPARSER_LIBREOFFICE" in text
    assert "KBPARSER_TESSERACT" in text
    assert "tools/" in text
