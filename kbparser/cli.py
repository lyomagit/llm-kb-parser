"""CLI entrypoint. `python -m kbparser.cli parse <path> [--out <dir>]`."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .dispatcher import SUPPORTED, UnsupportedFormat, dispatch
from .export import to_output, write_json
from .records import build_records
from .validation import ValidationError, validate


def _parse_one(
    path: Path, out_dir: Path, profile: str, overwrite: bool, ocr_langs: str | None,
) -> dict:
    try:
        doc = dispatch(path, profile=profile, ocr_langs=ocr_langs)
    except UnsupportedFormat as e:
        return {"file": str(path), "status": "failed", "error": f"unsupported: {e}"}
    except Exception as e:  # parser hard failure
        return {"file": str(path), "status": "failed", "error": f"{type(e).__name__}: {e}"}

    try:
        records = build_records(doc)
    except Exception as e:
        return {"file": str(path), "status": "failed", "error": f"chunker: {type(e).__name__}: {e}"}

    try:
        validate(doc, records)
    except ValidationError as e:
        return {"file": str(path), "status": "failed", "error": f"validation: {e.errors}"}

    out_path = out_dir / f"{doc.id}.json"
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

    return {
        "file": str(path),
        "status": "partial" if doc.warnings else "success",
        "doc_id": doc.id,
        "output": str(out_path),
        "parser": doc.parse.parser,
        "warnings": len(doc.warnings),
        "records": len(records),
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
    results = [
        _parse_one(p, out_dir, args.profile, args.overwrite, ocr_langs)
        for p in inputs
    ]

    if len(inputs) > 1 or src.is_dir():
        manifest = {"root": str(src), "profile": args.profile, "results": results}
        with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")

    for r in results:
        print(f"[{r['status']}] {r['file']} -> {r.get('output', r.get('error', ''))}")

    had_fail = any(r["status"] == "failed" for r in results)
    return 1 if had_fail else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kbparser", description="Local doc → KB-ready JSON parser.")
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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
