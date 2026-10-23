import pytest
from fastapi.testclient import TestClient
from test_service import TestEmbedder

from raglab.api import ExperimentBody, create_app
from raglab.config import Settings
from raglab.service import Lab


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'db'}", storage=tmp_path,
                        vector_dim=3, api_token="admin", viewer_token="viewer")
    lab = Lab(settings, TestEmbedder())
    with TestClient(create_app(settings, lab, start_worker=False)) as c:
        yield c, lab


def test_auth_scope_and_read_only_role(client):
    c, lab = client
    assert c.get("/api/v1/knowledge-bases").status_code == 401
    assert c.post("/api/v1/knowledge-bases", json={"name": "x"}, headers={"Authorization": "Bearer viewer"}).status_code == 403
    assert c.get("/api/v1/knowledge-bases", headers={"Authorization": "Bearer viewer"}).status_code == 200
    other = lab.create_kb("other", "hidden")
    assert c.get(f"/api/v1/knowledge-bases/{other['id']}/documents", headers={"Authorization": "Bearer admin"}).status_code == 404


def test_http_closed_loop_and_job_errors(client):
    c, lab = client
    c.headers["Authorization"] = "Bearer admin"
    kb = c.post("/api/v1/knowledge-bases", json={"name": "测试库"}).json()
    doc = c.post("/api/v1/ingestions", data={"kb_id": kb["id"]},
                 files={"file": ("工艺.txt", "温度80℃。".encode())}).json()
    assert doc["data"]["name"] == "工艺.txt"
    payload = {"kb_id": kb["id"], "document_ids": [doc["id"]], "parser": "local",
               "variants": [{"strategy": "window", "length": 100, "overlap": 0}]}
    job = c.post("/api/v1/experiments", json=payload, headers={"Idempotency-Key": "same"})
    assert job.status_code == 202
    assert c.post("/api/v1/experiments", json=payload, headers={"Idempotency-Key": "same"}).json()["id"] == job.json()["id"]
    lab.work_once()
    done = c.get(f"/api/v1/jobs/{job.json()['id']}").json()
    assert done["status"] == "SUCCEEDED"
    trial = done["result"]["trial_ids"][0]
    assert c.get(f"/api/v1/trials/{trial}/chunks").json()["items"]
    assert c.post("/api/v1/search", json={"trial_id": trial, "query": "温度", "mode": "hybrid"}).status_code == 200
    golden = c.post("/api/v1/golden-datasets", json={"kb_id": kb["id"], "name": "gold",
             "items": [{"id": "q", "query": "温度80", "relevant_documents": [doc["id"]]}]}).json()
    release_job = c.post("/api/v1/release-builds", json={"kb_id": kb["id"], "trial_id": trial,
                         "golden_id": golden["id"]}).json()
    lab.work_once()
    release = c.get(f"/api/v1/jobs/{release_job['id']}").json()["result"]
    assert c.post(f"/api/v1/releases/{release['id']}/activate", json={"expected_release_id": None}).status_code == 200
    assert c.post("/api/v1/search", json={"kb_id": kb["id"], "query": "温度"}).json()["release_id"] == release["id"]
    assert c.post("/api/v1/experiments", json=dict(payload, variants=[])).status_code == 422
    assert c.post("/api/v1/experiments", json=dict(payload, variants=[
        {"strategy": "table", "length": 100, "overlap": 1}])).status_code == 422
    bad = c.post("/api/v1/ingestions", data={"kb_id": kb["id"]}, files={"file": ("x.exe", b"MZ")})
    assert bad.status_code == 422


def test_raw_file_stream_and_json_dataset_validation(client):
    c, _ = client
    c.headers["Authorization"] = "Bearer admin"
    kb = c.post("/api/v1/knowledge-bases", json={"name": "流"}).json()
    response = c.post(f"/api/v1/ingestions/raw?kb_id={kb['id']}&file_name=stream.txt", content=b"hello",
                      headers={"Content-Type": "application/octet-stream"})
    assert response.status_code == 201
    assert c.post("/api/v1/golden-datasets", json={"kb_id": kb["id"], "name": "bad", "items": []}).status_code == 422


def test_multipart_upload_uses_configured_single_file_limit(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'small.db'}", storage=tmp_path,
                        vector_dim=3, api_token="admin", max_file_bytes=4)
    lab = Lab(settings, TestEmbedder())
    with TestClient(create_app(settings, lab, start_worker=False)) as c:
        c.headers["Authorization"] = "Bearer admin"
        kb = c.post("/api/v1/knowledge-bases", json={"name": "size"}).json()
        ok = c.post("/api/v1/ingestions", data={"kb_id": kb["id"]}, files={"file": ("ok.txt", b"1234")})
        too_large = c.post("/api/v1/ingestions", data={"kb_id": kb["id"]}, files={"file": ("large.txt", b"12345")})
        raw_too_large = c.post(f"/api/v1/ingestions/raw?kb_id={kb['id']}&file_name=large.txt",
                               content=b"12345", headers={"Content-Type": "application/octet-stream"})
        assert ok.status_code == 201
        assert too_large.status_code == 413
        assert raw_too_large.status_code == 413


def test_default_file_limit_is_500_mib():
    assert Settings().max_file_bytes == 500 * 1024 * 1024


def test_new_experiments_default_to_docling_parser():
    body = ExperimentBody.model_validate({"kb_id": "kb", "document_ids": ["doc"],
                                          "variants": [{"strategy": "recursive"}]})
    assert body.parser == "docling"


def test_default_docling_experiment_runs_through_ir_chunk_projection(client):
    c, lab = client
    c.headers["Authorization"] = "Bearer admin"
    kb = c.post("/api/v1/knowledge-bases", json={"name": "Docling默认链路"}).json()
    doc = c.post("/api/v1/ingestions", data={"kb_id": kb["id"]},
                 files={"file": ("maintenance.md", "# 保养\n\n检查压力值。".encode())}).json()
    queued = c.post("/api/v1/experiments", json={
        "kb_id": kb["id"], "document_ids": [doc["id"]],
        "variants": [{"strategy": "window", "length": 100, "overlap": 0}],
    })
    assert queued.status_code == 202
    lab.work_once()

    job = c.get(f"/api/v1/jobs/{queued.json()['id']}").json()
    assert job["status"] == "SUCCEEDED", job.get("error")
    trial_id = job["result"]["trial_ids"][0]
    trial = lab.store.get(trial_id, "local", "trial")
    chunks = c.get(f"/api/v1/trials/{trial_id}/chunks").json()["items"]
    assert trial["data"]["parser"] == "docling"
    assert trial["data"]["parse_schema_versions"] == ["1.5"]
    assert trial["data"]["parser_identity"].startswith("docling@2.142.0")
    assert chunks
    assert all(chunk["spans"][0]["item_uid"].startswith("ir_") for chunk in chunks)


def test_presets_api_exposes_strategy_specific_labels(client):
    c, _ = client
    c.headers["Authorization"] = "Bearer admin"
    rows = {row["id"]: row for row in c.get("/api/v1/presets").json()}
    assert rows["recursive"]["length_label"] == "单块最大长度（字符）"
    assert rows["window"]["length_label"] == "固定窗口长度（字符）"
    assert rows["table"]["overlap_supported"] is False
