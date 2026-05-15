import os
import stat
from pathlib import Path

import kbparser.runtime_tools as runtime_tools
from kbparser.runtime_tools import (
    LIBREOFFICE,
    TESSERACT,
    dependency_guidance_text,
    dependency_status_text,
    find_tool,
    missing_tesseract_languages,
    tool_status,
)


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_find_tool_prefers_explicit_env_path(tmp_path: Path, monkeypatch):
    explicit = tmp_path / "custom-tesseract"
    explicit.write_text("", encoding="utf-8")
    _make_executable(explicit)
    monkeypatch.setenv("KBPARSER_TESSERACT", str(explicit))
    monkeypatch.setenv("PATH", "")

    found = find_tool(TESSERACT)

    assert found == explicit


def test_find_tool_accepts_explicit_env_directory(tmp_path: Path, monkeypatch):
    install_dir = tmp_path / "Tesseract-OCR"
    exe = install_dir / "tesseract"
    install_dir.mkdir()
    exe.write_text("", encoding="utf-8")
    _make_executable(exe)
    monkeypatch.setenv("KBPARSER_TESSERACT", str(install_dir))
    monkeypatch.setenv("PATH", "")

    found = find_tool(TESSERACT)

    assert found == exe


def test_find_tool_checks_user_tools_root(tmp_path: Path, monkeypatch):
    soffice = tmp_path / "LibreOffice" / "program" / "soffice"
    soffice.parent.mkdir(parents=True)
    soffice.write_text("", encoding="utf-8")
    _make_executable(soffice)
    monkeypatch.delenv("KBPARSER_LIBREOFFICE", raising=False)
    monkeypatch.setenv("KBPARSER_TOOLS_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", "")

    found = find_tool(LIBREOFFICE)

    assert found == soffice


def test_find_tool_accepts_explicit_libreoffice_app_directory(tmp_path: Path, monkeypatch):
    soffice = tmp_path / "LibreOffice.app" / "Contents" / "MacOS" / "soffice"
    soffice.parent.mkdir(parents=True)
    soffice.write_text("", encoding="utf-8")
    _make_executable(soffice)
    monkeypatch.setenv("KBPARSER_LIBREOFFICE", str(tmp_path / "LibreOffice.app"))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(runtime_tools, "configured_tool_roots", lambda: [])
    monkeypatch.setattr(runtime_tools, "_common_absolute_candidates", lambda spec: [])

    found = find_tool(LIBREOFFICE)

    assert found == soffice


def test_tool_status_warns_for_non_runnable_explicit_file(tmp_path: Path, monkeypatch):
    explicit = tmp_path / "not-runnable-tesseract"
    explicit.write_text("", encoding="utf-8")
    monkeypatch.setenv("KBPARSER_TESSERACT", str(explicit))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(runtime_tools, "configured_tool_roots", lambda: [])
    monkeypatch.setattr(runtime_tools, "_common_absolute_candidates", lambda spec: [])

    status = tool_status(TESSERACT)

    assert status.status == "WARN"
    assert status.version is None


def test_dependency_status_does_not_pass_languages_when_tesseract_is_not_runnable(tmp_path: Path, monkeypatch):
    explicit = tmp_path / "not-runnable-tesseract"
    explicit.write_text("", encoding="utf-8")
    monkeypatch.setenv("KBPARSER_TESSERACT", str(explicit))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(runtime_tools, "configured_tool_roots", lambda: [])
    monkeypatch.setattr(runtime_tools, "_common_absolute_candidates", lambda spec: [])

    text = dependency_status_text("rus+eng")

    assert "Tesseract OCR: WARN" in text
    assert "Tesseract languages: PASS" not in text


def test_missing_tesseract_languages_uses_sidecar_tessdata(tmp_path: Path, monkeypatch):
    tesseract = tmp_path / "Tesseract-OCR" / "tesseract"
    tessdata = tmp_path / "Tesseract-OCR" / "tessdata"
    tessdata.mkdir(parents=True)
    tesseract.write_text("", encoding="utf-8")
    _make_executable(tesseract)
    monkeypatch.setenv("KBPARSER_TOOLS_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("KBPARSER_TESSERACT", raising=False)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)

    def fake_run(args, **kwargs):
        env = kwargs.get("env") or os.environ
        text = "List of available languages (2):\neng\nrus\n" if env.get("TESSDATA_PREFIX") == str(tessdata) else "List of available languages (1):\neng\n"
        return type("Result", (), {"returncode": 0, "stdout": text, "stderr": ""})()

    monkeypatch.setattr(runtime_tools.subprocess, "run", fake_run)

    assert missing_tesseract_languages("rus+eng") == []


def test_dependency_guidance_names_versions_and_bundle_locations():
    text = dependency_guidance_text()

    assert "LibreOffice" in text
    assert "Tesseract" in text
    assert "KBPARSER_TOOLS_DIR" in text
    assert "KBPARSER_LIBREOFFICE" in text
    assert "KBPARSER_TESSERACT" in text
    assert "tools/" in text
