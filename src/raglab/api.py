"""有鉴权的研发API。内嵌Worker供单机使用，可关闭并运行独立worker进程。"""
import csv
import hashlib
import hmac
import io
import json
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, TypeAdapter, model_validator
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from .chunking import presets
from .config import Settings
from .golden import GoldenItem
from .persistence import uid
from .service import Lab


class NameBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Variant(BaseModel):
    strategy: Literal["recursive", "window", "heading", "faq", "table"]
    length: int = Field(default=800, ge=1, le=1600)
    overlap: int = Field(default=100, ge=0)

    @model_validator(mode="after")
    def check_overlap(self):
        if self.overlap >= self.length:
            raise ValueError("重叠必须小于长度")
        return self


class ExperimentBody(BaseModel):
    kb_id: str
    document_ids: list[str] = Field(min_length=1, max_length=500)
    parser: Literal["local", "ragflow"] = "local"
    variants: list[Variant] = Field(min_length=1, max_length=20)


class GoldenBody(NameBody):
    kb_id: str
    items: list[GoldenItem] = Field(min_length=1, max_length=5000)


class EvaluationBody(BaseModel):
    trial_id: str
    golden_id: str
    top_k: int = Field(default=5, ge=1, le=50)
    budget: int = Field(default=2000, ge=1, le=20000)
    mode: Literal["vector", "bm25", "hybrid"] = "vector"


class ReleaseBody(BaseModel):
    kb_id: str
    trial_id: str
    golden_id: str
    threshold: float = Field(default=.8, ge=0, le=1)


class ActivateBody(BaseModel):
    expected_release_id: str | None = None


class SearchBody(BaseModel):
    trial_id: str | None = None
    kb_id: str | None = None
    query: str = Field(min_length=1, max_length=10000)
    top_k: int = Field(default=5, ge=1, le=50)
    budget: int = Field(default=2000, ge=1, le=20000)
    mode: Literal["vector", "bm25", "hybrid"] = "vector"


