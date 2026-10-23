"""Docling SDK adapter. Input is always a staged local path; network parsing is disabled."""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    ArtifactRef,
    DocumentIR,
    EvidenceLocation,
    EvidenceStatus,
    FileMeta,
    FormulaItem,
    HeadingItem,
    ImageItem,
    JobStatus,
    PageInfo,
    PageRecord,
    ParagraphItem,
    Polygon,
    Provenance,
    ProviderSnapshot,
    SourceSpan,
    TableItem,
)
from .models import (
    TableCell as IRTableCell,
)
from .validation import validate_document_ir

ADAPTER_VERSION = "docling-adapter@1"


class DoclingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    do_ocr: bool = False
    do_table_structure: bool = True
    artifacts_path: Path | None = None
    offline: Literal[True] = True
    max_pages: int = Field(default=1000, ge=1, le=10000)

    def config_digest(self) -> str:
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DoclingParserAdapter:
    path_based = True

    def __init__(self, options: DoclingOptions | None = None, converter=None):
        self.options = options or DoclingOptions()
        self._converter = converter
        try:
            self.package_version = importlib.metadata.version("docling-slim")
        except importlib.metadata.PackageNotFoundError:
            self.package_version = importlib.metadata.version("docling")
        self.version = f"docling@{self.package_version}+{ADAPTER_VERSION};config={self.options.config_digest()}"

    def _get_converter(self, extension: str):
        if self._converter is not None:
            return self._converter
        if extension == ".pdf":
            artifact_path = self.options.artifacts_path
            if artifact_path is None or not artifact_path.is_dir():
                raise ValueError("Docling PDF模型资产目录未配置；离线运行不会自动下载模型")
            if not any(artifact_path.iterdir()):
                raise ValueError("Docling PDF模型资产目录为空；离线运行不会自动下载模型")
            if importlib.util.find_spec("docling_ibm_models") is None:
                raise ValueError("缺少PDF模型运行时；安装项目可选依赖 docling-pdf 后再配置模型资产目录")
        if self.options.offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
            if importlib.util.find_spec("huggingface_hub") is not None:
                from huggingface_hub import constants

                constants.HF_HUB_OFFLINE = True
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        format_options = {}
        if extension == ".pdf":
            pdf_options = PdfPipelineOptions(
                do_ocr=self.options.do_ocr,
                do_table_structure=self.options.do_table_structure,
                generate_page_images=False,
            )
            pdf_options.artifacts_path = self.options.artifacts_path
            format_options[InputFormat.PDF] = PdfFormatOption(pipeline_options=pdf_options)
        self._converter = DocumentConverter(format_options=format_options)
        return self._converter

    def parse(self, name: str, source_path: Path, revision: str, options: DoclingOptions | None = None) -> DocumentIR:
        if options is not None and options != self.options:
            return DoclingParserAdapter(options).parse(name, source_path, revision)
        path = Path(source_path)
        extension = Path(name).suffix.lower()
        if extension not in {".pdf", ".docx", ".pptx", ".txt", ".md"}:
            raise ValueError("Docling适配器支持PDF/DOCX/PPTX/TXT/Markdown")
        digest = _file_sha256(path)
        size = path.stat().st_size
        converter = self._get_converter(extension)
        try:
            if extension == ".txt":
                markdown_path = None
                try:
                    with path.open("rb") as source, tempfile.NamedTemporaryFile(
                        mode="wb", suffix=".md", dir=path.parent, delete=False
                    ) as staged:
                        markdown_path = Path(staged.name)
                        shutil.copyfileobj(source, staged, length=65536)
                    result = converter.convert(markdown_path, max_num_pages=self.options.max_pages,
                                               max_file_size=size)
                finally:
                    if markdown_path is not None:
                        markdown_path.unlink(missing_ok=True)
            else:
                result = converter.convert(path, max_num_pages=self.options.max_pages, max_file_size=size)
        except Exception as exc:
            from docling.exceptions import ConversionError

            if isinstance(exc, ConversionError):
                raise ValueError(f"Docling解析失败：{exc}") from exc
            raise
        if getattr(result.status, "value", str(result.status)).lower() not in {"success", "partial_success"}:
            raise ValueError(f"Docling解析失败：{result.status}")

        nodes, relations, outline = self._map_items(result.document, digest)
        warnings = [str(getattr(error, "error_message", error)) for error in getattr(result, "errors", [])]
        pages, page_records = _map_pages(result.document)
        ir = DocumentIR(
            meta=FileMeta(doc_id=revision, filename=Path(name).name, sha256=digest, size_bytes=size,
                          detected_format=extension.lstrip("."), original_format=extension.lstrip(".")),
            engine_info={"engine": "docling", "engine_version": self.package_version, "pages": len(pages) or None},
            job_status=JobStatus.DEGRADED if warnings else JobStatus.COMPLETE,
            outline=outline, items=nodes, relations=relations, warnings=warnings,
            pages=pages, page_records=page_records,
            provider_snapshot=[ProviderSnapshot(provider="docling", version=self.package_version,
                                                config_digest=self.options.config_digest(),
                                                capabilities=["structure", "table"] + (["ocr"] if self.options.do_ocr else []),
                                                execution_status="invoked")],
            config_snapshot={"adapter": ADAPTER_VERSION, "options": self.options.model_dump(mode="json")},
            capability_status={"physical_location": "available" if any(
                item.provenance.locations for item in nodes) else "unsupported",
                "ocr": "configured" if self.options.do_ocr else "not_attempted",
                "tables": "configured" if self.options.do_table_structure else "not_attempted"},
            original_artifact=ArtifactRef(uri=f"blob:{digest}", sha256=digest, size_bytes=size,
                                         media_type=_media_type(extension)),
            extensions={"docling": {"document_name": getattr(result.document, "name", None)}},
        )
        return validate_document_ir(ir)

    def _map_items(self, document, file_hash):
        mapped: list[Any] = []
        relations = []
        outline = []
        outline_stack: list[tuple[int, dict]] = []
        heading_stack: list[tuple[int, str]] = []
        uid_by_ref: dict[str, str] = {}
        raw_items = list(document.iterate_items())

        for order, entry in enumerate(raw_items):
            native, _level = entry
            ref = str(getattr(native, "self_ref", f"item-{order}"))
            label_value = getattr(getattr(native, "label", None), "value", getattr(native, "label", ""))
            label = str(label_value).lower()
            native_type = type(native).__name__.lower()
            item_uid = _item_uid(file_hash, ref, label, order)
            uid_by_ref[ref] = item_uid
            text = str(getattr(native, "text", "") or "")
            locations, spans = _map_provenance(getattr(native, "prov", []))
            provenance = Provenance(item_id=ref, source="docling", source_spans=spans, locations=locations)
            common = {"uid": item_uid, "text": text, "provenance": provenance,
                      "order": order, "status": EvidenceStatus.EXTRACTED if text or "table" in native_type else EvidenceStatus.UNRESOLVED,
                      "extensions": {"docling": {"self_ref": ref, "label": label}}}

            if "table" in native_type or label == "table":
                common["type"] = "table"
                data = getattr(native, "data", None)
                table_cells = list(getattr(data, "table_cells", []) or [])
                cells = [IRTableCell(uid=f"{item_uid}:c{idx}", text=str(getattr(cell, "text", "") or ""),
                                     row=int(getattr(cell, "start_row_offset_idx", 0)),
                                     col=int(getattr(cell, "start_col_offset_idx", 0)),
                                     rowspan=int(getattr(cell, "row_span", 1)),
                                     colspan=int(getattr(cell, "col_span", 1)),
                                     is_header=bool(getattr(cell, "column_header", False)),
                                     status=EvidenceStatus.EXTRACTED)
                          for idx, cell in enumerate(table_cells)]
                mapped.append(TableItem(**common, cells=cells,
                                        n_rows=int(getattr(data, "num_rows", 0) or 0),
                                        n_cols=int(getattr(data, "num_cols", 0) or 0),
                                        grid_complete=bool(cells)))
            elif "picture" in native_type or label in {"picture", "image"}:
                common["type"] = "image"
                common["status"] = EvidenceStatus.UNRESOLVED
                mapped.append(ImageItem(**common,
                                        title=str(getattr(native, "caption", "") or "")))
            elif "formula" in native_type or label in {"formula", "formula_code"}:
                common["type"] = "formula"
                mapped.append(FormulaItem(**common, latex=text))
            elif label in {"section_header", "title"}:
                common["type"] = "heading"
                level = max(1, int(getattr(native, "level", 1) or 1))
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, text))
                outline_node = {"title": text, "level": level, "item_uids": [item_uid], "children": []}
                while outline_stack and outline_stack[-1][0] >= level:
                    outline_stack.pop()
                if outline_stack:
                    outline_stack[-1][1]["children"].append(outline_node)
                else:
                    outline.append(outline_node)
                outline_stack.append((level, outline_node))
                mapped.append(HeadingItem(**common, level=level, chapter_path=[value for _, value in heading_stack]))
            else:
                common["type"] = "paragraph"
                mapped.append(ParagraphItem(**common, chapter_path=[value for _, value in heading_stack]))

        for native, _level in raw_items:
            child_uid = uid_by_ref.get(str(getattr(native, "self_ref", "")))
            parent_ref = getattr(native, "parent", None)
            parent_ref = getattr(parent_ref, "cref", None)
            parent_uid = uid_by_ref.get(str(parent_ref)) if parent_ref else None
            if child_uid and parent_uid:
                child = next((item for item in mapped if item.uid == child_uid), None)
                if child:
                    child.parent_uid = parent_uid
                relations.append({"source_uid": parent_uid, "target_uid": child_uid,
                                  "kind": "contains", "metadata": {"source": "docling"}})
        return mapped, relations, outline


