"""Canonical document model. Schema per design spec sections 8-13."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BlockType = Literal[
    "paragraph",
    "heading",
    "list",
    "list_item",
    "table_ref",
    "caption",
    "note",
    "header",
    "footer",
    "cell_text",
]

RecordType = Literal[
    "chunk",
    "reference_chunk",
    "diagram_chunk",
    "table",
    "section_summary_seed",
    "sheet_region",
]

WarningCode = Literal[
    "ocr_skipped_by_profile",
    "empty_extraction",
    "ocr_applied_to_pages",
    "ocr_skipped_missing_binary",
    "ocr_skipped_empty_result",
    "ocr_skipped_timeout",
    "ocr_skipped_error",
    "table_structure_uncertain",
    "doc_conversion_lost_styles",
    "formula_not_evaluated",
    "header_footer_filtered_heuristically",
    "heading_inference_low_confidence",
    "parser_stub_used",
]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Base):
    path: str
    filename: str
    format: Literal["pdf", "docx", "doc", "xls", "xlsx"]
    mime_type: str
    sha256: str
    size_bytes: int
    modified_at: str


class Parse(_Base):
    parser: str
    parser_version: str
    started_at: str
    finished_at: str
    ocr_used: bool = False
    ocr_languages: str | None = None
    conversion_used: bool = False
    confidence: float = 1.0
    profile: Literal["fidelity", "balanced", "text-lite"] = "fidelity"
    conversion_info: dict[str, Any] | None = None


class Warning(_Base):
    code: WarningCode
    message: str
    scope: dict[str, Any] | None = None


class Provenance(_Base):
    page: int | None = None
    sheet: str | None = None
    bbox: list[float] | None = None  # [x0,y0,x1,y1]
    source_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None


class Section(_Base):
    id: str
    type: Literal["section"] = "section"
    title: str | None = None
    level: int = 1
    numbering: str | None = None
    parent_id: str | None = None
    path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    sheet_refs: list[str] = Field(default_factory=list)
    block_ids: list[str] = Field(default_factory=list)
    text: str | None = None


class Block(_Base):
    id: str
    type: BlockType
    section_id: str | None = None
    page: int | None = None
    sheet: str | None = None
    order: int = 0
    text: str | None = None
    style: dict[str, Any] | None = None
    bbox: list[float] | None = None
    provenance: Provenance | None = None


class TableCell(_Base):
    row: int
    col: int
    text: str | None = None
    raw_value: Any | None = None
    display_value: str | None = None
    formula: str | None = None
    row_span: int = 1
    col_span: int = 1
    bbox: list[float] | None = None


class Table(_Base):
    id: str
    type: Literal["table"] = "table"
    section_id: str | None = None
    page: int | None = None
    sheet: str | None = None
    title: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[TableCell]] = Field(default_factory=list)
    summary_text: str | None = None
    provenance: Provenance | None = None


class Page(_Base):
    page_number: int
    width: float | None = None
    height: float | None = None
    block_ids: list[str] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)
    image_ids: list[str] = Field(default_factory=list)


class SheetRegion(_Base):
    id: str
    kind: Literal["title", "note", "data_table", "side_commentary"]
    range: str  # A1 notation e.g. "A1:D20"
    table_id: str | None = None
    text: str | None = None


class Sheet(_Base):
    id: str
    sheet_name: str
    index: int
    visibility: Literal["visible", "hidden", "very_hidden"] = "visible"
    used_range: str | None = None
    table_ids: list[str] = Field(default_factory=list)
    regions: list[SheetRegion] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Asset(_Base):
    id: str
    kind: Literal["image", "embed", "other"]
    path: str | None = None
    page: int | None = None
    sheet: str | None = None
    bbox: list[float] | None = None
    mime_type: str | None = None


class Relationship(_Base):
    kind: Literal["contains", "references", "caption_of", "footnote_of"]
    from_id: str
    to_id: str


class Document(_Base):
    id: str
    source: Source
    metadata: dict[str, Any] = Field(default_factory=dict)
    parse: Parse
    warnings: list[Warning] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)
    sheets: list[Sheet] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)


class Record(_Base):
    id: str
    type: RecordType
    document_id: str
    text: str | None = None
    char_count: int | None = None
    token_estimate: int | None = None
    section_path: list[str] = Field(default_factory=list)
    section_title: str | None = None
    page_span: list[int] | None = None  # [start,end]
    sheet_name: str | None = None
    source_node_ids: list[str] = Field(default_factory=list)
    source_table_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Output(_Base):
    """Top-level JSON output."""
    schema_version: str = "1.0"
    records_version: str = "1.0"
    parser_version: str = "0.0.0"
    document: Document
    records: list[Record] = Field(default_factory=list)
