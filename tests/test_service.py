import io
from pathlib import Path

import pytest

from raglab.config import Settings
from raglab.service import Lab


class TestEmbedder:
    """仅单元测试使用；生产始终调用真实Ollama。"""
    def binding(self, model_name=None):
        return {"model": "fixture", "digest": "fixed", "dimension": 3}

    def embed(self, texts, binding):
        return [[float("80" in t), float("安全" in t), 0.1] for t in texts]


@pytest.fixture
def lab(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'db'}", storage=tmp_path,
                        vector_dim=3, api_token="test")
    return Lab(settings, embedder=TestEmbedder())


def setup(lab):
    kb = lab.create_kb("w", "工艺库")
    doc = lab.ingest("w", kb["id"], "工艺.txt", io.BytesIO("温度80℃。安全检查合格。".encode()),
                     "manual", "工艺", "1")
    return kb, doc


def test_path_parser_receives_streamed_temp_file_and_cache_tracks_parser_version(lab):
    seen = []

    class PathAdapter:
        path_based = True
        version = "path-parser@1"

        def parse(self, name, source_path, revision):
            path = Path(source_path)
            seen.append((self.version, str(path), path.exists(), path.read_bytes(), path.suffix))
            return {"parser": self.version, "revision": revision, "blocks": []}

    kb, doc = setup(lab)
    lab.parser_adapters["path"] = PathAdapter()
    first = lab.parsed("w", doc["id"], "path")
    first_temp = seen[-1]
    assert first["parser"] == "path-parser@1"
    assert first_temp[2:4] == (True, "温度80℃。安全检查合格。".encode())
    assert not Path(first_temp[1]).exists()

    lab.parser_adapters["path"] = PathAdapter()
    lab.parser_adapters["path"].version = "path-parser@2"
    second = lab.parsed("w", doc["id"], "path")
    assert second["parser"] == "path-parser@2"
    assert len(seen) == 2
    assert not Path(seen[-1][1]).exists()


def test_docling_experiment_projects_ir_to_chunks_and_pins_parser_identity(lab):
    kb = lab.create_kb("w", "Docling知识库")
    doc = lab.ingest("w", kb["id"], "维修.md", io.BytesIO("# 安全检查\n\n检查阀门😀。".encode()),
                     "manual", "maintenance", "r1")
    job = lab.store.enqueue("w", "experiment", {
        "kb_id": kb["id"], "document_ids": [doc["id"]], "parser": "docling",
        "variants": [{"strategy": "window", "length": 100, "overlap": 0}],
    }, "docling-ir-trial")

    assert lab.work_once()
    result = lab.store.get_job(job["id"], "w")
    assert result["status"] == "SUCCEEDED", result.get("error")
    trial = lab.store.get(result["result"]["trial_ids"][0], "w", "trial")
    chunks = lab.chunks("w", trial["id"])
    assert trial["data"]["parser_identity"].startswith("docling@2.142.0")
    assert trial["data"]["parse_hashes"]
    assert [chunk["text"] for chunk in chunks] == ["安全检查", "检查阀门😀。"]
    assert all(chunk["spans"][0]["item_uid"].startswith("ir_") for chunk in chunks)
    assert chunks[1]["section_path"] == ["安全检查"]

    ir = lab.parsed("w", doc["id"], "docling")
    paragraph = next(item for item in ir["items"] if item["type"] == "paragraph")
    golden = lab.import_golden("w", kb["id"], "Docling证据", [{
        "id": "ir-evidence", "query": "阀门检查", "relevant_documents": [doc["id"]],
        "evidence": [{"document_id": doc["id"], "block_id": paragraph["uid"],
                      "start": 0, "end": len(paragraph["text"])}],
    }])
    report = lab._evaluate("w", {"trial_id": trial["id"], "golden_id": golden["id"],
                                  "top_k": 5, "budget": 1000, "mode": "bm25"})
    assert report["data"]["items"][0]["error"] is None