def _map_provenance(prov_items):
    locations, spans = [], []
    for prov in prov_items or []:
        page = getattr(prov, "page_no", None)
        bbox_obj = getattr(prov, "bbox", None)
        bbox = None
        if bbox_obj is not None:
            values = [getattr(bbox_obj, name, None) for name in ("l", "t", "r", "b")]
            if all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
                bbox = tuple(float(value) for value in values)
        if page or bbox:
            origin = getattr(getattr(bbox_obj, "coord_origin", None), "value",
                             getattr(bbox_obj, "coord_origin", None)) if bbox_obj is not None else None
            polygon = None
            if bbox and page and origin in {"TOPLEFT", "BOTTOMLEFT", "top_left", "bottom_left"}:
                normalized_origin = "top_left" if str(origin).lower() in {"topleft", "top_left"} else "bottom_left"
                left, top, right, bottom = bbox
                points = ([(left, top), (right, top), (right, bottom), (left, bottom)]
                          if normalized_origin == "top_left" else
                          [(left, bottom), (right, bottom), (right, top), (left, top)])
                polygon = Polygon(points=points, page_uid=f"page-{page}", coordinate_unit="pt",
                                  coordinate_origin=normalized_origin)
            locations.append(EvidenceLocation(page=page, bbox=bbox, polygon=polygon))
        charspan = getattr(prov, "charspan", None)
        if charspan and len(charspan) == 2 and charspan[0] is not None and charspan[1] is not None:
            spans.append(SourceSpan(start=int(charspan[0]), end=int(charspan[1]), unit="char"))
    return locations, spans


def _map_pages(document):
    pages, records = [], []
    for page_no, page in sorted(getattr(document, "pages", {}).items(), key=lambda pair: int(pair[0])):
        size = getattr(page, "size", None)
        width, height = getattr(size, "width", None), getattr(size, "height", None)
        pages.append(PageInfo(page=int(page_no), width=width, height=height))
        records.append(PageRecord(uid=f"page-{page_no}", page=int(page_no), width=width, height=height,
                                  status=EvidenceStatus.EXTRACTED))
    return pages, records


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while part := stream.read(65536):
            h.update(part)
    return h.hexdigest()


def _item_uid(file_hash: str, ref: str, label: str, order: int) -> str:
    digest = hashlib.sha256(f"{file_hash}\0{ref}\0{label}\0{order}".encode()).hexdigest()[:24]
    return f"ir_{digest}"


def _media_type(extension: str) -> str:
    return {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".md": "text/markdown", ".txt": "text/plain"}.get(extension, "application/octet-stream")
