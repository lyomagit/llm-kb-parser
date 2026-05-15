"""CLI entrypoint. `python -m kbparser.cli parse <path>` or `kbparser parse <path>`."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from collections import Counter
from pathlib import Path

from . import __version__
from .dispatcher import SUPPORTED, UnsupportedFormat, dispatch
from .export import to_output, write_json
from .records import build_records
from .runtime_tools import (
    LIBREOFFICE,
    TESSERACT,
    dependency_guidance_text,
    tesseract_language_status,
    tool_status,
)
from .validation import ValidationError, validate
from .versioning import RECORDS_VERSION, SCHEMA_VERSION

_MAX_OUTPUT_BASE_CHARS = 180
_RESERVED_OUTPUT_CHARS = set('<>:"/\\|?*')
_STATUS_SYMBOLS = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}
_STATUS_ASCII = {"PASS": "OK", "WARN": "!", "FAIL": "X"}


def _stream_supports_status_symbols(stream: object) -> bool:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        "".join(_STATUS_SYMBOLS.values()).encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def _status_marker(status: str, stream: object | None = None) -> str:
    if _stream_supports_status_symbols(stream or sys.stdout):
        return _STATUS_SYMBOLS[status]
    return _STATUS_ASCII[status]


def _safe_output_filename(path: Path) -> str:
    """Return a human-readable JSON filename based on the source filename."""
    base = "".join(
        "_" if ch in _RESERVED_OUTPUT_CHARS or ord(ch) < 32 else ch
        for ch in path.name
    ).strip(" .")
    if not base:
        base = "document"
    if len(base) > _MAX_OUTPUT_BASE_CHARS:
        base = base[:_MAX_OUTPUT_BASE_CHARS].rstrip(" ._") or "document"
    return f"{base}.json"


def _stable_path_suffix(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:8]


def _with_collision_suffix(filename: str, suffix: str) -> str:
    base = filename[:-5] if filename.endswith(".json") else filename
    suffix_part = f"__{suffix}"
    max_base = max(1, _MAX_OUTPUT_BASE_CHARS - len(suffix_part))
    return f"{base[:max_base].rstrip(' ._')}{suffix_part}.json"


def _output_filenames_for_inputs(inputs: list[Path]) -> dict[Path, str]:
    names = {p: _safe_output_filename(p) for p in inputs}
    counts = Counter(names.values())
    used: set[str] = set()
    out: dict[Path, str] = {}

    for path in inputs:
        name = names[path]
        if counts[name] > 1:
            name = _with_collision_suffix(name, _stable_path_suffix(path))
        while name in used:
            name = _with_collision_suffix(name, hashlib.sha256(name.encode("utf-8")).hexdigest()[:8])
        used.add(name)
        out[path] = name
    return out


def _parse_one(
    path: Path, out_dir: Path, output_filename: str, profile: str, overwrite: bool, ocr_langs: str | None,
) -> dict:
    t0 = time.monotonic()
    try:
        doc = dispatch(path, profile=profile, ocr_langs=ocr_langs)
    except UnsupportedFormat as e:
        return {"file": str(path), "status": "failed", "error": f"unsupported: {e}"}
    except Exception as e:  # parser hard failure
        return {"file": str(path), "status": "failed", "error": f"{type(e).__name__}: {e}"}
    t_parse = time.monotonic() - t0

    t1 = time.monotonic()
    try:
        records = build_records(doc)
    except Exception as e:
        return {"file": str(path), "status": "failed", "error": f"chunker: {type(e).__name__}: {e}"}
    t_records = time.monotonic() - t1

    try:
        validate(doc, records)
    except ValidationError as e:
        return {"file": str(path), "status": "failed", "error": f"validation: {e.errors}"}

    out_path = out_dir / output_filename
    if out_path.exists() and not overwrite:
        return {
            "file": str(path),
            "status": "skipped",
            "doc_id": doc.id,
            "output": str(out_path),
        }

    try:
        write_json(to_output(doc, records), out_path)
    except OSError as e:
        return {"file": str(path), "status": "failed", "error": f"write: {e}"}

    type_counts = dict(Counter(r.type for r in records))

    return {
        "file": str(path),
        "status": "partial" if doc.warnings else "success",
        "doc_id": doc.id,
        "output": str(out_path),
        "parser": doc.parse.parser,
        "warnings": len(doc.warnings),
        "warning_codes": [w.code for w in doc.warnings],
        "records": len(records),
        "record_counts": type_counts,
        "input_sha256": doc.source.sha256,
        "timings": {
            "parse_seconds": round(t_parse, 3),
            "records_seconds": round(t_records, 3),
        },
    }


def _iter_inputs(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p for p in path.rglob("*")
            if p.is_file() and p.suffix.lower().lstrip(".") in SUPPORTED
        )
    raise FileNotFoundError(path)


def cmd_parse(args: argparse.Namespace) -> int:
    src = Path(args.path).expanduser().resolve()
    if args.out:
        out_dir = Path(args.out).expanduser().resolve()
    else:
        out_dir = (src.parent / "kb-parse-out").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = _iter_inputs(src)
    if not inputs:
        print(f"no supported files under {src}", file=sys.stderr)
        return 2

    ocr_langs = args.lang or os.environ.get("KBPARSER_OCR_LANGS") or None
    output_names = _output_filenames_for_inputs(inputs)
    results = [
        _parse_one(p, out_dir, output_names[p], args.profile, args.overwrite, ocr_langs)
        for p in inputs
    ]

    if len(inputs) > 1 or src.is_dir():
        manifest = {
            "kbparser_version": __version__,
            "schema_version": SCHEMA_VERSION,
            "records_version": RECORDS_VERSION,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "root": str(src),
            "profile": args.profile,
            "results": results,
        }
        with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")

    for r in results:
        print(f"[{r['status']}] {r['file']} -> {r.get('output', r.get('error', ''))}")

    had_fail = any(r["status"] == "failed" for r in results)
    return 1 if had_fail else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Preflight check: verify runtime dependencies and environment."""
    checks: list[tuple[str, str, str]] = []  # (name, status, detail)

    # Python version
    py_ver = platform.python_version()
    py_ok = sys.version_info >= (3, 11)
    checks.append(("Python", "PASS" if py_ok else "FAIL", f"{py_ver} ({'>=3.11' if py_ok else '<3.11'})"))

    # Required packages
    required = ["pydantic", "docx", "openpyxl", "fitz", "pdfplumber", "xlrd", "pytesseract", "PIL"]
    pkg_names = ["pydantic", "python-docx", "openpyxl", "pymupdf", "pdfplumber", "xlrd", "pytesseract", "Pillow"]
    for mod, pkg in zip(required, pkg_names):
        try:
            __import__(mod)
            checks.append((f"Package {pkg}", "PASS", "importable"))
        except ImportError:
            checks.append((f"Package {pkg}", "FAIL", "not installed"))

    # External tools are optional for core parsing, but required for .doc and scanned-PDF OCR.
    libreoffice = tool_status(LIBREOFFICE)
    checks.append(("LibreOffice", libreoffice.status, libreoffice.detail))

    tesseract = tool_status(TESSERACT)
    checks.append(("Tesseract", tesseract.status, tesseract.detail))
    if tesseract.status == "PASS" and tesseract.path is not None:
        lang_status, lang_detail = tesseract_language_status(args.langs, tesseract.path)
        if lang_status == "WARN":
            lang_detail = f"{lang_detail}; install tesseract-lang or add tessdata files"
        checks.append(("Tesseract languages", lang_status, lang_detail))

    # Temp directory
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(delete=True) as f:
            f.write(b"test")
        checks.append(("Temp directory", "PASS", tempfile.gettempdir()))
    except Exception as e:
        checks.append(("Temp directory", "FAIL", str(e)))

    # kbparser version
    checks.append(("kbparser", "PASS", f"v{__version__} (schema {SCHEMA_VERSION}, records {RECORDS_VERSION})"))

    # Output
    max_name = max(len(c[0]) for c in checks)
    has_fail = False
    for name, status, detail in checks:
        icon = _status_marker(status)
        print(f"  {icon} {name:<{max_name}}  {detail}")
        if status == "FAIL":
            has_fail = True

    if any(status == "WARN" for _, status, _ in checks):
        print()
        print(dependency_guidance_text())

    return 1 if has_fail else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kbparser", description="Local doc → KB-ready JSON parser.")
    p.add_argument("--version", action="version", version=f"kbparser {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("parse", help="Parse file or directory.")
    q.add_argument("path")
    q.add_argument(
        "--out",
        default=None,
        help="Output directory. Default: <input_parent>/kb-parse-out",
    )
    q.add_argument(
        "--profile",
        choices=["fidelity", "balanced", "text-lite"],
        default="fidelity",
    )
    q.add_argument("--overwrite", action="store_true")
    q.add_argument(
        "--lang",
        default=None,
        help="Tesseract OCR language codes (e.g. 'rus+eng'). Env fallback: KBPARSER_OCR_LANGS.",
    )
    q.set_defaults(func=cmd_parse)

    d = sub.add_parser("doctor", help="Check runtime dependencies and environment.")
    d.add_argument(
        "--langs",
        default="rus+eng",
        help="OCR languages to verify for Tesseract language data. Default: rus+eng.",
    )
    d.set_defaults(func=cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
