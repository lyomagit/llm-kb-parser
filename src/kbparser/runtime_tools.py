"""Discovery and setup guidance for external desktop tools."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolSpec:
    key: str
    label: str
    env_var: str
    executable_names: tuple[str, ...]
    relative_paths: tuple[str, ...]
    minimum_version: str
    recommended_version: str
    mac_install: str
    linux_install: str
    windows_install: str
    download_url: str


@dataclass(frozen=True)
class ToolStatus:
    spec: ToolSpec
    path: Path | None
    status: str
    detail: str
    version: str | None = None


LIBREOFFICE = ToolSpec(
    key="libreoffice",
    label="LibreOffice",
    env_var="KBPARSER_LIBREOFFICE",
    executable_names=("soffice", "libreoffice", "soffice.exe", "libreoffice.exe"),
    relative_paths=(
        "LibreOffice.app/Contents/MacOS/soffice",
        "LibreOffice/program/soffice.exe",
        "LibreOffice/program/soffice",
        "libreoffice/program/soffice.exe",
        "program/soffice.exe",
        "program/soffice",
        "soffice",
        "soffice.exe",
    ),
    minimum_version="7.6+",
    recommended_version="26.2.x stable or 25.8.x still",
    mac_install="brew install --cask libreoffice",
    linux_install="sudo apt install libreoffice",
    windows_install="Download LibreOffice Windows x86-64 stable from libreoffice.org",
    download_url="https://www.libreoffice.org/download/download-libreoffice/",
)

TESSERACT = ToolSpec(
    key="tesseract",
    label="Tesseract OCR",
    env_var="KBPARSER_TESSERACT",
    executable_names=("tesseract", "tesseract.exe"),
    relative_paths=(
        "Tesseract-OCR/tesseract.exe",
        "Tesseract-OCR/tesseract",
        "tesseract/bin/tesseract",
        "tesseract/tesseract.exe",
        "bin/tesseract",
        "tesseract",
        "tesseract.exe",
    ),
    minimum_version="5.0+",
    recommended_version="5.5.x",
    mac_install="brew install tesseract tesseract-lang",
    linux_install="sudo apt install tesseract-ocr tesseract-ocr-all",
    windows_install="Download the UB Mannheim 64-bit Tesseract installer",
    download_url="https://github.com/UB-Mannheim/tesseract/wiki",
)

TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata"


def platform_key() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"


def app_tools_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "KBParser" / "tools"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "KBParser" / "tools"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "kbparser" / "tools"


def executable_sidecar_roots() -> list[Path]:
    roots: list[Path] = []
    executable = Path(getattr(sys, "executable", "") or "")
    if executable:
        for parent in [executable.parent, *executable.parents]:
            roots.append(parent / "tools")
            if parent.name.endswith(".app"):
                roots.append(parent / "Contents" / "Resources" / "tools")
                roots.append(parent / "Contents" / "Tools")
    module_root = Path(__file__).resolve().parents[2]
    roots.append(module_root / "tools")
    return _dedupe_paths(roots)


def configured_tool_roots() -> list[Path]:
    roots: list[Path] = []
    raw = os.environ.get("KBPARSER_TOOLS_DIR")
    if raw:
        roots.extend(Path(part).expanduser() for part in raw.split(os.pathsep) if part)
    roots.append(app_tools_dir())
    roots.extend(executable_sidecar_roots())
    return _dedupe_paths(roots)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path.expanduser())
        if key in seen:
            continue
        seen.add(key)
        out.append(path.expanduser())
    return out


def _resolve_candidate(candidate: str | Path) -> Path | None:
    raw = Path(candidate).expanduser()
    if raw.is_file():
        return raw
    if len(raw.parts) == 1:
        resolved = shutil.which(str(raw))
        if resolved:
            return Path(resolved)
    return None


def _common_absolute_candidates(spec: ToolSpec) -> list[Path]:
    if spec is LIBREOFFICE:
        if sys.platform == "darwin":
            return [
                Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
                Path("/opt/homebrew/bin/soffice"),
                Path("/usr/local/bin/soffice"),
                Path("/usr/bin/libreoffice"),
            ]
        if sys.platform == "win32":
            roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
            return [
                Path(root) / "LibreOffice" / "program" / "soffice.exe"
                for root in roots
                if root
            ]
        return [Path("/usr/bin/libreoffice"), Path("/usr/bin/soffice"), Path("/usr/local/bin/soffice")]

    if sys.platform == "win32":
        roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
        return [
            Path(root) / "Tesseract-OCR" / "tesseract.exe"
            for root in roots
            if root
        ]
    return [Path("/opt/homebrew/bin/tesseract"), Path("/usr/local/bin/tesseract"), Path("/usr/bin/tesseract")]


def find_tool(spec: ToolSpec) -> Path | None:
    explicit = os.environ.get(spec.env_var)
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if explicit_path.is_dir():
            for rel in spec.relative_paths:
                found = _resolve_candidate(explicit_path / rel)
                if found:
                    return found
            for name in spec.executable_names:
                found = _resolve_candidate(explicit_path / name)
                if found:
                    return found
        else:
            found = _resolve_candidate(explicit_path)
            if found:
                return found

    for root in configured_tool_roots():
        for rel in spec.relative_paths:
            found = _resolve_candidate(root / rel)
            if found:
                return found

    for candidate in _common_absolute_candidates(spec):
        found = _resolve_candidate(candidate)
        if found:
            return found

    for name in spec.executable_names:
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved)

    return None


def tool_version(path: Path) -> str | None:
    try:
        out = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return None
    text = (out.stdout or out.stderr or "").strip()
    return text.splitlines()[0] if text else None


def tool_status(spec: ToolSpec) -> ToolStatus:
    path = find_tool(spec)
    if path is None:
        return ToolStatus(
            spec=spec,
            path=None,
            status="WARN",
            detail=f"not found; needs {spec.label} {spec.minimum_version}. {install_summary(spec)}",
        )
    version = tool_version(path)
    detail = str(path)
    if version:
        detail += f" ({version})"
    return ToolStatus(spec=spec, path=path, status="PASS", detail=detail, version=version)


def tesseract_languages(tesseract_bin: Path | None = None) -> list[str]:
    bin_path = tesseract_bin or find_tool(TESSERACT)
    if bin_path is None:
        return []
    try:
        out = subprocess.run(
            [str(bin_path), "--list-langs"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return []
    return [line.strip() for line in (out.stdout or out.stderr or "").splitlines()[1:] if line.strip()]


def missing_tesseract_languages(required: str) -> list[str]:
    langs = {lang.strip() for lang in required.split("+") if lang.strip()}
    available = set(tesseract_languages())
    if not langs or not available:
        return []
    return sorted(lang for lang in langs if lang not in available)


def find_tessdata_dir(tesseract_bin: Path | None = None) -> Path | None:
    raw = os.environ.get("TESSDATA_PREFIX")
    if raw and Path(raw).expanduser().is_dir():
        return Path(raw).expanduser()
    for root in configured_tool_roots():
        for rel in (
            "tessdata",
            "Tesseract-OCR/tessdata",
            "tesseract/tessdata",
            "tesseract/share/tessdata",
            "share/tessdata",
        ):
            candidate = root / rel
            if candidate.is_dir():
                return candidate
    if tesseract_bin is not None:
        for candidate in (
            tesseract_bin.parent / "tessdata",
            tesseract_bin.parent.parent / "share" / "tessdata",
        ):
            if candidate.is_dir():
                return candidate
    return None


def install_summary(spec: ToolSpec) -> str:
    key = platform_key()
    if key == "macos":
        return spec.mac_install
    if key == "windows":
        return spec.windows_install
    return spec.linux_install


def dependency_download_links() -> list[tuple[str, str]]:
    return [
        ("LibreOffice download", LIBREOFFICE.download_url),
        ("Tesseract Windows installer", TESSERACT.download_url),
        ("Tesseract language data", TESSDATA_URL),
    ]


def dependency_guidance_text() -> str:
    tools_root = app_tools_dir()
    return "\n".join(
        [
            "External tools setup",
            "",
            f"LibreOffice: required for legacy .doc parsing. Minimum {LIBREOFFICE.minimum_version}; recommended {LIBREOFFICE.recommended_version}.",
            f"Tesseract OCR: required for scanned PDF OCR. Minimum {TESSERACT.minimum_version}; recommended {TESSERACT.recommended_version}.",
            "",
            "Install options:",
            f"- macOS: {LIBREOFFICE.mac_install}; {TESSERACT.mac_install}",
            f"- Windows: {LIBREOFFICE.windows_install}; {TESSERACT.windows_install}",
            f"- Linux: {LIBREOFFICE.linux_install}; {TESSERACT.linux_install}",
            "",
            "Portable sidecar layout:",
            "- Put tools next to the app under tools/ or set KBPARSER_TOOLS_DIR.",
            "- LibreOffice examples: tools/LibreOffice/program/soffice.exe or tools/LibreOffice.app/Contents/MacOS/soffice.",
            "- Tesseract examples: tools/Tesseract-OCR/tesseract.exe plus tools/Tesseract-OCR/tessdata/ for language files.",
            "",
            "Explicit overrides:",
            f"- {LIBREOFFICE.env_var}=path/to/soffice",
            f"- {TESSERACT.env_var}=path/to/tesseract",
            "- TESSDATA_PREFIX=path/to/tessdata",
            f"- User tools folder: {tools_root}",
            "",
            "Download pages:",
            f"- LibreOffice: {LIBREOFFICE.download_url}",
            f"- Tesseract: {TESSERACT.download_url}",
            f"- Tesseract language data: {TESSDATA_URL}",
        ]
    )
