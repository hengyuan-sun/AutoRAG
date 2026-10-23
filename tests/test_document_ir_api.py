import io

from fastapi.testclient import TestClient
from test_service import TestEmbedder

from raglab.api import create_app
from raglab.config import Settings
from raglab.document_ir.models import DocumentIR, EngineRunInfo, FileMeta, ParagraphItem, Provenance
from raglab.service import Lab


class FakeIRParser:
    version = "fixture-ir@1"

    def parse(self, name, source, revision):
        return DocumentIR(
            meta=FileMeta(doc_id=revision, filename=name, sha256="a" * 64, size_bytes=7,
                          detected_format="txt", original_format="txt"),
            engine_info=EngineRunInfo(engine="fixture", engine_version="1", pages=1),
            items=[
                ParagraphItem(uid="ir_p1", type="paragraph", text="第一段😀", order=0,
                              provenance=Provenance(page=1, source="fixture")),
                ParagraphItem(uid="ir_p2", type="paragraph", text="第二段", order=1,
                              provenance=Provenance(page=1, source="fixture")),
            ],
            warnings=["fixture warning"], pages=[{"page": 1}],
        )


def make_client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'db'}", storage=tmp_path,
                        vector_dim=3, api_token="admin")
    lab = Lab(settings, TestEmbedder(), {"fixture": FakeIRParser()})
    client = TestClient(create_app(settings, lab, start_worker=False))
    client.headers["Authorization"] = "Bearer admin"
    kb = lab.create_kb("local", "IR")
    doc = lab.ingest("local", kb["id"], "source.txt", io.BytesIO(b"fixture"), "manual", "doc", "r1")
    return client, lab, doc


def test_ir_api_paginates_items_and_reports_stable_manifest(tmp_path):
    client, lab, doc = make_client(tmp_path)
    manifest = client.get(f"/api/v1/documents/{doc['id']}/ir?parser=fixture").json()
    assert manifest["schema_version"] == "1.5"
    assert manifest["item_count"] == 2 and manifest["page_count"] == 1
    assert manifest["artifact"]["sha256"] == manifest["ir_sha256"]
    assert "items" not in manifest
    page = client.get(f"/api/v1/documents/{doc['id']}/ir/items?parser=fixture&page=1&page_size=1&type=paragraph").json()
    assert page["total"] == 2 and page["page"] == 1
    assert [item["uid"] for item in page["items"]] == ["ir_p1"]
    assert page["ir_sha256"] == manifest["ir_sha256"]
    snapshot = lab.store.list("parse_snapshot", "local")[0]["data"]
    assert "items" not in snapshot and snapshot["ir_artifact"]["sha256"] == manifest["ir_sha256"]


def test_ir_item_api_returns_provenance_and_relations(tmp_path):
    client, _, doc = make_client(tmp_path)
    result = client.get(f"/api/v1/documents/{doc['id']}/ir/items/ir_p1?parser=fixture").json()
    assert result["item"]["text"] == "第一段😀"
    assert result["item"]["provenance"]["page"] == 1
    assert result["ir_sha256"]
    assert result["relations"] == []


def test_ir_api_rejects_cross_workspace_access_and_bounds_pages(tmp_path):
    client, lab, doc = make_client(tmp_path)
    other_kb = lab.create_kb("other", "private")
    other_doc = lab.ingest("other", other_kb["id"], "private.txt", io.BytesIO(b"private"),
                           "manual", "private", "r1")
    assert client.get(f"/api/v1/documents/{other_doc['id']}/ir?parser=fixture").status_code == 404
    assert client.get(f"/api/v1/documents/{doc['id']}/ir/items?parser=fixture&page_size=501").status_code == 422


def test_legacy_parsed_endpoint_projects_ir_to_blocks(tmp_path):
    client, _, doc = make_client(tmp_path)
    parsed = client.get(f"/api/v1/documents/{doc['id']}/parsed?parser=fixture").json()
    assert parsed["schema_version"] == "1.5"
    assert [block["text"] for block in parsed["blocks"]] == ["第一段😀", "第二段"]
    assert parsed["blocks"][0]["item_uid"] == "ir_p1"


def test_legacy_local_parsed_response_keeps_its_existing_shape(tmp_path):
    client, _, doc = make_client(tmp_path)
    parsed = client.get(f"/api/v1/documents/{doc['id']}/parsed?parser=local").json()
    assert parsed["parser"] == "local-baseline@2"
    assert parsed["blocks"][0]["text"] == "fixture"
    assert parsed["schema_version"] == 1
