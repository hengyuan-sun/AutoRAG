"""Validated, non-executable field selection over canonical DocumentIR."""
from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    DocumentIR,
    HeaderFooterItem,
    HeadingItem,
    ImageItem,
    ItemKind,
    ParagraphItem,
    Provenance,
    TableCell,
    TableItem,
    TocEntryItem,
)

_ITEM_TYPES = {kind.value for kind in ItemKind}
_ITEM_MODELS = (HeadingItem, ParagraphItem, TableItem, ImageItem, TocEntryItem, HeaderFooterItem)
_ITEM_FIELDS = set().union(*(model.model_fields for model in _ITEM_MODELS))
_ITEM_MODEL_BY_TYPE = {get_args(model.model_fields["type"].annotation)[0]: model for model in _ITEM_MODELS}


class ConsumerField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    selector: str = Field(min_length=1, max_length=160)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    item_types: list[str] = Field(default_factory=list, max_length=7)
    cardinality: Literal["one", "many"] = "many"
    transform: Literal["identity", "join_text", "table_markdown"] = "identity"
    required: bool = False

    @field_validator("item_types")
    @classmethod
    def known_item_types(cls, value):
        if len(set(value)) != len(value) or any(item_type not in _ITEM_TYPES for item_type in value):
            raise ValueError("item_types包含未知或重复类型")
        return value

    @field_validator("aliases")
    @classmethod
    def unique_aliases(cls, value):
        if len(set(value)) != len(value) or any(not alias.strip() for alias in value):
            raise ValueError("aliases不能重复或为空")
        return value

    @model_validator(mode="after")
    def safe_selector(self):
        _validate_selector(self.selector, self.item_types)
        if self.transform == "table_markdown" and (not self.item_types or set(self.item_types) != {"table"}):
            raise ValueError("table_markdown转换仅适用于table条目")
        return self


class ConsumerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1)
    schema_version: Literal["1.5"] = "1.5"
    fields: list[ConsumerField] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_field_keys(self):
        keys = [field.key for field in self.fields]
        if len(set(keys)) != len(keys):
            raise ValueError("Consumer Profile字段key不能重复")
        return self


def _validate_selector(selector: str, item_types: list[str]):
    parts = selector.split(".")
    allowed = False
    if len(parts) == 2 and parts[0] == "meta":
        from .models import FileMeta
        allowed = parts[1] in FileMeta.model_fields
    elif len(parts) == 2 and parts[0] == "outline[*]":
        from .models import OutlineNode
        allowed = parts[1] in OutlineNode.model_fields and parts[1] not in {"children"}
    elif len(parts) == 2 and parts[0] == "items[*]":
        allowed = parts[1] in _ITEM_FIELDS and parts[1] not in {"provenance", "cells"}
        if allowed:
            chosen_types = item_types or list(_ITEM_TYPES)
            allowed = all(parts[1] in _ITEM_MODEL_BY_TYPE[item_type].model_fields
                          for item_type in chosen_types)
    elif len(parts) == 3 and parts[:2] == ["items[*]", "provenance"]:
        allowed = parts[2] in Provenance.model_fields
    elif len(parts) == 3 and parts[:2] == ["items[*]", "cells[*]"]:
        allowed = parts[2] in TableCell.model_fields
    if not allowed:
        raise ValueError("selector不在支持的DocumentIR字段路径白名单中")
    if selector.startswith("items[*].cells[*].") and item_types and "table" not in item_types:
        raise ValueError("cells选择器要求item_types包含table")


def preview_profile(profile: ConsumerProfile, ir: DocumentIR):
    if ir.schema_version != profile.schema_version:
        raise ValueError(f"Profile schema {profile.schema_version} 与DocumentIR {ir.schema_version}不兼容")
    fields = {}
    missing_required = []
    for selection in profile.fields:
        selected = _select(selection, ir)
        values = [{"value": _transform(selection.transform, raw, item),
                   "source_uid": source_uid, "location": location}
                  for raw, source_uid, location, item in selected]
        if selection.cardinality == "one" and len(values) > 1:
            raise ValueError(f"字段{selection.key}声明为one但选择到多个值")
        status = "extracted" if values else ("failed" if selection.required else "empty_in_source")
        if selection.required and not values:
            missing_required.append(selection.key)
        fields[selection.key] = {"selector": selection.selector, "aliases": selection.aliases,
                                 "status": status,
                                 "values": values, "required": selection.required}
    return {"profile_id": profile.id, "profile_version": profile.version,
            "schema_version": ir.schema_version, "fields": fields,
            "missing_required": missing_required}