def test_ingest_idempotency_conflict_and_scope(lab):
    kb, doc = setup(lab)
    same = lab.ingest("w", kb["id"], "工艺.txt", io.BytesIO("温度80℃。安全检查合格。".encode()),
                      "manual", "工艺", "1")
    assert same["id"] == doc["id"]
    with pytest.raises(ValueError, match="修订"):
        lab.ingest("w", kb["id"], "工艺.txt", io.BytesIO(b"changed"), "manual", "工艺", "1")
    with pytest.raises(KeyError):
        lab.ingest("other", kb["id"], "x.txt", io.BytesIO(b"x"), "manual", "x", "1")


def run_job(lab, kind, payload, key):
    job = lab.store.enqueue("w", kind, payload, key)
    assert lab.work_once()
    result = lab.store.get_job(job["id"], "w")
    assert result["status"] == "SUCCEEDED", result.get("error")
    return result["result"]


def test_experiment_evaluation_release_rollback_closed_loop(lab):
    kb, doc = setup(lab)
    payload = {"kb_id": kb["id"], "document_ids": [doc["id"]], "parser": "local",
               "variants": [{"strategy": "window", "length": 100, "overlap": 0}]}
    exp = run_job(lab, "experiment", payload, "exp")
    trial = lab.store.get(exp["trial_ids"][0], "w", "trial")
    assert trial["data"]["status"] == "READY"
    search = lab.search("w", trial["id"], "温度80", 5, 100, "vector")
    assert search["hits"][0]["document_id"] == doc["id"]
    golden = lab.import_golden("w", kb["id"], "验证", [{"id": "q1", "query": "温度80", "relevant_documents": [doc["id"]]}])
    evaluation = run_job(lab, "evaluation", {"trial_id": trial["id"], "golden_id": golden["id"],
                         "top_k": 5, "budget": 100, "mode": "vector"}, "eval")
    assert evaluation["metrics"]["recall"] == 1
    release = run_job(lab, "release", {"kb_id": kb["id"], "trial_id": trial["id"],
                      "golden_id": golden["id"], "threshold": .8}, "release")
    active = lab.activate("w", release["id"], None)
    assert active["release_id"] == release["id"]
    with pytest.raises(ValueError, match="冲突"):
        lab.activate("w", release["id"], None)
    assert lab.search_active("w", kb["id"], "温度80")["release_id"] == release["id"]
    with pytest.raises(KeyError):
        lab.search("other", trial["id"], "x", 5, 100, "vector")


def test_missing_golden_and_unknown_parser_fail_closed(lab):
    kb, doc = setup(lab)
    job = lab.store.enqueue("w", "experiment", {"kb_id": kb["id"], "document_ids": [doc["id"]],
              "parser": "unconfigured", "variants": [{"strategy": "window", "length": 100, "overlap": 0}]}, "bad")
    lab.work_once()
    assert lab.store.get_job(job["id"], "w")["status"] == "FAILED"
    assert not lab.store.get(kb["id"], "w")["data"]["active_release_id"]


def test_release_builds_complete_corpus_and_gates_candidate(lab):
    kb, doc = setup(lab)
    exp = run_job(lab, "experiment", {"kb_id": kb["id"], "document_ids": [doc["id"]], "parser": "local",
                  "variants": [{"strategy": "recursive", "length": 100, "overlap": 0}]}, "ex")
    more = lab.ingest("w", kb["id"], "安全.txt", io.BytesIO("安全要求必须佩戴护具。".encode()), "manual", "安全", "1")
    golden = lab.import_golden("w", kb["id"], "all", [{"id": "q", "query": "安全", "relevant_documents": [more["id"]]}])
    release = run_job(lab, "release", {"kb_id": kb["id"], "trial_id": exp["trial_ids"][0],
                      "golden_id": golden["id"], "threshold": .8}, "r")
    candidate = lab.store.get(release["data"]["trial_id"], "w")
    assert set(candidate["data"]["document_ids"]) == {doc["id"], more["id"]}


def test_invalid_golden_does_not_silently_pass(lab):
    kb, _ = setup(lab)
    with pytest.raises(ValueError):
        lab.import_golden("w", kb["id"], "invalid", [{"id": "q", "query": "x", "relevant_documents": ["missing"]}])
