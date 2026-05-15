from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = Path(os.environ.get("KBPARSER_DIST_ROOT", ROOT / "dist" / "apps")).resolve()
CLI_DIST = DIST_ROOT / "cli"
GUI_DIST = DIST_ROOT / "gui"
WORK_ROOT = ROOT / "build" / "pyinstaller"


def run(args: list[str]) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def pyinstaller_base(*, dist: Path, work: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--paths",
        str(ROOT / "src"),
        "--collect-submodules",
        "pydantic",
        "--collect-submodules",
        "pdfminer",
        "--collect-submodules",
        "PIL",
        "--hidden-import",
        "fitz",
        "--hidden-import",
        "pdfplumber",
        "--hidden-import",
        "pytesseract",
    ]


def build_cli() -> None:
    run(
        pyinstaller_base(dist=CLI_DIST, work=WORK_ROOT / "cli")
        + [
            "--onefile",
            "--console",
            "--name",
            "kbparser",
            str(ROOT / "packaging" / "entrypoints" / "kbparser_cli.py"),
        ]
    )


def build_gui() -> None:
    args = pyinstaller_base(dist=GUI_DIST, work=WORK_ROOT / "gui") + [
        "--windowed",
        "--name",
        "KBParser",
    ]
    if sys.platform != "darwin":
        args.append("--onefile")
    args.append(str(ROOT / "packaging" / "entrypoints" / "kbparser_gui.py"))
    run(args)
    sign_macos_app()


def sign_macos_app() -> None:
    if sys.platform != "darwin":
        return
    app = GUI_DIST / "KBParser.app"
    if not app.exists():
        return
    for attempt in range(1, 4):
        clean_macos_metadata(app)
        sign_result = subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], cwd=ROOT)
        verify_result = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], cwd=ROOT)
        if sign_result.returncode == 0 and verify_result.returncode == 0:
            return
        if attempt < 3:
            time.sleep(1)
    raise SystemExit(f"codesign failed for {app}")


def clean_macos_metadata(path: Path) -> None:
    run(["dot_clean", "-m", str(path)])
    for attr in ("com.apple.fileprovider.fpfs#P", "com.apple.FinderInfo"):
        subprocess.run(
            ["find", str(path), "-exec", "xattr", "-d", attr, "{}", ";"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    run(["xattr", "-cr", str(path)])


def cli_executable() -> Path:
    candidates = [
        CLI_DIST / ("kbparser.exe" if sys.platform == "win32" else "kbparser"),
        CLI_DIST / "kbparser" / ("kbparser.exe" if sys.platform == "win32" else "kbparser"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"kbparser executable not found in {CLI_DIST}")


def smoke_cli() -> None:
    exe = cli_executable()
    run([str(exe), "--version"])
    run([str(exe), "doctor"])


def main() -> int:
    shutil.rmtree(DIST_ROOT, ignore_errors=True)
    shutil.rmtree(WORK_ROOT, ignore_errors=True)
    build_cli()
    build_gui()
    smoke_cli()
    print(f"Built apps in {DIST_ROOT}")
    print(f"Platform: {platform.platform()} {platform.machine()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
