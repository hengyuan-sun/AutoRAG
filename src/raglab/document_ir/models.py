"""Schema 1.5 for parser-neutral document evidence and structure."""
from __future__ import annotations

import math
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.5"


class EvidenceStatus(str, Enum):
    EXTRACTED = "extracted"
    EMPTY_IN_SOURCE = "empty_in_source"
    UNSUPPORTED = "unsupported"
    UNRESOLVED = "unresolved"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    NOT_ATTEMPTED = "not_attempted"


class JobStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETE = "complete"
    DEGRADED = "degraded"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemKind(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    IMAGE = "image"
    FORMULA = "formula"
    TOC_ENTRY = "toc_entry"
    HEADER_FOOTER = "header_footer"


class IRModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceSpan(IRModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    unit: Literal["char", "byte", "token"] = "char"
    source_ref: str | None = None
    normalized_start: int | None = Field(default=None, ge=0)
    normalized_end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start or (self.normalized_start is not None and
                                     self.normalized_end is not None and
                                     self.normalized_end < self.normalized_start):
            raise ValueError("source span end must be greater than or equal to start")
        return self


class ArtifactRef(IRModel):
    uri: str
    sha256: str
    size_bytes: int = Field(ge=0)
    media_type: str = "application/octet-stream"


class Polygon(IRModel):
    points: list[tuple[float, float]]
    page_uid: str
    coordinate_unit: Literal["pt", "px", "mm"]
    coordinate_origin: Literal["top_left", "bottom_left"]
    source_rotation_deg: float | None = None
    correction_rotation_deg: float | None = None

    @field_validator("points")
    @classmethod
    def finite_points(cls, value):
        if len(value) < 3 or any(not math.isfinite(x) or not math.isfinite(y) for x, y in value):
            raise ValueError("polygon requires at least three finite points")
        return value


class EvidenceLocation(IRModel):
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    xpath: str | None = None
    reading_order: int | None = Field(default=None, ge=0)
    table_uid: str | None = None
    cell_row: int | None = Field(default=None, ge=0)
    cell_col: int | None = Field(default=None, ge=0)
    polygon: Polygon | None = None

    @field_validator("bbox")
    @classmethod
    def finite_bbox(cls, value):
        if value is not None and (any(not math.isfinite(x) for x in value) or
                                  value[2] < value[0] or value[3] < value[1]):
            raise ValueError("bbox must contain finite, ordered coordinates")
        return value


class Provenance(IRModel):
    item_id: int | str | None = None
    xpath: str | None = None
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    source: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)
    locations: list[EvidenceLocation] = Field(default_factory=list)


class ParagraphFormat(IRModel):
    style: str | None = None
    font_name: str | None = None
    font_size_pt: float | None = None
    line_spacing: float | None = None
    first_line_indent_pt: float | None = None


class TableCell(IRModel):
    uid: str | None = None
    text: str = ""
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    rowspan: int = Field(default=1, ge=1)
    colspan: int = Field(default=1, ge=1)
    is_header: bool = False
    provenance: EvidenceLocation | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)
    content_uids: list[str] = Field(default_factory=list)
    status: EvidenceStatus = EvidenceStatus.NOT_ATTEMPTED
    status_reason: str | None = None
    evidence_refs: list[ArtifactRef] = Field(default_factory=list)


class TableImageRef(IRModel):
    uid: str
    title: str = ""
    filename: str = ""
    overall_content: str = ""
    pic_summary: str = ""
    pic_title: str = ""


class _Item(IRModel):
    uid: str
    text: str = ""
    chapter_path: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    parent_uid: str | None = None
    order: int | None = Field(default=None, ge=0)
    status: EvidenceStatus = EvidenceStatus.NOT_ATTEMPTED
    status_reason: str | None = None
    evidence_refs: list[ArtifactRef] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)


class HeadingItem(_Item):
    type: Literal["heading"]
    level: int = Field(default=1, ge=1)
    number: str | None = None


class ParagraphItem(_Item):
    type: Literal["paragraph"]
    format: ParagraphFormat | None = None
    image_uids: list[str] = Field(default_factory=list)


class TableItem(_Item):
    type: Literal["table"]
    title: str = ""
    cells: list[TableCell] = Field(default_factory=list)
    grid_complete: bool = True
    grid_status_reason: str | None = None
    n_rows: int = Field(default=0, ge=0)
    n_cols: int = Field(default=0, ge=0)
    has_header: bool | None = None
    table_markdown: str = ""
    table_json: list[dict[str, Any]] = Field(default_factory=list)
    linearized_rows: list[str] = Field(default_factory=list)
    image_refs: list[TableImageRef] = Field(default_factory=list)
    caption_paragraph_uid: str | None = None


class ImageItem(_Item):
    type: Literal["image"]
    filename: str = ""
    title: str = ""
    pic_summary: str = ""
    llm_description: str = ""
    width_px: int | None = Field(default=None, ge=0)
    height_px: int | None = Field(default=None, ge=0)
    media_artifact: ArtifactRef | None = None
    source_relationship_id: str | None = None
    source_container_uid: str | None = None


