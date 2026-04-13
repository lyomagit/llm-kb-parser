"""Canonical document model. Schema per design spec sections 8-13."""
from __future__ import annotations

from typing import Any, Literal, Optional

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
    "ocr_applied_to_pages",
    "ocr_skipped_missing_binary",
    "ocr_skipped_empty_result",
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
    conversion_used: bool = False
    confidence: float = 1.0
    profile: Literal["fidelity", "balanced", "text-lite"] = "fidelity"
    conversion_info: Optional[dict[str, Any]] = None


class Warning(_Base):
    code: WarningCode
    message: str
    scope: Optional[dict[str, Any]] = None


class Provenance(_Base):
    page: Optional[int] = None
    sheet: Optional[str] = None
    bbox: Optional[list[float]] = None  # [x0,y0,x1,y1]
    source_ids: list[str] = Field(default_factory=list)
    confidence: Optional[float] = None


class Section(_Base):
    id: str
    type: Literal["section"] = "section"
    title: Optional[str] = None
    level: int = 1
    numbering: Optional[str] = None
    parent_id: Optional[str] = None
    path: list[str] = Field(default_factory=list)
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    sheet_refs: list[str] = Field(default_factory=list)
    block_ids: list[str] = Field(default_factory=list)
    text: Optional[str] = None


class Block(_Base):
    id: str
    type: BlockType
    section_id: Optional[str] = None
    page: Optional[int] = None
    sheet: Optional[str] = None
    order: int = 0
    text: Optional[str] = None
    style: Optional[dict[str, Any]] = None
    bbox: Optional[list[float]] = None
    provenance: Optional[Provenance] = None


class TableCell(_Base):
    row: int
    col: int
    text: Optional[str] = None
    raw_value: Optional[Any] = None
    display_value: Optional[str] = None
    formula: Optional[str] = None
    row_span: int = 1
    col_span: int = 1
    bbox: Optional[list[float]] = None


class Table(_Base):
    id: str
    type: Literal["table"] = "table"
    section_id: Optional[str] = None
    page: Optional[int] = None
    sheet: Optional[str] = None
    title: Optional[str] = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[TableCell]] = Field(default_factory=list)
    summary_text: Optional[str] = None
    provenance: Optional[Provenance] = None


class Page(_Base):
    page_number: int
    width: Optional[float] = None
    height: Optional[float] = None
    block_ids: list[str] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)
    image_ids: list[str] = Field(default_factory=list)


class SheetRegion(_Base):
    id: str
    kind: Literal["title", "note", "data_table", "side_commentary"]
    range: str  # A1 notation e.g. "A1:D20"
    table_id: Optional[str] = None
    text: Optional[str] = None


class Sheet(_Base):
    id: str
    sheet_name: str
    index: int
    visibility: Literal["visible", "hidden", "very_hidden"] = "visible"
    used_range: Optional[str] = None
    table_ids: list[str] = Field(default_factory=list)
    regions: list[SheetRegion] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Asset(_Base):
    id: str
    kind: Literal["image", "embed", "other"]
    path: Optional[str] = None
    page: Optional[int] = None
    sheet: Optional[str] = None
    bbox: Optional[list[float]] = None
    mime_type: Optional[str] = None


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
    text: Optional[str] = None
    char_count: Optional[int] = None
    token_estimate: Optional[int] = None
    section_path: list[str] = Field(default_factory=list)
    section_title: Optional[str] = None
    page_span: Optional[list[int]] = None  # [start,end]
    sheet_name: Optional[str] = None
    source_node_ids: list[str] = Field(default_factory=list)
    source_table_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Output(_Base):
    """Top-level JSON output."""
    document: Document
    records: list[Record] = Field(default_factory=list)
