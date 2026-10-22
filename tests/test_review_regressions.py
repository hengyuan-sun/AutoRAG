import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from test_service import TestEmbedder, run_job, setup

from raglab.api import create_app
from raglab.config import Settings
from raglab.models import Ollama
from raglab.service import Lab


@pytest.fixture
def lab(tmp_path):
    return Lab(Settings(database_url=f"sqlite:///{tmp_path / 'db'}", storage=tmp_path,
                        vector_dim=3, api_token="admin"), TestEmbedder())


@pytest.mark.parametrize("bad", [
    {"id": "q", "query": None, "relevant_documents": []},
    {"id": ["q"], "query": "x", "relevant_documents": []},
    {"id": "q", "query": "x", "relevant_documents": [], "evidence": None},
    {"id": "q", "query": "x", "relevant_documents": [], "evidence": [None]},
])
def test_malformed_golden_is_422_not_500(lab, bad):
    kb = lab.create_kb("local", "invalid")
    with TestClient(create_app(lab.settings, lab, start_worker=False), raise_server_exceptions=False) as c:
        result = c.post("/api/v1/golden-datasets", headers={"Authorization": "Bearer admin"},
                        json={"name": "bad", "kb_id": kb["id"], "items": [bad]})
        assert result.status_code == 422


def test_default_model_change_does_not_break_existing_binding(monkeypatch):
    original = httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "old", "digest": "old-digest"},
                                                        {"name": "new", "digest": "new-digest"}]})
        return httpx.Response(200, json={"embeddings": [[1, 0, 0]]})

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler)))
    model = Ollama("http://ollama", "new", 3)
    assert model.embed(["x"], {"model": "old", "digest": "old-digest", "dimension": 3}) == [[1, 0, 0]]
    assert len(requests) == 2


def test_document_topk_aggregates_before_cutting(lab, monkeypatch):
    kb, doc = setup(lab)
    result = run_job(lab, "experiment", {"kb_id": kb["id"], "document_ids": [doc["id"]], "parser": "local",
                     "variants": [{"strategy": "window", "length": 100, "overlap": 0}]}, "x")
    trial = result["trial_ids"][0]
    hits = [{"id": str(i), "document_id": "a", "text": "x", "spans": [], "score": 1} for i in range(5)]
    hits.append({"id": "b", "document_id": "b", "text": "y", "spans": [], "score": .5})
    monkeypatch.setattr(lab.store, "search_vectors", lambda *args: hits)
    found = lab.search("w", trial, "x", 2, 100, "vector")
    assert found["document_ranking"] == ["a", "b"]
    assert len(found["hits"]) == 2  # 块级TopK保持原意义；文档指标另用聚合排名。


def test_old_worker_cannot_commit_outputs_after_lease_loss(lab):
    job = lab.store.enqueue("w", "evaluation", {}, "lease")
    old = lab.store.claim("old")
    with lab.store.engine.begin() as c:
        c.execute(update(lab.store.jobs).where(lab.store.jobs.c.id == job["id"]).values(lease=time.time()-1))
    current = lab.store.claim("new")
    assert current["fence"] == old["fence"]+1
    with lab.store.job_scope(job["id"], "old", old["fence"]):
        with pytest.raises(ValueError, match="租约"):
            lab.store.create("evaluation", "w", {"bad": True})
        with pytest.raises(ValueError, match="租约"):
            lab.store.write_vectors("w", "index", [], [])
    assert not lab.store.list("evaluation", "w")
