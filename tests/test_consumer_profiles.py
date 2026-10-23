import json
from pathlib import Path

import pytest

from raglab.document_ir.consumer_profiles import ConsumerProfile, preview_profile
from raglab.document_ir.models import (
    DocumentIR,
    EngineRunInfo,
    FileMeta,
    ParagraphItem,
    Provenance,
    SourceSpan,
    TableCell,
    TableItem,
)


@pytest.fixture
def sample_ir():
    return DocumentIR(
        meta=FileMeta(doc_id="doc-1", filename="spec.md", sha256="a" * 64, size_bytes=10,
                      detected_format="md", original_format="md"),
        engine_info=EngineRunInfo(engine="fixture", engine_version="1"),
        items=[ParagraphItem(uid="ir_p1", type="paragraph", text="保养周期为12个月。", order=0,
                             provenance=Provenance(page=2, source_spans=[SourceSpan(start=3, end=14)])),
               ParagraphItem(uid="ir_p2", type="paragraph", text="到期前完成检查。", order=1,
                             provenance=Provenance(page=3))],
    )


def test_profile_rejects_unknown_selector_and_transform():
    with pytest.raises(ValueError):
        ConsumerProfile.model_validate({"id": "bad", "name": "bad", "fields": [
            {"key": "x", "selector": "items[*].__class__", "item_types": ["paragraph"]}]})
    with pytest.raises(ValueError):
        ConsumerProfile.model_validate({"id": "bad", "name": "bad", "fields": [
            {"key": "x", "selector": "items[*].text", "item_types": ["paragraph"],
             "transform": "python_eval"}]})
    with pytest.raises(ValueError):
        ConsumerProfile.model_validate({"id": "bad", "name": "bad", "fields": [
            {"key": "x", "selector": "items[*].table_markdown", "item_types": ["paragraph"]}]})


def test_profile_preview_emits_source_refs_for_each_value(sample_ir):
    profile = ConsumerProfile.model_validate({"id": "maintenance", "name": "保养字段", "fields": [
        {"key": "maintenance_rule", "selector": "items[*].text", "item_types": ["paragraph"],
         "cardinality": "many", "transform": "identity", "required": True}]})
    result = preview_profile(profile, sample_ir)
    values = result["fields"]["maintenance_rule"]["values"]
    assert [row["value"] for row in values] == ["保养周期为12个月。", "到期前完成检查。"]
    assert [row["source_uid"] for row in values] == ["ir_p1", "ir_p2"]
    assert values[0]["location"]["source_spans"][0] == {"start": 3, "end": 14, "unit": "char"}
    assert values[1]["location"]["page"] == 3


def test_profile_preview_handles_cell_values_and_cardinality(sample_ir):
    profile = ConsumerProfile.model_validate({"id": "meta", "name": "元信息", "fields": [
        {"key": "document_name", "selector": "meta.filename", "cardinality": "one"}]})
    result = preview_profile(profile, sample_ir)
    assert result["fields"]["document_name"]["values"] == [
        {"value": "spec.md", "source_uid": None, "location": None}]


def test_table_selectors_keep_cell_location_and_table_markdown(sample_ir):
    sample_ir.items.append(TableItem(uid="ir_table", type="table", order=2, table_markdown="| 名称 | 值 |",
                                     cells=[TableCell(uid="c1", text="压力", row=0, col=0),
                                            TableCell(uid="c2", text="12", row=0, col=1)]))
    profile = ConsumerProfile.model_validate({"id": "table", "name": "表格消费", "fields": [
        {"key": "headers", "selector": "items[*].cells[*].text", "item_types": ["table"],
         "cardinality": "many", "transform": "identity"},
        {"key": "table", "selector": "items[*].table_markdown", "item_types": ["table"],
         "cardinality": "many", "transform": "table_markdown"}]})
    result = preview_profile(profile, sample_ir)
    assert [row["value"] for row in result["fields"]["headers"]["values"]] == ["压力", "12"]
    assert all(row["source_uid"] == "ir_table" for row in result["fields"]["headers"]["values"])
    assert result["fields"]["table"]["values"][0]["value"] == "| 名称 | 值 |"


def test_consumer_profile_examples_validate_and_keep_wps_aliases():
    root = Path(__file__).parent / "fixtures" / "consumer_profiles"
    retrieval = ConsumerProfile.model_validate(json.loads((root / "retrieval.json").read_text(encoding="utf-8")))
    wps = json.loads((root / "wps_fields.json").read_text(encoding="utf-8"))
    profile = ConsumerProfile.model_validate(wps["profile"])
    assert retrieval.id == "general-retrieval"
    assert profile.fields[0].aliases == ["process"]
