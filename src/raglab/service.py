"""三个研发闭环的领域服务；API和Worker共用，全部资源显式限定workspace。"""
import io
import json
import math
import threading
import time
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from .chunking import chunk_document, presets
from .golden import GoldenItem
from .metrics import assemble, evidence_metrics, ranking_metrics, rrf
from .models import Ollama
from .parsing import parse_local, parse_ragflow
from .persistence import BlobStore, Store, digest, uid
from .retrieval import bm25


class Lab:
    def __init__(self, settings, embedder=None):
        self.settings = settings
        settings.storage.mkdir(parents=True, exist_ok=True)
        self.store = Store(settings.database_url, settings.vector_dim)
        self.blobs = BlobStore(settings.storage / "blobs", settings.max_file_bytes)
        self.embedder = embedder or Ollama(settings.ollama_url, settings.embed_model, settings.vector_dim)

    def _cached(self, kind, workspace, key, compute):
        old = self.store.by_key(kind, workspace, key)
        if old:
            return old["data"]
        value = compute()
        try:
            return self.store.create(kind, workspace, value, key)["data"]
        except IntegrityError:
            return self.store.by_key(kind, workspace, key)["data"]

    def create_kb(self, workspace, name):
        if not name.strip() or len(name) > 100:
            raise ValueError("知识库名称不能为空且不超过100字")
        return self.store.create("knowledge_base", workspace, {"name": name})

    def ingest(self, workspace, kb_id, name, stream, source, external_id, revision):
        self.store.get(kb_id, workspace, "knowledge_base")
        name = name.replace("\\", "/").split("/")[-1]
        if Path(name).suffix.lower() not in {".txt", ".md", ".docx", ".pdf"}:
            raise ValueError("不支持此文件类型")
        hash_ = self.blobs.put(stream)
        key = digest([kb_id, source, external_id, revision])
        data = {"kb_id": kb_id, "name": name, "hash": hash_, "source": source,
                "external_id": external_id, "source_revision": revision,
                "logical_key": digest([kb_id, source, external_id])}
        old = self.store.by_key("document", workspace, key)
        if old:
            if old["data"]["hash"] != hash_:
                raise ValueError("同一来源修订内容冲突")
            return old
        try:
            return self.store.create("document", workspace, data, key)
        except IntegrityError:
            old = self.store.by_key("document", workspace, key)
            if old["data"]["hash"] != hash_:
                raise ValueError("同一来源修订内容冲突") from None
            return old

    def documents(self, workspace, kb_id):
        self.store.get(kb_id, workspace, "knowledge_base")
        current = {}
        for row in self.store.list("document", workspace, limit=10000):
            if row["data"]["kb_id"] == kb_id:
                current.setdefault(row["data"]["logical_key"], row)
        return list(current.values())

    def parsed(self, workspace, document_id, parser):
        doc = self.store.get(document_id, workspace, "document")
        key = digest([document_id, doc["data"]["hash"], parser, "1", self.settings.ragflow_url])

        def compute():
            raw = self.blobs.read(doc["data"]["hash"])
            if parser == "local":
                return parse_local(doc["data"]["name"], raw, document_id)
            if parser == "ragflow":
                return parse_ragflow(doc["data"]["name"], raw, document_id,
                                     self.settings.ragflow_url, self.settings.ragflow_token)
            raise ValueError("未知解析器")

        return self._cached("parse_snapshot", workspace, key, compute)

    def _embed(self, workspace, texts, binding, role="document"):
        # 以实际输入和digest为缓存身份；不跨工作区复用。
        actual = [(binding.get("query_prefix", "") if role == "query" else "") + t for t in texts]
        keys = [digest([binding, role, t]) for t in actual]
        cached = [self.store.by_key("embedding", workspace, k) for k in keys]
        missing = list(dict.fromkeys(i for i, c in enumerate(cached) if c is None))
        for start in range(0, len(missing), 16):
            indexes = missing[start:start+16]
            vectors = self.embedder.embed([actual[i] for i in indexes], binding)
            for index, vector in zip(indexes, vectors, strict=True):
                if len(vector) != binding["dimension"] or not all(math.isfinite(x) for x in vector):
                    raise ValueError("模型向量数值不合法")
                value = self._cached("embedding", workspace, keys[index], lambda v=vector: {"vector": v})
                cached[index] = {"data": value}
        return [c["data"]["vector"] for c in cached]

    def _build_trial(self, workspace, kb_id, document_ids, parser, config, binding, key):
        old = self.store.by_key("trial", workspace, key)
        if old and old["data"]["status"] == "READY":
            return old
        data = {"kb_id": kb_id, "document_ids": document_ids, "parser": parser, "config": config,
                "model_binding": binding, "status": "BUILDING", "backend": "pgvector" if self.store.pg else "sqlite-test",
                "schema_version": 1, "config_hash": digest([config, binding, parser]), "chunker_version": "1.0"}
        trial = old or self.store.create("trial", workspace, data, key)
        chunks, snapshots = [], []
        for document_id in document_ids:
            doc = self.store.get(document_id, workspace, "document")
            if doc["data"]["kb_id"] != kb_id:
                raise ValueError("文档不属于目标知识库")
            parsed = self.parsed(workspace, document_id, parser)
            snapshots.append(digest(parsed))
            chunks.extend(chunk_document(parsed, **config))
        if not chunks or len(chunks) > 20000:
            raise ValueError("本地首期每个Trial要求1–20000个Chunk")
        vectors = self._embed(workspace, [c["text"] for c in chunks], binding)
        self.store.write_vectors(workspace, trial["id"], chunks, vectors)
        chunk_ref = self.blobs.put(io.BytesIO(json.dumps(chunks, ensure_ascii=False).encode()))
        data.update(status="READY", chunk_ref=chunk_ref, chunk_count=len(chunks),
                    parse_hashes=snapshots, manifest_hash=digest(document_ids),
                    average_length=sum(len(c["text"]) for c in chunks)/len(chunks))
        return self.store.replace(trial["id"], workspace, data)

    def chunks(self, workspace, trial_id):
        trial = self.store.get(trial_id, workspace, "trial")
        if trial["data"]["status"] != "READY":
            raise ValueError("索引尚未就绪")
        return json.loads(self.blobs.read(trial["data"]["chunk_ref"]))

    def _experiment(self, workspace, payload, key):
        self.store.get(payload["kb_id"], workspace, "knowledge_base")
        if not payload["document_ids"] or len(set(payload["document_ids"])) != len(payload["document_ids"]):
            raise ValueError("文档清单不能为空或重复")
        if not 1 <= len(payload["variants"]) <= 20:
            raise ValueError("参数扫描限1–20组")
        for variant in payload["variants"]:
            if variant["strategy"] not in {p["id"] for p in presets()} or not 1 <= variant["length"] <= 1600 or not 0 <= variant["overlap"] < variant["length"]:
                raise ValueError("切分参数无效")
        old = self.store.by_key("experiment", workspace, key)
        experiment = old or self.store.create("experiment", workspace, dict(payload, model_binding=self.embedder.binding()), key)
        binding = experiment["data"]["model_binding"]
        ids, errors = [], []
        for i, config in enumerate(payload["variants"]):
            try:
                trial = self._build_trial(workspace, payload["kb_id"], payload["document_ids"], payload["parser"],
                                          config, binding, digest([key, i]))
                ids.append(trial["id"])
            except (ValueError, http_error_types()) as exc:
                errors.append({"variant": i, "error": str(exc)[:500]})
        if not ids:
            self.store.replace(experiment["id"], workspace, dict(experiment["data"], errors=errors, status="FAILED"))
            raise ValueError("所有试验方案失败：" + errors[0]["error"])
        self.store.replace(experiment["id"], workspace, dict(experiment["data"], trial_ids=ids, errors=errors,
                                                            status="PARTIAL" if errors else "SUCCEEDED"))
        return {"id": experiment["id"], "trial_ids": ids, "errors": errors}

    def import_golden(self, workspace, kb_id, name, items):
        self.store.get(kb_id, workspace, "knowledge_base")
        try:
            validated = [GoldenItem.model_validate(item).model_dump() for item in items]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"黄金集条目格式错误：{exc}") from None
        items = validated
        if not items or len(items) > 5000:
            raise ValueError("黄金集要求1–5000题")
        ids = set()
        for i, item in enumerate(items, 1):
            if not item.get("id") or item["id"] in ids or not item.get("query", "").strip():
                raise ValueError(f"第{i}题ID重复或问题为空")
            ids.add(item["id"])
            if not isinstance(item.get("relevant_documents"), list):
                raise ValueError(f"第{i}题缺少相关文档数组")
            for doc_id in item["relevant_documents"]:
                try:
                    document = self.store.get(doc_id, workspace, "document")
                except KeyError:
                    raise ValueError(f"第{i}题引用文档不存在") from None
                if document["data"]["kb_id"] != kb_id:
                    raise ValueError(f"第{i}题文档不属于本知识库")
            for span in item.get("evidence", []):
                if span.get("document_id") not in item["relevant_documents"] or not isinstance(span.get("block_id"), str) or not isinstance(span.get("start"), int) or not isinstance(span.get("end"), int) or not 0 <= span["start"] < span["end"]:
                    raise ValueError(f"第{i}题证据区间不合法")
        return self.store.create("golden", workspace, {"kb_id": kb_id, "name": name,
                                 "items": items, "content_hash": digest(items), "schema_version": 1})

    def search(self, workspace, trial_id, query, top_k=5, budget=2000, mode="vector"):
        started = time.perf_counter()
        if not query.strip() or not 1 <= top_k <= 50 or not 1 <= budget <= 20000 or mode not in {"vector", "bm25", "hybrid"}:
            raise ValueError("检索参数无效")
        trial = self.store.get(trial_id, workspace, "trial")
        chunks = self.chunks(workspace, trial_id)
        vector_hits, lexical = [], []
        if mode in {"vector", "hybrid"}:
            vector = self._embed(workspace, [query], trial["data"]["model_binding"], "query")[0]
            vector_hits = self.store.search_vectors(workspace, trial_id, vector, 50)
        if mode in {"bm25", "hybrid"}:
            lexical = bm25(chunks, query, 50)
        candidates = rrf([vector_hits, lexical]) if mode == "hybrid" else (vector_hits if mode == "vector" else lexical)
        document_scores = {}
        for candidate in candidates:
            doc_id = candidate["document_id"]
            document_scores[doc_id] = max(document_scores.get(doc_id, float("-inf")), candidate["score"])
        document_ranking = sorted(document_scores, key=lambda doc_id: (-document_scores[doc_id], doc_id))[:top_k]
        hits = candidates[:top_k]
        context = assemble(hits, budget, "characters")
        return {"trial_id": trial_id, "query": query, "mode": mode, "hits": hits,
                "document_ranking": document_ranking, "context": context,
                "trace": {"vector_ids": [c["id"] for c in vector_hits], "bm25_ids": [c["id"] for c in lexical],
                          "model_digest": trial["data"]["model_binding"]["digest"]},
                "latency_ms": (time.perf_counter()-started)*1000}

    def _evaluate(self, workspace, payload):
        trial = self.store.get(payload["trial_id"], workspace, "trial")
        golden = self.store.get(payload["golden_id"], workspace, "golden")
        if golden["data"]["kb_id"] != trial["data"]["kb_id"]:
            raise ValueError("黄金集与索引不属于同一知识库")
        rows = []
        all_chunks = self.chunks(workspace, trial["id"])
        blocks = {}
        for doc_id in trial["data"]["document_ids"]:
            parsed = self.parsed(workspace, doc_id, trial["data"]["parser"])
            blocks.update({(doc_id, b["id"]): len(b["text"]) for b in parsed["blocks"]})
        for item in golden["data"]["items"]:
            error, trace = None, None
            try:
                if not set(item["relevant_documents"]) <= set(trial["data"]["document_ids"]):
                    raise ValueError("黄金文档版本不在该索引manifest中")
                for span in item.get("evidence", []):
                    if span["end"] > blocks.get((span["document_id"], span["block_id"]), -1):
                        raise ValueError("黄金证据无法精确对齐当前解析快照")
                trace = self.search(workspace, trial["id"], item["query"], payload.get("top_k", 5),
                                    payload.get("budget", 2000), payload.get("mode", "vector"))
                metrics = ranking_metrics(item["relevant_documents"], trace["document_ranking"], payload.get("top_k", 5))
                metrics.update(evidence_metrics(item.get("evidence", []), trace["context"]["spans"], trace["context"]["cost"]))
            except (ValueError, http_error_types()) as exc:
                error = str(exc)[:500]
                metrics = ranking_metrics(item["relevant_documents"], [], payload.get("top_k", 5))
                metrics.update(evidence_metrics(item.get("evidence", []), [], 0))
            rows.append({"query_id": item["id"], "query": item["query"], "metrics": metrics,
                         "error": error, "trace": trace})
        names = ["recall", "hit", "mrr", "ndcg", "evidence_recall", "evidence_precision", "evidence_iou", "effective_precision", "redundancy"]
        averages = {}
        for name in names:
            values = [r["metrics"][name] for r in rows if r["metrics"][name] is not None]
            averages[name] = sum(values)/len(values) if values else None
        latencies = sorted(r["trace"]["latency_ms"] for r in rows if r["trace"])
        averages["p95_ms"] = latencies[math.ceil(.95*len(latencies))-1] if latencies else None
        averages["error_rate"] = sum(bool(r["error"]) for r in rows)/len(rows)
        report = {"trial_id": trial["id"], "golden_id": golden["id"], "config": payload,
                  "metrics": averages, "items": rows, "metric_version": "1.0", "total": len(rows),
                  "chunk_count": len(all_chunks)}
        return self.store.create("evaluation", workspace, report)

    def _release(self, workspace, payload, key):
        kb = self.store.get(payload["kb_id"], workspace, "knowledge_base")
        source = self.store.get(payload["trial_id"], workspace, "trial")
        if source["data"]["kb_id"] != kb["id"]:
            raise ValueError("试验方案不属于目标知识库")
        existing = self.store.by_key("release", workspace, key)
        if existing:
            return existing
        # 重试必须复用同一完整语料manifest，不能把中途新增文件混入。
        manifest = self._cached("release_manifest", workspace, key, lambda: {
            "document_ids": [d["id"] for d in self.documents(workspace, kb["id"])]})
        trial = self._build_trial(workspace, kb["id"], manifest["document_ids"], source["data"]["parser"],
                                  source["data"]["config"], source["data"]["model_binding"], digest([key, "candidate"]))
        report = self._evaluate(workspace, {"trial_id": trial["id"], "golden_id": payload["golden_id"],
                                            "top_k": 5, "budget": 2000, "mode": "vector"})
        metrics = report["data"]["metrics"]
        threshold = payload.get("threshold", .8)
        if not 0 <= threshold <= 1:
            raise ValueError("发布门槛必须在0–1之间")
        passed = metrics["error_rate"] == 0 and metrics["recall"] is not None and metrics["recall"] >= threshold
        return self.store.create("release", workspace, {"kb_id": kb["id"], "trial_id": trial["id"],
                                 "golden_id": payload["golden_id"], "report_id": report["id"],
                                 "status": "READY" if passed else "REJECTED", "gate": {"passed": passed,
                                 "required_document_recall": threshold, "metrics": metrics},
                                 "manifest_hash": digest(manifest), "model_binding": trial["data"]["model_binding"],
                                 "previous_release_id": kb["data"]["active_release_id"]}, key)

    def activate(self, workspace, release_id, expected):
        release = self.store.get(release_id, workspace, "release")
        data = release["data"]
        if data["status"] != "READY" or not data["gate"]["passed"]:
            raise ValueError("候选版本未通过发布门槛")
        self.chunks(workspace, data["trial_id"])
        try:
            current = self.embedder.binding(data["model_binding"]["model"])
        except TypeError:
            current = self.embedder.binding()
        if current["digest"] != data["model_binding"]["digest"]:
            raise ValueError("旧版模型已不可用，不能发布或回滚")
        if not self.store.activate(data["kb_id"], workspace, release_id, expected):
            raise ValueError("发布冲突：当前活动版本已改变")
        self.store.create("audit", workspace, {"action": "activate", "release_id": release_id, "previous": expected})
        return {"release_id": release_id, "previous_release_id": expected}

    def search_active(self, workspace, kb_id, query):
        kb = self.store.get(kb_id, workspace, "knowledge_base")
        release_id = kb["data"]["active_release_id"]
        if not release_id:
            raise ValueError("知识库没有已发布版本")
        release = self.store.get(release_id, workspace, "release")
        return dict(self.search(workspace, release["data"]["trial_id"], query), release_id=release_id)

    def work_once(self):
        owner = uid()
        job = self.store.claim(owner)
        if not job:
            return False
        stopped = threading.Event()

        def heartbeat():
            while not stopped.wait(15):
                if not self.store.heartbeat(job["id"], owner, job["fence"]):
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            with self.store.job_scope(job["id"], owner, job["fence"]):
                if job["kind"] == "experiment":
                    result = self._experiment(job["workspace"], job["payload"], job["id"])
                elif job["kind"] == "evaluation":
                    result = self._evaluate(job["workspace"], job["payload"])["data"]
                elif job["kind"] == "release":
                    result = self._release(job["workspace"], job["payload"], job["id"])
                else:
                    raise ValueError("未知任务类型")
            self.store.finish(job["id"], owner, job["fence"], result=result)
        except Exception as exc:
            # 不返回连接串/响应URL等可能带凭据的异常；详细上下文由模块固定错误保存。
            error = str(exc)[:700] if isinstance(exc, (ValueError, KeyError)) else f"{type(exc).__name__}：依赖执行失败"
            try:
                self.store.finish(job["id"], owner, job["fence"], error=error)
            except ValueError:
                pass
        finally:
            stopped.set()
            thread.join(timeout=2)
        return True


def http_error_types():
    import httpx
    return httpx.HTTPError