def create_app(settings=None, lab=None, start_worker=True):
    settings = settings or Settings()
    if len(settings.api_token) < 1:
        raise ValueError("请在.env中设置RAGLAB_API_TOKEN后启动")
    lab = lab or Lab(settings)
    stop = threading.Event()

    def worker():
        while not stop.is_set():
            try:
                if not lab.work_once():
                    stop.wait(.4)
            except Exception:
                stop.wait(2)

    @asynccontextmanager
    async def lifespan(app):
        thread = None
        if start_worker:
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
        yield
        stop.set()
        if thread:
            thread.join(timeout=3)

    app = FastAPI(title="AutoRAG 研发试验台", version="0.1.0", lifespan=lifespan)
    app.state.lab = lab

    def auth(request: Request, authorization: str = Header(default="")):
        token = authorization.removeprefix("Bearer ")
        admin = hmac.compare_digest(token, settings.api_token)
        viewer = bool(settings.viewer_token) and hmac.compare_digest(token, settings.viewer_token)
        if not admin and not viewer:
            raise HTTPException(401, "请提供有效访问令牌")
        if not admin and request.method not in {"GET", "HEAD"}:
            raise HTTPException(403, "只读角色不能执行此操作")
        # 单机版身份在服务端固定，不能通过请求头冒充其他workspace。
        return "local"

    @app.exception_handler(KeyError)
    async def missing(_, exc):
        return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": "资源不存在或无权限"})

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        message = str(exc)
        return JSONResponse(status_code=409 if "冲突" in message or "幂等" in message else 422,
                            content={"code": "INVALID_REQUEST", "message": message})

    @app.exception_handler(IntegrityError)
    async def conflict(_, exc):
        return JSONResponse(status_code=409, content={"code": "CONFLICT", "message": "资源或任务已存在，请查询后重试"})

    @app.exception_handler(httpx.HTTPError)
    async def unavailable(_, exc):
        return JSONResponse(status_code=503, content={"code": "DEPENDENCY_UNAVAILABLE", "message": "模型或解析服务不可用"})

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/v1/diagnostics")
    def diagnostics(workspace=Depends(auth)):
        try:
            binding = lab.embedder.binding()
            model = {"available": True, **binding}
        except Exception:
            model = {"available": False, "model": settings.embed_model}
        return {"database": "postgresql+pgvector" if lab.store.pg else "sqlite-test",
                "model": model, "parsers": {"local": True, "ragflow_configured": bool(settings.ragflow_url)},
                "token_budget_available": False, "reranker_available": False,
                "obs_connector": "reserved", "workspace": workspace}

    @app.get("/api/v1/presets")
    def list_presets(workspace=Depends(auth)):
        return presets()

    @app.get("/api/v1/knowledge-bases")
    def knowledge_bases(workspace=Depends(auth)):
        return lab.store.list("knowledge_base", workspace)

    @app.post("/api/v1/knowledge-bases", status_code=201)
    def create_kb(body: NameBody, workspace=Depends(auth)):
        return lab.create_kb(workspace, body.name)

    @app.get("/api/v1/knowledge-bases/{kb_id}/documents")
    def documents(kb_id: str, workspace=Depends(auth)):
        return lab.documents(workspace, kb_id)

    @app.post("/api/v1/ingestions", status_code=201)
    def ingest(kb_id: str = Form(...), file: UploadFile = File(...), source: str = Form("manual"),
               external_id: str = Form(""), revision: str = Form(""), workspace=Depends(auth)):
        lab.store.get(kb_id, workspace, "knowledge_base")
        # 未显式给source revision时使用内容hash，上传修改文件产生新修订。
        blob_hash = lab.blobs.put(file.file)
        file.file.seek(0)
        return lab.ingest(workspace, kb_id, file.filename or "upload.txt", file.file, source,
                          external_id or file.filename or "upload", revision or blob_hash)

    @app.post("/api/v1/ingestions/raw", status_code=201)
    async def raw_ingest(request: Request, kb_id: str, file_name: str = Query(max_length=255),
                         source: str = "internal-reserved", external_id: str = "", revision: str = "",
                         workspace=Depends(auth)):
        lab.store.get(kb_id, workspace, "knowledge_base")
        with tempfile.TemporaryFile() as stream:
            count, sha = 0, hashlib.sha256()
            async for chunk in request.stream():
                count += len(chunk)
                if count > settings.max_file_bytes:
                    raise HTTPException(413, "流文件超过大小限制")
                stream.write(chunk)
                sha.update(chunk)
            stream.seek(0)
            return await run_in_threadpool(lab.ingest, workspace, kb_id, file_name, stream,
                                          source, external_id or file_name, revision or sha.hexdigest())

    @app.get("/api/v1/documents/{id}/parsed")
    def parsed(id: str, parser: Literal["local", "ragflow"] = "local", workspace=Depends(auth)):
        return lab.parsed(workspace, id, parser)

    def enqueue(workspace, kind, body, key):
        return lab.store.enqueue(workspace, kind, body.model_dump(), key or uid())

    @app.post("/api/v1/experiments", status_code=202)
    def experiments(body: ExperimentBody, workspace=Depends(auth), idempotency_key: str = Header(default="")):
        lab.store.get(body.kb_id, workspace, "knowledge_base")
        for id in body.document_ids:
            doc = lab.store.get(id, workspace, "document")
            if doc["data"]["kb_id"] != body.kb_id:
                raise ValueError("文档不属于知识库")
        return enqueue(workspace, "experiment", body, idempotency_key)

    @app.get("/api/v1/jobs/{id}")
    def job(id: str, workspace=Depends(auth)):
        return lab.store.get_job(id, workspace)

    @app.get("/api/v1/records/{kind}")
    def records(kind: Literal["trial", "experiment", "golden", "evaluation", "release", "audit"],
                workspace=Depends(auth)):
        return lab.store.list(kind, workspace)

    @app.get("/api/v1/trials/{id}/chunks")
    def chunks(id: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500),
               workspace=Depends(auth)):
        rows = lab.chunks(workspace, id)
        return {"items": rows[offset:offset+limit], "total": len(rows)}

    @app.post("/api/v1/golden-datasets", status_code=201)
    def golden(body: GoldenBody, workspace=Depends(auth)):
        return lab.import_golden(workspace, body.kb_id, body.name,
                                 [item.model_dump() for item in body.items])

    @app.post("/api/v1/golden-datasets/import", status_code=201)
    def import_golden(kb_id: str = Form(...), name: str = Form(...), file: UploadFile = File(...),
                      workspace=Depends(auth)):
        lab.store.get(kb_id, workspace, "knowledge_base")
        raw = file.file.read(5*1024*1024+1)
        if len(raw) > 5*1024*1024:
            raise ValueError("黄金集超过5MB")
        content = raw.decode("utf-8-sig")
        if (file.filename or "").lower().endswith(".csv"):
            items = list(csv.DictReader(io.StringIO(content)))
            for row in items:
                row["relevant_documents"] = json.loads(row["relevant_documents"])
                if row.get("evidence"):
                    row["evidence"] = json.loads(row["evidence"])
                else:
                    row.pop("evidence", None)
        else:
            items = json.loads(content)
        items = TypeAdapter(list[GoldenItem]).validate_python(items)
        items = [item.model_dump() for item in items]
        return lab.import_golden(workspace, kb_id, name, items)

    @app.post("/api/v1/evaluations", status_code=202)
    def evaluations(body: EvaluationBody, workspace=Depends(auth), idempotency_key: str = Header(default="")):
        lab.store.get(body.trial_id, workspace, "trial")
        lab.store.get(body.golden_id, workspace, "golden")
        return enqueue(workspace, "evaluation", body, idempotency_key)

    @app.post("/api/v1/release-builds", status_code=202)
    def release_build(body: ReleaseBody, workspace=Depends(auth), idempotency_key: str = Header(default="")):
        lab.store.get(body.kb_id, workspace, "knowledge_base")
        lab.store.get(body.trial_id, workspace, "trial")
        lab.store.get(body.golden_id, workspace, "golden")
        return enqueue(workspace, "release", body, idempotency_key)

    @app.post("/api/v1/releases/{id}/activate")
    @app.post("/api/v1/releases/{id}/rollback")
    def activate(id: str, body: ActivateBody, workspace=Depends(auth)):
        return lab.activate(workspace, id, body.expected_release_id)

    @app.post("/api/v1/search")
    def search(body: SearchBody, workspace=Depends(auth)):
        if body.trial_id:
            return lab.search(workspace, body.trial_id, body.query, body.top_k, body.budget, body.mode)
        if body.kb_id:
            return lab.search_active(workspace, body.kb_id, body.query)
        raise ValueError("请选择试验方案或已发布知识库")

    static = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if static.exists():
        app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
    return app
