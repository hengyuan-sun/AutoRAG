"""真实Ollama+PostgreSQL端到端验证，必须显式开启，绝不替换模型返回。"""
import io
import os

import pytest

from raglab.config import Settings
from raglab.persistence import uid
from raglab.service import Lab

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.getenv("RAGLAB_RUN_INTEGRATION") != "1",
                                                       reason="设置RAGLAB_RUN_INTEGRATION=1运行真实服务测试")]


def test_real_ollama_pgvector_complete_pipeline():
    lab = Lab(Settings())
    assert lab.store.pg
    workspace = "integration-" + uid()
    kb = lab.create_kb(workspace, "真实服务验证")
    document = lab.ingest(workspace, kb["id"], "温度.txt", io.BytesIO("焊接工艺温度保持80摄氏度，作业前完成安全检查。".encode()),
                          "integration", "temperature", "1")
    experiment_job = lab.store.enqueue(workspace, "experiment", {"kb_id": kb["id"],
                "document_ids": [document["id"]], "parser": "local", "variants": [
                    {"strategy": "recursive", "length": 100, "overlap": 0}]}, uid())
    assert lab.work_once()
    completed = lab.store.get_job(experiment_job["id"], workspace)
    assert completed["status"] == "SUCCEEDED", completed["error"]
    trial = completed["result"]["trial_ids"][0]
    result = lab.search(workspace, trial, "焊接温度是多少", 5, 1000, "hybrid")
    assert result["hits"][0]["document_id"] == document["id"]
    assert "80" in result["context"]["text"]
    assert not lab.store.search_vectors("not-authorized", trial, [0.0] * 1024, 5)
    golden = lab.import_golden(workspace, kb["id"], "真实黄金集", [{"id": "q1", "query": "焊接温度是多少",
                      "relevant_documents": [document["id"]], "evidence": [{"document_id": document["id"],
                       "block_id": "b0", "start": 0, "end": 15}]}])
    job = lab.store.enqueue(workspace, "release", {"kb_id": kb["id"], "trial_id": trial,
                  "golden_id": golden["id"], "threshold": 1}, uid())
    lab.work_once()
    done = lab.store.get_job(job["id"], workspace)
    assert done["status"] == "SUCCEEDED", done["error"]
    release = done["result"]
    assert release["data"]["gate"]["passed"]
    lab.activate(workspace, release["id"], None)
    assert lab.search_active(workspace, kb["id"], "温度")["release_id"] == release["id"]
    # 使用同一数据库新建Service，验证跨进程重启后台账和索引仍可查询。
    again = Lab(Settings())
    assert "80" in again.search_active(workspace, kb["id"], "焊接温度")["context"]["text"]
