from raglab.document_ir.models import DocumentIR, EvidenceStatus, ItemKind


def sample_ir():
    return {
        "schema_version": "1.5",
        "meta": {
            "doc_id": "doc-1", "filename": "sample.docx", "sha256": "a" * 64,
            "size_bytes": 123, "detected_format": "docx", "original_format": "docx",
        },
        "engine_info": {"engine": "docling", "engine_version": "2.0"},
        "extensions": {"docling": {"document_hash": "d" * 64}},
        "outline": [{"title": "章节", "level": 1, "item_uids": ["h1"], "children": []}],
        "items": [
            {"uid": "h1", "type": "heading", "text": "章节", "level": 1, "status": "extracted"},
            {"uid": "p1", "type": "paragraph", "text": "正文内容", "status": "extracted",
             "provenance": {"source": "docling", "source_spans": [{"start": 0, "end": 4, "unit": "char"}]}},
            {"uid": "t1", "type": "table", "text": "", "n_rows": 1, "n_cols": 1,
             "cells": [{"uid": "c1", "text": "值", "row": 0, "col": 0, "is_header": True}],
             "table_markdown": "|值|"},
            {"uid": "i1", "type": "image", "filename": "image-1.png", "status": "unsupported"},
            {"uid": "f1", "type": "formula", "text": "x=1", "latex": "x=1"},
        ],
        "toc": [{"uid": "toc1", "type": "toc_entry", "text": "章节", "target_number": "1"}],
        "header_footer": [{"uid": "hf1", "type": "header_footer", "kind": "header", "text": "页眉"}],
        "relations": [{"source_uid": "p1", "target_uid": "t1", "kind": "references"}],
        "provider_snapshot": [{"provider": "docling", "version": "2.0", "execution_status": "invoked"}],
        "config_snapshot": {"pipeline": "standard"},
        "pages": [{"page": 1, "width": 612, "height": 792, "coordinate_unit": "pt",
                   "coordinate_origin": "top_left"}],
        "page_records": [{"uid": "page-1", "page": 1, "status": "extracted"}],
        "shards": [{"batch_id": 0, "artifact": {"uri": "blob:abc", "sha256": "b" * 64,
                    "size_bytes": 12}, "item_uids": ["p1"]}],
    }


def test_document_ir_v15_round_trips_core_item_kinds():
    ir = DocumentIR.model_validate(sample_ir())

    restored = DocumentIR.model_validate(ir.model_dump(mode="json"))

    assert restored.schema_version == "1.5"
    assert {item.type for item in restored.items} == {
        ItemKind.HEADING, ItemKind.PARAGRAPH, ItemKind.TABLE, ItemKind.IMAGE, ItemKind.FORMULA,
    }
    assert restored.toc[0].type == ItemKind.TOC_ENTRY
    assert restored.header_footer[0].type == ItemKind.HEADER_FOOTER
    assert restored.items[2].cells[0].uid == "c1"
    assert restored.provider_snapshot[0].provider == "docling"
    assert restored.shards[0].item_uids == ["p1"]
    assert restored.extensions["docling"]["document_hash"] == "d" * 64


def test_document_ir_keeps_source_location_and_evidence_status():
    payload = sample_ir()
    payload["items"][1]["provenance"]["locations"] = [
        {"page": 2, "bbox": [1.0, 2.0, 30.0, 40.0], "reading_order": 3}
    ]
    ir = DocumentIR.model_validate(payload)

    assert ir.items[1].provenance.locations[0].page == 2
    assert ir.items[1].provenance.locations[0].bbox == (1.0, 2.0, 30.0, 40.0)
    assert ir.items[3].status == EvidenceStatus.UNSUPPORTED
