"""Format detection + parser dispatch."""
from __future__ import annotations

from pathlib import Path

from .parsers.base import ParseContext, Parser
from .parsers.doc import DOCParser
from .parsers.docx import DOCXParser
from .parsers.excel import ExcelParser
from .parsers.pdf import PDFParser

SUPPORTED = {"pdf", "docx", "doc", "xlsx", "xls"}

_MAGIC_PDF = b"%PDF-"
_MAGIC_ZIP = b"PK\x03\x04"  # docx/xlsx
_MAGIC_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy doc/xls


class UnsupportedFormat(Exception):
    pass


def detect_format(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    if ext in SUPPORTED:
        # Sanity-check via magic bytes for robustness.
        with open(path, "rb") as f:
            head = f.read(8)
        if ext == "pdf" and not head.startswith(_MAGIC_PDF):
            raise UnsupportedFormat(f"{path.name}: .pdf but no PDF magic")
        if ext in {"docx", "xlsx"} and not head.startswith(_MAGIC_ZIP):
            raise UnsupportedFormat(f"{path.name}: .{ext} but no ZIP magic")
        if ext in {"doc", "xls"} and not head.startswith(_MAGIC_OLE):
            raise UnsupportedFormat(f"{path.name}: .{ext} but no OLE magic")
        return ext
    raise UnsupportedFormat(f"{path.name}: unsupported extension '{ext}'")


def get_parser(fmt: str) -> Parser:
    mapping: dict[str, Parser] = {
        "pdf": PDFParser(),
        "docx": DOCXParser(),
        "doc": DOCParser(),
        "xlsx": ExcelParser(),
        "xls": ExcelParser(),
    }
    if fmt not in mapping:
        raise UnsupportedFormat(fmt)
    return mapping[fmt]


def dispatch(path: Path, profile: str = "fidelity", ocr_langs: str | None = None):
    fmt = detect_format(path)
    parser = get_parser(fmt)
    return parser.parse(ParseContext(path=path, profile=profile, ocr_langs=ocr_langs))
