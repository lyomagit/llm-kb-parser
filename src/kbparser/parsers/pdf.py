"""PDF text, ruled tables, and optional OCR with source-text preservation.

Only painted borders define table grids. A lossy table candidate must not
replace embedded text. Widescreen pages get independent sections so numeric
callouts do not become document-wide headings.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import fitz  # pymupdf
import pdfplumber

from ..ids import block_id, section_id, table_id
from ..model import (
    Block,
    Document,
    Page,
    Provenance,
    Section,
    Table,
    TableCell,
    Warning,
)
from ..versioning import PACKAGE_VERSION
from .base import ParseContext, build_source_and_parse, check_cancelled, finalize_parse
from .ocr import OCREngineError, OCRTimeout, find_tesseract, ocr_page


class PDFParser:
    name = "pdf"
    version = PACKAGE_VERSION
    formats = ("pdf",)

    def parse(self, ctx: ParseContext) -> Document:
        from .base import _iso_now  # type: ignore
        started = _iso_now()
        src, parse, did = build_source_and_parse(
            ctx, "pdf", self.name, self.version, started_at=started, confidence=0.8,
        )

        metadata = _pdf_metadata(ctx.path)
        warnings: list[Warning] = []
        raw_pages = _extract_pymupdf(ctx.path, warnings, cancelled=ctx.cancelled)
        ocr = _maybe_ocr(
            ctx.path, raw_pages, profile=ctx.profile, lang=ctx.ocr_langs or "eng",
            cancelled=ctx.cancelled,
        )
        if ocr.applied_pages:
            parse.ocr_used = True
            warnings.append(Warning(
                code="ocr_applied_to_pages",
                message=f"OCR applied to {len(ocr.applied_pages)} page(s) with weak text layer.",
                scope={"pages": ocr.applied_pages},
            ))
        if ocr.missing_binary_pages:
            warnings.append(Warning(
                code="ocr_skipped_missing_binary",
                message=(
                    "Page(s) lack a text layer but Tesseract is not installed. "
                    "Install via `brew install tesseract` / `apt install tesseract-ocr` "
                    "to recover text."
                ),
                scope={"pages_missing_ocr": ocr.missing_binary_pages},
            ))
        if ocr.timeout_pages:
            warnings.append(Warning(
                code="ocr_skipped_timeout",
                message="OCR timed out for page(s) with weak text layer; file parsing continued without OCR text.",
                scope={"pages_missing_ocr": ocr.timeout_pages},
            ))
        if ocr.error_pages:
            warnings.append(Warning(
                code="ocr_skipped_error",
                message="OCR failed for page(s) with weak text layer; file parsing continued without OCR text.",
                scope={"pages_missing_ocr": ocr.error_pages},
            ))
        if ocr.empty_pages:
            warnings.append(Warning(
                code="ocr_skipped_empty_result",
                message="Tesseract produced no output for page(s); OCR effectively failed.",
                scope={"pages_missing_ocr": ocr.empty_pages},
            ))
        if ocr.disabled_pages:
            warnings.append(Warning(
                code="ocr_skipped_by_profile",
                message="Page(s) have no usable text layer; select fidelity or balanced to enable OCR.",
                scope={"pages_missing_ocr": ocr.disabled_pages},
            ))

        pdfplumber_tables = _extract_pdfplumber_tables(
            ctx.path, cancelled=ctx.cancelled, native_pages=raw_pages, warnings=warnings,
        )
        _strip_spans_inside_tables(raw_pages, pdfplumber_tables)
        page_sections = len(raw_pages) > 1 and all(p.width >= 1.6 * p.height for p in raw_pages)
        if page_sections:
            metadata["page_sections"] = True
            for page in raw_pages:
                page.blocks = _split_slide_columns(page)
        else:
            _classify_header_footer(raw_pages)
            body_size = _dominant_body_size(raw_pages)
            _assign_heading_levels(raw_pages, body_size)

        state = _BuildState(document_id=did)
        if raw_pages and not page_sections and not any(b.role == "heading" for p in raw_pages for b in p.blocks):
            fallback_title = str(metadata.get("title") or ctx.path.stem)
            state.push(1, fallback_title, raw_pages[0].number)

        pages_out: list[Page] = []
        tables_out: list[Table] = []

        for page in raw_pages:
            check_cancelled(ctx.cancelled)
            title_block = _page_title_block(page) if page_sections else None
            if page_sections:
                title = title_block.text if title_block else f"Страница {page.number}"
                state.push(1, title, page.number)
                for block in page.blocks:
                    block.role = "heading" if block is title_block else "body"
                    block.heading_level = 1 if block is title_block else None
            page_tables = pdfplumber_tables.get(page.number, [])
            page_out = Page(
                page_number=page.number,
                width=page.width,
                height=page.height,
            )
            items: list[tuple[tuple[float, float, float, float], str, Any]] = []
            for blk in page.blocks:
                if blk.role == "header_footer":
                    continue
                items.append((blk.bbox, "block", blk))
            for ti, tdata in enumerate(page_tables):
                items.append((tdata["bbox"], "table", (ti, tdata)))

            if page_sections:
                title_items = [item for item in items if item[1] == "block" and item[2] is title_block]
                footer_items = [item for item in items if item[1] == "block"
                                and item[2].text.strip() == str(page.number) and item[0][1] > page.height * 0.85]
                body_items = [item for item in items if item not in title_items and item not in footer_items]
                ordered = title_items + _reading_order(body_items, page.width) + footer_items
            else:
                ordered = _reading_order(items, page.width)
            for _, kind, payload in ordered:
                if not state.sections and (kind == "table" or payload.role != "heading"):
                    state.push(1, str(metadata.get("title") or ctx.path.stem), page.number)
                if kind == "block":
                    blk = payload  # type: ignore[assignment]
                    _emit_block(state, blk, page_out, infer_sections=not page_sections)
                else:
                    ti, tdata = payload
                    tbl = _build_pdf_table(did, state, tdata, page.number, ti)
                    tables_out.append(tbl)
                    state.add_table_ref(tbl.id, page_out)
                    page_out.table_ids.append(tbl.id)

            pages_out.append(page_out)

        # Warnings
        if any(b.role == "header_footer" for p in raw_pages for b in p.blocks):
            warnings.append(Warning(
                code="header_footer_filtered_heuristically",
                message="Running header/footer blocks filtered via repetition heuristic.",
            ))

        return Document(
            id=did,
            source=src,
            metadata=metadata,
            parse=finalize_parse(parse),
            warnings=warnings,
            sections=state.sections,
            blocks=state.blocks,
            tables=tables_out,
            pages=pages_out,
        )


# ----- extraction -----

@dataclass
class _Span:
    text: str
    size: float
    font: str
    bbox: tuple[float, float, float, float]
    line: int = 0


@dataclass
class _PdfBlock:
    text: str
    bbox: tuple[float, float, float, float]
    spans: list[_Span] = field(default_factory=list)
    role: str = "body"  # "body" | "header_footer" | "heading"
    heading_level: int | None = None
    dominant_size: float = 0.0
    is_bold: bool = False


@dataclass
class _PdfPage:
    number: int
    width: float
    height: float
    blocks: list[_PdfBlock] = field(default_factory=list)
    total_chars: int = 0
    has_images: bool = False


@dataclass
class _OCRSummary:
    applied_pages: list[int] = field(default_factory=list)
    missing_binary_pages: list[int] = field(default_factory=list)
    timeout_pages: list[int] = field(default_factory=list)
    error_pages: list[int] = field(default_factory=list)
    empty_pages: list[int] = field(default_factory=list)
    disabled_pages: list[int] = field(default_factory=list)


def _extract_pymupdf(path: Path, warnings: list[Warning], *, cancelled=None) -> list[_PdfPage]:
    out: list[_PdfPage] = []
    with fitz.open(str(path)) as doc:
        for i, page in enumerate(doc):
            check_cancelled(cancelled)
            page_obj = _PdfPage(number=i + 1, width=page.rect.width, height=page.rect.height)
            raw = page.get_text("dict")
            for block in raw.get("blocks", []):
                if block.get("type") != 0:
                    if block.get("type") == 1:
                        page_obj.has_images = True
                    continue
                spans: list[_Span] = []
                texts: list[str] = []
                for line_number, line in enumerate(block.get("lines", [])):
                    line_parts: list[str] = []
                    for span in line.get("spans", []):
                        t = span.get("text", "")
                        if t == "":
                            continue
                        spans.append(_Span(
                            text=t,
                            size=float(span.get("size", 0.0)),
                            font=str(span.get("font", "")),
                            bbox=tuple(span.get("bbox", (0, 0, 0, 0))),  # type: ignore[arg-type]
                            line=line_number,
                        ))
                        line_parts.append(t)
                    if line_parts:
                        texts.append("".join(line_parts))
                if not spans:
                    continue
                text = " ".join(texts).strip()
                if not text:
                    continue
                bbox = tuple(block.get("bbox", (0, 0, 0, 0)))
                sizes = Counter(round(s.size, 1) for s in spans)
                dominant_size = sizes.most_common(1)[0][0]
                is_bold = any("Bold" in s.font or "bold" in s.font for s in spans)
                page_obj.blocks.append(_PdfBlock(
                    text=text, bbox=bbox, spans=spans,
                    dominant_size=dominant_size, is_bold=is_bold,
                ))
                page_obj.total_chars += len(text)
            # stable reading order: top→bottom, then left→right
            page_obj.blocks.sort(key=lambda b: (round(b.bbox[1], 1), round(b.bbox[0], 1)))
            out.append(page_obj)
    return out


def _pdf_metadata(path: Path) -> dict:
    with fitz.open(str(path)) as doc:
        md = doc.metadata or {}
    out = {
        "title": md.get("title") or None,
        "author": md.get("author") or None,
        "subject": md.get("subject") or None,
        "keywords": md.get("keywords") or None,
        "producer": md.get("producer") or None,
        "creator": md.get("creator") or None,
    }
    return {k: v for k, v in out.items() if v and v != "(unspecified)"}


# ----- OCR branch -----

_OCR_TEXT_THRESHOLD = 80


def _maybe_ocr(
    path: Path, pages: list[_PdfPage], *, profile: str, lang: str = "eng",
    cancelled=None,
) -> _OCRSummary:
    candidates = [
        p for p in pages
        if p.total_chars < _OCR_TEXT_THRESHOLD and (p.has_images or p.total_chars == 0)
    ]
    if not candidates:
        return _OCRSummary()
    if profile == "text-lite":
        return _OCRSummary(disabled_pages=[p.number for p in candidates])

    tesseract = find_tesseract()
    if tesseract is None:
        return _OCRSummary(missing_binary_pages=[p.number for p in candidates])

    import fitz  # pymupdf

    summary = _OCRSummary()
    with fitz.open(str(path)) as doc:
        for p in candidates:
            check_cancelled(cancelled)
            fitz_page = doc[p.number - 1]
            try:
                results = ocr_page(fitz_page, tesseract, lang=lang)
            except OCRTimeout:
                summary.timeout_pages.append(p.number)
                continue
            except OCREngineError:
                summary.error_pages.append(p.number)
                continue
            if not results:
                summary.empty_pages.append(p.number)
                continue
            added_text = False
            native_spans = [s for block in p.blocks for s in block.spans]
            native_text = {_compact_text(block.text) for block in p.blocks}
            for r in results:
                text = r.text.strip()
                if not text:
                    continue
                area = max(0, r.bbox[2] - r.bbox[0]) * max(0, r.bbox[3] - r.bbox[1])
                overlap = sum(
                    max(0, min(r.bbox[2], s.bbox[2]) - max(r.bbox[0], s.bbox[0]))
                    * max(0, min(r.bbox[3], s.bbox[3]) - max(r.bbox[1], s.bbox[1]))
                    for s in native_spans
                )
                if area and (overlap >= area * 0.5 or overlap > 0 and _compact_text(text) in native_text):
                    continue
                p.blocks.append(_PdfBlock(
                    text=text,
                    bbox=r.bbox,
                    spans=[_Span(text=text, size=11.0, font="ocr", bbox=r.bbox)],
                    dominant_size=11.0,
                    is_bold=False,
                ))
                p.total_chars += len(text)
                added_text = True
            if not added_text:
                if not p.total_chars:
                    summary.empty_pages.append(p.number)
                continue
            p.blocks.sort(key=lambda b: (round(b.bbox[1], 1), round(b.bbox[0], 1)))
            summary.applied_pages.append(p.number)
    return summary


# ----- header/footer detection -----

_DIGIT_RE = re.compile(r"\d+")


def _norm(text: str) -> str:
    return _DIGIT_RE.sub("#", text.strip().lower())


def _classify_header_footer(pages: list[_PdfPage]) -> None:
    if not pages:
        return
    n_pages = len(pages)
    # collect (zone, normalized_text) across pages
    occ: Counter[tuple[str, str]] = Counter()
    block_zones: list[list[str | None]] = []

    for p in pages:
        top_thr = p.height * 0.12
        bot_thr = p.height * 0.88
        zones: list[str | None] = []
        seen: set[tuple[str, str]] = set()
        for b in p.blocks:
            y_mid = (b.bbox[1] + b.bbox[3]) / 2
            zone: str | None = None
            if y_mid < top_thr:
                zone = "header"
            elif y_mid > bot_thr:
                zone = "footer"
            zones.append(zone)
            if zone is not None:
                key = (zone, _norm(b.text))
                if key not in seen:
                    occ[key] += 1
                    seen.add(key)
        block_zones.append(zones)

    # repeating: appears on ≥50% of pages (and on ≥2 pages)
    threshold = max(2, (n_pages + 1) // 2)
    repeating = {k for k, c in occ.items() if c >= threshold}

    for p, zones in zip(pages, block_zones, strict=True):
        for b, z in zip(p.blocks, zones, strict=True):
            if z is None:
                continue
            if (z, _norm(b.text)) in repeating:
                b.role = "header_footer"


# ----- heading detection -----

def _dominant_body_size(pages: list[_PdfPage]) -> float:
    counter: Counter[float] = Counter()
    for p in pages:
        for b in p.blocks:
            if b.role == "header_footer":
                continue
            counter[b.dominant_size] += max(1, len(b.text))  # weight by length
    if not counter:
        return 11.0
    return counter.most_common(1)[0][0]


def _assign_heading_levels(pages: list[_PdfPage], body_size: float) -> None:
    heading_sizes: set[float] = set()
    for p in pages:
        for b in p.blocks:
            if b.role == "header_footer":
                continue
            if b.dominant_size > body_size * 1.15 and len(b.text) <= 120:
                # candidate heading
                heading_sizes.add(b.dominant_size)
    ranked = sorted(heading_sizes, reverse=True)
    level_of = {s: i + 1 for i, s in enumerate(ranked)}
    for p in pages:
        for b in p.blocks:
            if b.role == "header_footer":
                continue
            if b.dominant_size in level_of:
                b.role = "heading"
                b.heading_level = level_of[b.dominant_size]


# ----- tables via pdfplumber -----

def _compact_text(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold()
                   if not c.isspace() and c != "\u00ad")


def _text_chars(text: str) -> Counter:
    return Counter(_compact_text(text))


def _inside(box: Sequence[float], outer: Sequence[float], tolerance: float = 2) -> bool:
    return (outer[0] - tolerance <= box[0] <= box[2] <= outer[2] + tolerance
            and outer[1] - tolerance <= box[1] <= box[3] <= outer[3] + tolerance)


def _extract_pdfplumber_tables(
    path: Path, *, cancelled=None, native_pages: list[_PdfPage] | None = None,
    warnings: list[Warning] | None = None,
) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    native = {p.number: p for p in native_pages or []}
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            check_cancelled(cancelled)
            page_no = i + 1
            entries: list[dict] = []
            try:
                # Filled slide backgrounds and clipping rectangles are not grid borders.
                ruled = page.filter(lambda obj: obj.get("object_type") not in {"rect", "curve", "line"}
                                    or obj.get("stroke", False))
                found = ruled.find_tables()
            except Exception:
                found = []
            for tbl in found:
                try:
                    rows = tbl.extract() or []
                except Exception:
                    rows = []
                if not rows:
                    continue
                bbox = tuple(tbl.bbox)
                expected = ""
                if page_no in native:
                    for block in native[page_no].blocks:
                        for span in block.spans:
                            cx, cy = (span.bbox[0] + span.bbox[2]) / 2, (span.bbox[1] + span.bbox[3]) / 2
                            if _inside((cx, cy, cx, cy), bbox):
                                expected += span.text
                actual = "".join(cell or "" for row in rows for cell in row)
                missing = _text_chars(expected) - _text_chars(actual)
                if missing:
                    if warnings is not None:
                        warnings.append(Warning(
                            code="table_structure_uncertain",
                            message="Table extraction omitted source text; original text blocks preserved instead.",
                            scope={"page": page_no, "bbox": list(bbox), "missing_chars": sum(missing.values())},
                        ))
                    continue
                entries.append({"bbox": bbox, "rows": rows})
            if entries:
                out[page_no] = entries
    return out


def _strip_spans_inside_tables(
    pages: list[_PdfPage], pp_tables: dict[int, list[dict]],
) -> None:
    for p in pages:
        tbl_boxes = [t["bbox"] for t in pp_tables.get(p.number, [])]
        if not tbl_boxes:
            continue
        kept: list[_PdfBlock] = []
        for b in p.blocks:
            spans = [s for s in b.spans if not any(_inside(s.bbox, box) for box in tbl_boxes)]
            if len(spans) == len(b.spans):
                kept.append(b)
            elif spans:
                kept.append(_block_from_spans(b, spans))
        p.blocks = kept


# ----- build phase -----

def _block_from_spans(block: _PdfBlock, spans: list[_Span]) -> _PdfBlock:
    lines: dict[int, list[str]] = {}
    for span in spans:
        lines.setdefault(span.line, []).append(span.text)
    text = " ".join("".join(parts) for parts in lines.values()).strip()
    box = (min(s.bbox[0] for s in spans), min(s.bbox[1] for s in spans),
           max(s.bbox[2] for s in spans), max(s.bbox[3] for s in spans))
    return replace(block, text=text, bbox=box, spans=spans,
                   dominant_size=Counter(s.size for s in spans).most_common(1)[0][0],
                   is_bold=any("bold" in s.font.lower() for s in spans))


def _split_slide_columns(page: _PdfPage) -> list[_PdfBlock]:
    result: list[_PdfBlock] = []
    for block in page.blocks:
        sizes = [s.size for s in block.spans]
        if len(sizes) < 2 or max(sizes) > min(sizes) * 1.2:
            result.append(block)
            continue
        groups: list[list[_Span]] = []
        right: float | None = None
        for span in sorted(block.spans, key=lambda s: s.bbox[0]):
            if right is None or span.bbox[0] - right > max(16, page.width * 0.04):
                groups.append([])
            groups[-1].append(span)
            right = max(right, span.bbox[2]) if right is not None else span.bbox[2]
        if len(groups) == 1:
            result.append(block)
        else:
            for group in groups:
                result.append(_block_from_spans(block, [s for s in block.spans if s in group]))
    return result

def _page_title_block(page: _PdfPage) -> _PdfBlock | None:
    candidates = [b for b in page.blocks if len(b.text) <= 240 and sum(c.isalpha() for c in b.text) >= 4]
    top = [b for b in candidates if b.bbox[1] < page.height * 0.25]
    ranked = [(max((s.size for s in b.spans if any(c.isalpha() for c in s.text)), default=b.dominant_size), b)
              for b in top or candidates]
    if not ranked:
        return None
    minimum_size = max(size for size, _ in ranked) * 0.6
    return min((b for size, b in ranked if size >= minimum_size), key=lambda b: (b.bbox[1], b.bbox[0]))

def _reading_order(items: list[tuple], width: float) -> list[tuple]:
    """Read clear, overlapping columns between full-width content bands."""
    def row_order(values: list[tuple]) -> list[tuple]:
        return sorted(values, key=lambda item: (item[0][1], item[0][0]))

    def columns(band: list[tuple]) -> list[tuple]:
        groups: list[list[tuple]] = []
        left: float | None = None
        for item in sorted(band, key=lambda value: value[0][0]):
            if left is None or item[0][0] - left > max(24, width * 0.15):
                groups.append([])
                left = item[0][0]
            groups[-1].append(item)
        if len(groups) < 2:
            return row_order(band)
        if any(max(item[0][2] for item in group) - min(item[0][0] for item in group) < width * 0.15
               for group in groups):
            return row_order(band)
        # Separate indentation levels are not parallel columns.
        top = max(min(item[0][1] for item in group) for group in groups)
        bottom = min(max(item[0][3] for item in group) for group in groups)
        if top >= bottom:
            return row_order(band)
        return [item for group in groups for item in row_order(group)]

    result: list[tuple] = []
    band: list[tuple] = []
    for item in row_order(items):
        if item[0][2] - item[0][0] > width * 0.6:
            result.extend(columns(band))
            band = []
            result.append(item)
        else:
            band.append(item)
    return result + columns(band)

class _BuildState:
    def __init__(self, document_id: str):
        self.document_id = document_id
        self.sections: list[Section] = []
        self.blocks: list[Block] = []
        self.stack: list[Section] = []
        self.section_order = 0
        self.block_order = 0

    def current_sid(self) -> str | None:
        return self.stack[-1].id if self.stack else None

    def path(self) -> list[str]:
        return [s.title or f"sec{s.level}" for s in self.stack]

    def push(self, level: int, title: str, page: int) -> Section:
        while self.stack and self.stack[-1].level >= level:
            self.stack.pop()
        parent = self.current_sid()
        path = self.path() + [title or f"sec{level}"]
        sid = section_id(self.document_id, path, self.section_order)
        self.section_order += 1
        sec = Section(
            id=sid, title=title or None, level=level,
            parent_id=parent, path=path,
            page_start=page, page_end=page,
        )
        self.sections.append(sec)
        self.stack.append(sec)
        return sec

    def extend_section_page(self, page: int) -> None:
        for s in self.stack:
            s.page_end = page
        # also extend already-closed sections that are ancestors? not needed —
        # page_end updates only while on stack; once popped, it freezes.

    def add_block(
        self, btype: str, text: str | None, page: int,
        bbox: tuple[float, float, float, float] | None,
        style: dict | None,
    ) -> Block:
        sid = self.current_sid() or ""
        anchor = (text or "")[:40]
        bid = block_id(self.document_id, sid, self.block_order, anchor)
        self.block_order += 1
        blk = Block(
            id=bid, type=btype,  # type: ignore[arg-type]
            section_id=sid or None,
            page=page, order=self.block_order,
            text=text, style=style,
            bbox=list(bbox) if bbox else None,
            provenance=Provenance(page=page, confidence=0.9),
        )
        self.blocks.append(blk)
        if self.stack:
            self.stack[-1].block_ids.append(bid)
        return blk

    def add_table_ref(self, table_id_value: str, page_out: Page) -> None:
        blk = self.add_block(
            "table_ref", f"[table {table_id_value}]",
            page_out.page_number, None, None,
        )
        page_out.block_ids.append(blk.id)


def _emit_block(state: _BuildState, blk: _PdfBlock, page_out: Page, *, infer_sections: bool = True) -> None:
    style = {"font_size": blk.dominant_size, "bold": blk.is_bold}
    if blk.role == "heading" and blk.heading_level is not None:
        if infer_sections:
            state.push(blk.heading_level, blk.text.strip(), page_out.page_number)
        b = state.add_block("heading", blk.text, page_out.page_number, blk.bbox, style)
    else:
        b = state.add_block("paragraph", blk.text, page_out.page_number, blk.bbox, style)
    state.extend_section_page(page_out.page_number)
    page_out.block_ids.append(b.id)


def _build_pdf_table(
    doc_id: str, state: _BuildState, tdata: dict, page_no: int, order: int,
) -> Table:
    rows = tdata["rows"]
    bbox = tdata["bbox"]
    tid = table_id(doc_id, f"page:{page_no}", order)
    cells: list[list[TableCell]] = []
    for ri, row in enumerate(rows):
        crow: list[TableCell] = []
        for ci, val in enumerate(row):
            text = (val or "").strip() if isinstance(val, str) else (str(val) if val is not None else None)
            crow.append(TableCell(row=ri, col=ci, text=text))
        cells.append(crow)
    columns = [(c.text or "") for c in cells[0]] if cells else []
    return Table(
        id=tid,
        section_id=state.current_sid(),
        page=page_no,
        columns=columns,
        rows=cells,
        provenance=Provenance(page=page_no, bbox=list(bbox)),
    )
