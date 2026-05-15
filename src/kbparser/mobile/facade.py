"""Android-safe facade for the kbparser Python core.

This module is intentionally narrower than the desktop CLI. Android Phase 0
proves the embedded-Python path with formats that do not require desktop-only
tools such as LibreOffice, Tkinter, PyInstaller, or a Tesseract executable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MAGIC_ZIP = b"PK\x03\x04"
_MAGIC_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_SUPPORTED_FORMATS = ("xls", "xlsx")

_DISABLED_FORMATS: dict[str, dict[str, str]] = {
    "doc": {
        "reason": "LibreOffice is not bundled on Android",
        "replacement": "convert to DOCX/XLSX/PDF before import",
    },
    "docx": {
        "reason": "DOCX mobile backend is pending dependency validation",
        "replacement": "lightweight OOXML extractor or verified python-docx path",
    },
    "pdf": {
        "reason": "desktop PDF parser requires PyMuPDF",
        "replacement": "Android PDF backend without PyMuPDF hard dependency",
    },
    "ocr": {
        "reason": "pytesseract requires an external Tesseract executable",
        "replacement": "native Android OCR bridge",
    },
}


def android_capabilities_json() -> str:
    """Return the current Android Phase 0 capability contract."""
    return _json({
        "supported_formats": list(_SUPPORTED_FORMATS),
        "disabled_formats": _DISABLED_FORMATS,
        "python_entrypoint": "kbparser.mobile.facade.parse_path_json",
    })


def parse_path_json(path: str, profile: str = "balanced") -> str:
    """Parse an Android-cache file path and return a JSON string.

    Android code should copy the user-selected content URI into app-private
    cache first, then pass that cache path here. The result is always JSON so
    the Kotlin bridge has a stable contract for success and failure cases.
    """
    source = Path(path).expanduser()
    try:
        fmt = _detect_android_format(source)
    except Exception as exc:
        return _json({
            "status": "failed",
            "file": str(source),
            "message": f"{type(exc).__name__}: {exc}",
        })

    if fmt not in _SUPPORTED_FORMATS:
        disabled = _DISABLED_FORMATS.get(fmt, {
            "reason": f"{fmt} is not enabled in the Android Phase 0 profile",
            "replacement": "use a supported XLS/XLSX file for the feasibility spike",
        })
        return _json({
            "status": "unsupported",
            "format": fmt,
            "file": str(source),
            "message": disabled["reason"],
            "replacement": disabled["replacement"],
        })

    try:
        return _json(_parse_excel(source, fmt, profile))
    except Exception as exc:
        return _json({
            "status": "failed",
            "format": fmt,
            "file": str(source),
            "message": f"{type(exc).__name__}: {exc}",
        })


def _detect_android_format(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    ext = path.suffix.lower().lstrip(".")
    with open(path, "rb") as handle:
        head = handle.read(8)
    if ext == "xlsx":
        if not head.startswith(_MAGIC_ZIP):
            raise ValueError(f"{path.name}: .xlsx but no ZIP magic")
        return ext
    if ext == "xls":
        if not head.startswith(_MAGIC_OLE):
            raise ValueError(f"{path.name}: .xls but no OLE magic")
        return ext
    return ext or "unknown"


def _parse_excel(path: Path, fmt: str, profile: str) -> dict[str, Any]:
    if fmt == "xlsx":
        sheets = _parse_xlsx(path)
    else:
        sheets = _parse_xls(path)
    records = [
        {
            "type": "sheet_summary",
            "sheet_name": sheet["name"],
            "text": (
                f"{sheet['name']}: {sheet['non_empty_cells']} non-empty cells "
                f"across {sheet['rows']} rows x {sheet['columns']} columns"
            ),
        }
        for sheet in sheets
    ]
    return {
        "status": "success",
        "format": fmt,
        "backend": "mobile-lightweight-excel",
        "profile": profile,
        "source": {
            "path": str(path),
            "filename": path.name,
            "size_bytes": path.stat().st_size,
        },
        "sheets": sheets,
        "records": records,
    }


def _parse_xlsx(path: Path) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(str(path), data_only=False, read_only=True)
    try:
        return [
            _summarize_rows(
                name=sheet.title,
                rows=sheet.iter_rows(values_only=True),
                max_row=sheet.max_row or 0,
                max_column=sheet.max_column or 0,
            )
            for sheet in workbook.worksheets
        ]
    finally:
        workbook.close()


def _parse_xls(path: Path) -> list[dict[str, Any]]:
    import xlrd

    workbook = xlrd.open_workbook(str(path), on_demand=True, use_mmap=False)
    try:
        out: list[dict[str, Any]] = []
        for sheet in workbook.sheets():
            rows = (
                tuple(sheet.cell_value(row_index, col_index) for col_index in range(sheet.ncols))
                for row_index in range(sheet.nrows)
            )
            out.append(_summarize_rows(
                name=sheet.name,
                rows=rows,
                max_row=sheet.nrows,
                max_column=sheet.ncols,
            ))
        return out
    finally:
        workbook.release_resources()


def _summarize_rows(
    *,
    name: str,
    rows,
    max_row: int,
    max_column: int,
    preview_limit: int = 10,
) -> dict[str, Any]:
    preview: list[list[Any]] = []
    non_empty = 0
    for row in rows:
        values = [_cell_json(value) for value in row]
        if any(value not in (None, "") for value in values):
            non_empty += sum(1 for value in values if value not in (None, ""))
            if len(preview) < preview_limit:
                preview.append(values)
    return {
        "name": name,
        "rows": max_row,
        "columns": max_column,
        "non_empty_cells": non_empty,
        "preview_rows": preview,
    }


def _cell_json(value):
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return value


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
