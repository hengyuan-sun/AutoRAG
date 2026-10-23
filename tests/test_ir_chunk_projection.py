from raglab.chunking import chunk_document
from raglab.document_ir.chunk_projection import to_chunking_document
from raglab.document_ir.models import DocumentIR


def test_projection_preserves_ir_uids_and_heading_context():
    ir = DocumentIR.model_validate({
        "meta": {"doc_id": "source", "filename": "guide.docx", "sha256": "a" * 64,
                 "size_bytes": 20, "detected_format": "docx", "original_format": "docx"},
        "engine_info": {"engine": "docling", "engine_version": "2.142.0"},
        "items": [
            {"uid": "h1", "type": "heading", "text": "安全检查", "level": 1},
            {"uid": "p1", "type": "paragraph", "text": "检查阀门状态。",
             "chapter_path": ["安全检查"], "provenance": {"source": "docling",
             "locations": [{"page": 2, "bbox": [10, 20, 40, 50]}]}},
        ],
    })

    document = to_chunking_document(ir, "platform-doc-id")

    assert document["revision"] == "platform-doc-id"
    assert [block["id"] for block in document["blocks"]] == ["h1", "p1"]
    assert document["blocks"][1]["section_path"] == ["安全检查"]
    assert document["blocks"][1]["page"] == 2
    assert document["blocks"][1]["bbox"] == [10, 20, 40, 50]


def test_table_cells_keep_row_column_source_refs():
    ir = DocumentIR.model_validate({
        "meta": {"doc_id": "source", "filename": "table.docx", "sha256": "b" * 64,
                 "size_bytes": 20, "detected_format": "docx", "original_format": "docx"},
        "engine_info": {"engine": "docling", "engine_version": "2.142.0"},
        "items": [{"uid": "t1", "type": "table", "n_rows": 2, "n_cols": 2,
                   "cells": [{"uid": "c00", "row": 0, "col": 0, "text": "项目"},
                             {"uid": "c01", "row": 0, "col": 1, "text": "限值"},
                             {"uid": "c10", "row": 1, "col": 0, "text": "压力"},
                             {"uid": "c11", "row": 1, "col": 1, "text": "0.8MPa"}]}],
    })

    block = to_chunking_document(ir, "doc")["blocks"][0]

    assert block["type"] == "table"
    assert block["rows"] == ["项目 | 限值", "压力 | 0.8MPa"]
    assert block["cell_spans"][-1] == {"item_uid": "t1", "cell_uid": "c11", "row": 1,
                                      "col": 1, "start": 13, "end": 19}


def test_chunk_spans_round_trip_to_exact_ir_text():
    source_text = "温度😀保持"
    ir = DocumentIR.model_validate({
        "meta": {"doc_id": "source", "filename": "unicode.md", "sha256": "c" * 64,
                 "size_bytes": 20, "detected_format": "md", "original_format": "md"},
        "engine_info": {"engine": "docling", "engine_version": "2.142.0"},
        "items": [{"uid": "p-unicode", "type": "paragraph", "text": source_text,
                   "provenance": {"locations": [{"page": 1, "bbox": [1, 2, 3, 4]}]}}],
    })
    document = to_chunking_document(ir, "doc")

    chunks = chunk_document(document, "window", 3, 0)

    assert "".join(chunk["text"] for chunk in chunks) == source_text
    for chunk in chunks:
        span = chunk["spans"][0]
        assert span["item_uid"] == "p-unicode"
        assert source_text[span["start"]:span["end"]] == chunk["text"]
        assert span["page"] == 1
        assert span["bbox"] == [1, 2, 3, 4]