def _select(selection: ConsumerField, ir: DocumentIR):
    path = selection.selector.split(".")
    if path[0] == "meta":
        return [(getattr(ir.meta, path[1]), None, None, None)]
    if path[0] == "outline[*]":
        rows = []
        for node in _walk_outline(ir.outline):
            source_uid = node.item_uids[0] if node.item_uids else None
            item = ir.by_uid(source_uid) if source_uid else None
            location = _item_location(item) if item else None
            rows.append((getattr(node, path[1]), source_uid, location, item))
        return rows

    items = [item for item in [*ir.items, *ir.toc, *ir.header_footer]
             if not selection.item_types or item.type in selection.item_types]
    if path[1] == "provenance":
        return [(getattr(item.provenance, path[2]), item.uid, _item_location(item), item)
                for item in items]
    if path[1] == "cells[*]":
        result = []
        for item in items:
            if not isinstance(item, TableItem):
                continue
            for cell in sorted(item.cells, key=lambda value: (value.row, value.col)):
                location = (cell.provenance.model_dump(mode="json", exclude_none=True)
                            if cell.provenance else None)
                if location is not None and cell.source_spans:
                    location["source_spans"] = [span.model_dump(mode="json", exclude_none=True)
                                                for span in cell.source_spans]
                result.append((getattr(cell, path[2]), item.uid, location, item))
        return result
    return [(getattr(item, path[1]), item.uid, _item_location(item), item) for item in items]


def _item_location(item):
    return item.provenance.model_dump(mode="json", exclude_none=True)


def _walk_outline(nodes):
    for node in nodes:
        yield node
        yield from _walk_outline(node.children)


def _transform(transform, value, item):
    if transform == "identity":
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", exclude_none=True)
        if isinstance(value, list):
            return [entry.model_dump(mode="json", exclude_none=True) if hasattr(entry, "model_dump") else entry
                    for entry in value]
        return value
    if transform == "join_text":
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return "\n".join(str(entry) for entry in value if entry is not None)
        return str(value)
    if transform == "table_markdown":
        if not isinstance(item, TableItem):
            return ""
        if item.table_markdown:
            return item.table_markdown
        if item.linearized_rows:
            return "\n".join(item.linearized_rows)
        rows = {}
        for cell in item.cells:
            rows.setdefault(cell.row, []).append(cell)
        return "\n".join(" | ".join(cell.text for cell in sorted(cells, key=lambda cell: cell.col))
                         for _, cells in sorted(rows.items()))
    raise ValueError(f"不支持的转换：{transform}")


def builtin_profile_templates():
    """Small, versioned starter profiles; values are selectors, never document data."""
    return [
        {"id": "general-retrieval", "name": "通用检索文本", "schema_version": "1.5", "version": 1,
         "fields": [
             {"key": "content", "selector": "items[*].text",
              "item_types": ["heading", "paragraph", "table"], "cardinality": "many",
              "transform": "identity", "required": True},
             {"key": "section_path", "selector": "items[*].chapter_path",
              "item_types": ["heading", "paragraph", "table"], "cardinality": "many",
              "transform": "join_text"},
             {"key": "source_page", "selector": "items[*].provenance.page",
              "item_types": ["heading", "paragraph", "table"], "cardinality": "many",
              "transform": "identity"},
         ]},
        {"id": "structured-review", "name": "结构化审查", "schema_version": "1.5", "version": 1,
         "fields": [
             {"key": "review_text", "selector": "items[*].text", "item_types": ["paragraph"],
              "cardinality": "many", "transform": "identity", "required": True},
             {"key": "table_content", "selector": "items[*].table_markdown", "item_types": ["table"],
              "cardinality": "many", "transform": "table_markdown"},
             {"key": "source_evidence", "selector": "items[*].provenance.source_spans",
              "item_types": ["paragraph", "table"], "cardinality": "many", "transform": "identity"},
         ]},
        {"id": "wps-field-alias-example", "name": "WPS字段别名示例", "schema_version": "1.5", "version": 1,
         "fields": [
             {"key": "process_text", "aliases": ["process"], "selector": "items[*].text",
              "item_types": ["paragraph"], "cardinality": "many", "transform": "identity"},
             {"key": "weld_identifier_text", "aliases": ["weld_no"], "selector": "items[*].text",
              "item_types": ["paragraph"], "cardinality": "many", "transform": "identity"},
             {"key": "layer_text", "aliases": ["pass_or_layer"], "selector": "items[*].text",
              "item_types": ["paragraph"], "cardinality": "many", "transform": "identity"},
         ]},
    ]
