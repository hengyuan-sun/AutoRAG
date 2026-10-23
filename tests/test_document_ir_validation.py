import pytest
from pydantic import ValidationError

from raglab.document_ir.models import DocumentIR
from raglab.document_ir.validation import validate_document_ir
from tests.test_document_ir_models import sample_ir


def test_ir_rejects_duplicate_uid_and_dangling_relation():
    payload = sample_ir()
    payload["items"].append({"uid": "p1", "type": "paragraph", "text": "重复"})
    payload["relations"][0]["target_uid"] = "missing"

    with pytest.raises(ValueError, match="p1.*duplicate"):
        validate_document_ir(DocumentIR.model_validate(payload))


def test_ir_rejects_invalid_cell_or_nonfinite_geometry():
    payload = sample_ir()
    payload["items"][2]["cells"][0]["row"] = 1
    with pytest.raises(ValueError, match="t1.*cell"):
        validate_document_ir(DocumentIR.model_validate(payload))

    payload = sample_ir()
    payload["items"][1]["provenance"]["locations"] = [
        {"page": 1, "bbox": [0, 0, float("inf"), 10]}
    ]
    with pytest.raises(ValidationError, match="bbox"):
        DocumentIR.model_validate(payload)


def test_ir_requires_engine_extensions_to_use_a_namespace():
    payload = sample_ir()
    payload["unscoped_docling_document"] = {"id": "x"}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DocumentIR.model_validate(payload)
