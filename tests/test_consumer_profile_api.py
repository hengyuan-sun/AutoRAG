import io

from fastapi.testclient import TestClient
from test_service import TestEmbedder

from raglab.api import create_app
from raglab.config import Settings
from raglab.document_ir.models import DocumentIR, EngineRunInfo, FileMeta, ParagraphItem, Provenance
from raglab.service import Lab


class ProfileIRParser:
    version = "profile-ir@1"

    def parse(self, name, source, revision):
        return DocumentIR(meta=FileMeta(doc_id=revision, filename=name, sha256="b" * 64, size_bytes=5,
                                        detected_format="txt", original_format="txt"),
                          engine_info=EngineRunInfo(engine="fixture", engine_version="1"),
                          items=[ParagraphItem(uid="ir_rule", type="paragraph", text="按月检查。", order=0,
                                               provenance=Provenance(page=1))])


def setup_client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'db'}", storage=tmp_path,
                        vector_dim=3, api_token="admin")
    lab = Lab(settings, TestEmbedder(), {"fixture": ProfileIRParser()})
    client = TestClient(create_app(settings, lab, start_worker=False))
    client.headers["Authorization"] = "Bearer admin"
    kb = lab.create_kb("local", "字段消费")
    doc = lab.ingest("local", kb["id"], "procedure.txt", io.BytesIO(b"rule"), "manual", "r", "r1")
    return client, lab, kb, doc


def profile_payload(profile_id=None):
    return {"id": profile_id, "name": "检索字段", "fields": [
        {"key": "content", "selector": "items[*].text", "item_types": ["paragraph"],
         "cardinality": "many", "transform": "identity"}]}


def test_profile_api_versions_profiles_and_preview_with_provenance(tmp_path):
    client, lab, _, doc = setup_client(tmp_path)
    first = client.post("/api/v1/consumer-profiles", json=profile_payload())
    assert first.status_code == 201, first.text
    p1 = first.json()
    assert p1["version"] == 1 and p1["content_hash"]
    second = client.post("/api/v1/consumer-profiles", json=profile_payload(p1["id"]))
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2
    assert client.get(f"/api/v1/consumer-profiles/{p1['id']}?version=1").json()["version"] == 1
    latest = {profile["id"]: profile for profile in client.get("/api/v1/consumer-profiles").json()}
    assert latest[p1["id"]]["version"] == 2
    preview = client.post(f"/api/v1/documents/{doc['id']}/consumer-preview?parser=fixture",
                          json={"profile_id": p1["id"], "version": 1})
    assert preview.status_code == 200, preview.text
    value = preview.json()["fields"]["content"]["values"][0]
    assert value["value"] == "按月检查。" and value["source_uid"] == "ir_rule"
    assert value["location"]["page"] == 1
    assert lab.store.list("consumer_profile", "local")


def test_profile_api_rejects_invalid_selector_and_cross_workspace_profile(tmp_path):
    client, lab, _, _ = setup_client(tmp_path)
    invalid = client.post("/api/v1/consumer-profiles", json={"name": "bad", "fields": [
        {"key": "x", "selector": "items[*].provenance.__dict__"}]})
    assert invalid.status_code == 422
    foreign = lab.save_consumer_profile("other", profile_payload())
    assert client.get(f"/api/v1/consumer-profiles/{foreign['id']}").status_code == 404


def test_experiment_pins_consumer_profile_version_and_hash(tmp_path):
    client, lab, kb, doc = setup_client(tmp_path)
    profile = client.post("/api/v1/consumer-profiles", json=profile_payload()).json()
    job = client.post("/api/v1/experiments", json={
        "kb_id": kb["id"], "document_ids": [doc["id"]], "parser": "local",
        "consumer_profile_id": profile["id"],
        "variants": [{"strategy": "recursive", "length": 100, "overlap": 0}],
    })
    assert job.status_code == 202, job.text
    updated = client.post("/api/v1/consumer-profiles", json=profile_payload(profile["id"]))
    assert updated.status_code == 201 and updated.json()["version"] == 2
    lab.work_once()
    result = client.get(f"/api/v1/jobs/{job.json()['id']}").json()
    assert result["status"] == "SUCCEEDED", result.get("error")
    trial = lab.store.get(result["result"]["trial_ids"][0], "local", "trial")
    pinned = trial["data"]["consumer_profile"]
    assert pinned["id"] == profile["id"] and pinned["version"] == 1
    assert pinned["content_hash"] == profile["content_hash"]