class FormulaItem(_Item):
    type: Literal["formula"]
    latex: str = ""
    source_image: str | None = None


class TocEntryItem(_Item):
    type: Literal["toc_entry"]
    target_number: str | None = None


class HeaderFooterItem(_Item):
    type: Literal["header_footer"]
    kind: Literal["header", "footer", "page_number"] = "header"
    page: int | None = Field(default=None, ge=1)


IRItem = Annotated[HeadingItem | ParagraphItem | TableItem | ImageItem | FormulaItem,
                   Field(discriminator="type")]


class OutlineNode(IRModel):
    title: str = ""
    level: int = Field(default=1, ge=1)
    number: str | None = None
    item_uids: list[str] = Field(default_factory=list)
    children: list[OutlineNode] = Field(default_factory=list)


class FileMeta(IRModel):
    doc_id: str
    filename: str
    sha256: str
    size_bytes: int = Field(ge=0)
    detected_format: str
    original_format: str
    conversion_applied: bool = False
    encryption_state: str = "none"


class EngineRunInfo(IRModel):
    engine: str
    engine_version: str
    mineru_mode: str | None = None
    mineru_backend: str | None = None
    pages: int | None = Field(default=None, ge=0)


class PageInfo(IRModel):
    page: int = Field(ge=1)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    coordinate_unit: Literal["pt", "px", "mm"] | None = None
    coordinate_origin: Literal["top_left", "bottom_left"] | None = None
    artifact: ArtifactRef | None = None


class ProviderAttempt(IRModel):
    provider: str
    version: str | None = None
    model: str | None = None
    model_sha256: str | None = None
    config_digest: str | None = None
    status: Literal["succeeded", "empty", "failed", "timed_out", "cancelled"]
    trace_id: str | None = None
    input_artifacts: list[ArtifactRef] = Field(default_factory=list)
    output_artifacts: list[ArtifactRef] = Field(default_factory=list)
    elapsed_ms: int | None = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0)
    error_code: str | None = None
    confidence_summary: dict[str, float] = Field(default_factory=dict)


class PageRecord(IRModel):
    uid: str
    page: int = Field(ge=1)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    coordinate_unit: Literal["pt", "px", "mm"] | None = None
    coordinate_origin: Literal["top_left", "bottom_left"] | None = None
    source_artifact: ArtifactRef | None = None
    render_artifact: ArtifactRef | None = None
    status: EvidenceStatus = EvidenceStatus.NOT_ATTEMPTED
    provider_attempts: list[ProviderAttempt] = Field(default_factory=list)
    reason: str | None = None


class DocumentShard(IRModel):
    batch_id: int = Field(ge=0)
    artifact: ArtifactRef
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    item_uids: list[str] = Field(default_factory=list)
    chunk_index: int | None = Field(default=None, ge=0)
    chunk_count: int | None = Field(default=None, ge=0)
    encoding: str = "document-ir-json"
    content_sha256: str | None = None


class ProviderSnapshot(IRModel):
    provider: str
    version: str | None = None
    model: str | None = None
    config_digest: str | None = None
    trace_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    execution_status: Literal["configured", "invoked", "skipped", "failed", "degraded", "unknown"] = "unknown"
    status_detail: str | None = None


class EvidenceRelation(IRModel):
    source_uid: str
    target_uid: str
    kind: Literal["contains", "continues", "caption_of", "references", "derived_from", "same_as"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentIR(IRModel):
    schema_version: str = SCHEMA_VERSION
    meta: FileMeta
    engine_info: EngineRunInfo
    original_artifact: ArtifactRef | None = None
    job_status: JobStatus | None = None
    outline: list[OutlineNode] = Field(default_factory=list)
    items: list[IRItem] = Field(default_factory=list)
    toc: list[TocEntryItem] = Field(default_factory=list)
    header_footer: list[HeaderFooterItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    pages: list[PageInfo] = Field(default_factory=list)
    page_records: list[PageRecord] = Field(default_factory=list)
    relations: list[EvidenceRelation] = Field(default_factory=list)
    provider_snapshot: list[ProviderSnapshot] = Field(default_factory=list)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    capability_status: dict[str, str] = Field(default_factory=dict)
    manifest_only: bool = False
    manifest_item_count: int = Field(default=0, ge=0)
    shard_manifest_sha256: str | None = None
    shard_content_sha256: str | None = None
    shards: list[DocumentShard] = Field(default_factory=list)
    raw_artifacts: dict[str, Any] = Field(default_factory=dict)
    extensions: dict[str, Any] = Field(default_factory=dict)

    def iter_items(self, kind: ItemKind):
        return [item for item in self.items if item.type == kind.value]

    def by_uid(self, uid: str):
        return next((item for item in [*self.items, *self.toc, *self.header_footer]
                     if item.uid == uid), None)
