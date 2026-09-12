"""Parser protocol + shared helpers."""
from __future__ import annotations

import datetime as _dt
import mimetypes
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..ids import doc_id, sha256_file
from ..model import Document, Parse, Source, Warning
from ..versioning import PACKAGE_VERSION


@dataclass
class ParseContext:
    path: Path
    profile: str
    ocr_langs: str | None = None  # Tesseract language codes, e.g. "rus+eng"
    cancelled: Callable[[], bool] | None = None


class ParseCancelled(Exception):
    pass


def check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise ParseCancelled("Parsing cancelled")


class Parser(Protocol):
    name: str
    version: str
    @property
    def formats(self) -> tuple[str, ...]: ...

    def parse(self, ctx: ParseContext) -> Document: ...


def _iso_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def _iso_mtime(path: Path) -> str:
    return _dt.datetime.fromtimestamp(path.stat().st_mtime, _dt.UTC).isoformat()


def _mime(path: Path, fmt: str) -> str:
    guess, _ = mimetypes.guess_type(str(path))
    if guess:
        return guess
    defaults = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
    }
    return defaults.get(fmt, "application/octet-stream")


def build_source_and_parse(
    ctx: ParseContext,
    fmt: str,
    parser_name: str,
    parser_version: str,
    *,
    started_at: str,
    ocr_used: bool = False,
    conversion_used: bool = False,
    confidence: float = 1.0,
    conversion_info: dict | None = None,
) -> tuple[Source, Parse, str]:
    p = ctx.path
    sha = sha256_file(p)
    src = Source(
        path=str(p.resolve()),
        filename=p.name,
        format=fmt,  # type: ignore[arg-type]
        mime_type=_mime(p, fmt),
        sha256=sha,
        size_bytes=p.stat().st_size,
        modified_at=_iso_mtime(p),
    )
    parse = Parse(
        parser=parser_name,
        parser_version=parser_version,
        started_at=started_at,
        finished_at=started_at,
        ocr_used=ocr_used,
        ocr_languages=(ctx.ocr_langs or "eng") if fmt == "pdf" else None,
        conversion_used=conversion_used,
        confidence=confidence,
        profile=ctx.profile,  # type: ignore[arg-type]
        conversion_info=conversion_info,
    )
    return src, parse, doc_id(sha, ctx.profile)


def finalize_parse(parse: Parse) -> Parse:
    parse.finished_at = _iso_now()
    return parse


def empty_document(
    ctx: ParseContext,
    fmt: str,
    parser_name: str,
    parser_version: str = PACKAGE_VERSION,
    *,
    warning_code: str = "parser_stub_used",
    warning_message: str = "Stub parser: no extraction performed (phase 1).",
) -> Document:
    started = _iso_now()
    src, parse, did = build_source_and_parse(
        ctx, fmt, parser_name, parser_version, started_at=started, confidence=0.0
    )
    return Document(
        id=did,
        source=src,
        metadata={},
        parse=finalize_parse(parse),
        warnings=[Warning(code=warning_code, message=warning_message)],  # type: ignore[arg-type]
    )


__all__ = ["Parser", "ParseContext", "build_source_and_parse", "finalize_parse", "empty_document"]
