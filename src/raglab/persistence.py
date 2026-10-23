"""关系台账、租约任务及向量索引。测试SQLite，正式路径PostgreSQL/pgvector。"""
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    and_,
    create_engine,
    delete,
    insert,
    or_,
    select,
    text,
    update,
)


def uid():
    return uuid.uuid4().hex


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class FileTooLargeError(ValueError):
    pass


class Store:
    def __init__(self, url, dimension):
        self.engine = create_engine(url, pool_pre_ping=True,
                                    connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        self.pg = self.engine.dialect.name == "postgresql"
        self.dimension = dimension
        self.lock = threading.RLock()
        self._job_context = threading.local()
        meta = MetaData()
        self.records = Table("lab_records", meta, Column("id", String(32), primary_key=True),
                             Column("workspace", String(80), nullable=False, index=True),
                             Column("kind", String(50), nullable=False, index=True),
                             Column("key", String(128)), Column("data", JSON, nullable=False),
                             Column("active_release", String(32)), Column("version", Integer, default=0),
                             Column("created", Float, nullable=False),
                             UniqueConstraint("workspace", "kind", "key"))
        self.jobs = Table("lab_jobs", meta, Column("id", String(32), primary_key=True),
                          Column("workspace", String(80), nullable=False), Column("kind", String(40)),
                          Column("key", String(128)), Column("payload", JSON), Column("status", String(20)),
                          Column("owner", String(80)), Column("fence", Integer, default=0),
                          Column("lease", Float, default=0), Column("result", JSON),
                          Column("error", String(1000)), Column("created", Float),
                          UniqueConstraint("workspace", "key"))
        vector_type = Vector(dimension) if self.pg else JSON
        self.vectors = Table("lab_vectors", meta, Column("id", String(70), primary_key=True),
                             Column("workspace", String(80), nullable=False, index=True),
                             Column("index_id", String(32), nullable=False, index=True),
                             Column("chunk", JSON), Column("embedding", vector_type))
        if self.pg:
            with self.engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        meta.create_all(self.engine)

    @staticmethod
    def _record(row):
        r = dict(row)
        if r.get("kind") == "knowledge_base":
            r["data"] = dict(r["data"], active_release_id=r["active_release"])
        return r

    def create(self, kind, workspace, data, key=None):
        values = {"id": uid(), "kind": kind, "workspace": workspace, "data": data,
                  "key": key, "created": time.time(), "version": 0}
        with self.engine.begin() as c:
            self._assert_job_fence(c)
            c.execute(insert(self.records).values(**values))
        return self.get(values["id"], workspace)

    def get(self, id, workspace, kind=None):
        query = select(self.records).where(self.records.c.id == id, self.records.c.workspace == workspace)
        if kind:
            query = query.where(self.records.c.kind == kind)
        with self.engine.connect() as c:
            row = c.execute(query).mappings().first()
        if not row:
            raise KeyError("资源不存在或无权限")
        return self._record(row)

    def list(self, kind, workspace, limit=200):
        with self.engine.connect() as c:
            rows = c.execute(select(self.records).where(self.records.c.workspace == workspace,
                             self.records.c.kind == kind).order_by(self.records.c.created.desc())
                             .limit(limit)).mappings().all()
        return [self._record(r) for r in rows]

    def by_key(self, kind, workspace, key):
        with self.engine.connect() as c:
            row = c.execute(select(self.records).where(self.records.c.workspace == workspace,
                            self.records.c.kind == kind, self.records.c.key == key)).mappings().first()
        return self._record(row) if row else None

    def replace(self, id, workspace, data):
        self.get(id, workspace)
        with self.engine.begin() as c:
            self._assert_job_fence(c)
            c.execute(update(self.records).where(self.records.c.id == id, self.records.c.workspace == workspace)
                      .values(data=data, version=self.records.c.version+1))
        return self.get(id, workspace)

    def activate(self, kb_id, workspace, release_id, expected):
        condition = (self.records.c.active_release == expected if expected is not None
                     else self.records.c.active_release.is_(None))
        with self.engine.begin() as c:
            result = c.execute(update(self.records).where(self.records.c.id == kb_id,
                               self.records.c.workspace == workspace,
                               self.records.c.kind == "knowledge_base", condition)
                               .values(active_release=release_id, version=self.records.c.version+1))
            return result.rowcount == 1

    def enqueue(self, workspace, kind, payload, key):
        with self.lock, self.engine.begin() as c:
            old = c.execute(select(self.jobs).where(self.jobs.c.workspace == workspace,
                            self.jobs.c.key == key)).mappings().first()
            if old:
                if old["kind"] != kind or old["payload"] != payload:
                    raise ValueError("幂等键已用于其他请求")
                return dict(old)
            values = dict(id=uid(), workspace=workspace, kind=kind, payload=payload, key=key,
                          status="QUEUED", fence=0, lease=0, created=time.time())
            c.execute(insert(self.jobs).values(**values))
            return values

    def get_job(self, id, workspace):
        with self.engine.connect() as c:
            row = c.execute(select(self.jobs).where(self.jobs.c.id == id,
                            self.jobs.c.workspace == workspace)).mappings().first()
        if not row:
            raise KeyError("任务不存在或无权限")
        return dict(row)

    def claim(self, owner, lease_seconds=60):
        with self.lock, self.engine.begin() as c:
            now = time.time()
            q = select(self.jobs).where(or_(self.jobs.c.status == "QUEUED",
                                       and_(self.jobs.c.status == "RUNNING", self.jobs.c.lease < now)))
            q = q.order_by(self.jobs.c.created).limit(1)
            if self.pg:
                q = q.with_for_update(skip_locked=True)
            row = c.execute(q).mappings().first()
            if not row:
                return None
            values = dict(status="RUNNING", owner=owner, fence=row["fence"]+1, lease=now+lease_seconds)
            c.execute(update(self.jobs).where(self.jobs.c.id == row["id"]).values(**values))
            return dict(row, **values)

    def heartbeat(self, id, owner, fence, lease_seconds=60):
        with self.engine.begin() as c:
            result = c.execute(update(self.jobs).where(self.jobs.c.id == id, self.jobs.c.owner == owner,
                               self.jobs.c.fence == fence, self.jobs.c.status == "RUNNING",
                               self.jobs.c.lease >= time.time()).values(lease=time.time()+lease_seconds))
            return result.rowcount == 1

    def finish(self, id, owner, fence, result=None, error=None):
        with self.engine.begin() as c:
            r = c.execute(update(self.jobs).where(self.jobs.c.id == id, self.jobs.c.owner == owner,
                          self.jobs.c.fence == fence, self.jobs.c.status == "RUNNING",
                          self.jobs.c.lease >= time.time()).values(status="FAILED" if error else "SUCCEEDED",
                          result=result, error=error, lease=0))
            if r.rowcount != 1:
                raise ValueError("任务租约失效，拒绝旧Worker提交")

    def write_vectors(self, workspace, index_id, chunks, vectors):
        if len(chunks) != len(vectors):
            raise ValueError("向量与Chunk数量不一致")
        for vec in vectors:
            if len(vec) != self.dimension or not all(math.isfinite(x) for x in vec):
                raise ValueError("向量维度或数值不合法")
        with self.engine.begin() as c:
            self._assert_job_fence(c)
            c.execute(delete(self.vectors).where(self.vectors.c.workspace == workspace,
                                               self.vectors.c.index_id == index_id))
            if chunks:
                c.execute(insert(self.vectors), [{"id": f"{index_id}:{chunk['id']}", "workspace": workspace,
                          "index_id": index_id, "chunk": chunk, "embedding": vec}
                          for chunk, vec in zip(chunks, vectors, strict=True)])

    @contextmanager
    def job_scope(self, job_id, owner, fence):
        """将当前线程的资源写入绑定到仍有效的任务租约。"""
        previous = getattr(self._job_context, "identity", None)
        self._job_context.identity = (job_id, owner, fence)
        try:
            yield
        finally:
            self._job_context.identity = previous

    def _assert_job_fence(self, conn):
        identity = getattr(self._job_context, "identity", None)
        if identity is None:
            return
        job_id, owner, fence = identity
        q = select(self.jobs).where(self.jobs.c.id == job_id, self.jobs.c.owner == owner,
                                    self.jobs.c.fence == fence, self.jobs.c.status == "RUNNING",
                                    self.jobs.c.lease >= time.time())
        if self.pg:
            q = q.with_for_update()
        if conn.execute(q).first() is None:
            raise ValueError("任务租约失效，拒绝旧Worker提交")

    def search_vectors(self, workspace, index_id, vector, limit):
        if len(vector) != self.dimension or not all(math.isfinite(x) for x in vector):
            raise ValueError("查询向量维度或数值不合法")
        q = select(self.vectors).where(self.vectors.c.workspace == workspace,
                                       self.vectors.c.index_id == index_id)
        if self.pg:
            distance = self.vectors.c.embedding.cosine_distance(vector)
            with self.engine.connect() as c:
                rows = c.execute(q.add_columns(distance.label("distance"))
                                 .order_by(distance, self.vectors.c.id).limit(limit)).mappings().all()
            return [dict(r["chunk"], score=1-float(r["distance"])) for r in rows]
        with self.engine.connect() as c:
            rows = c.execute(q).mappings().all()
        norm = math.sqrt(sum(x*x for x in vector)) or 1
        ranked = [dict(r["chunk"], score=sum(a*b for a, b in zip(vector, r["embedding"], strict=True)) /
                       (norm * (math.sqrt(sum(x*x for x in r["embedding"])) or 1))) for r in rows]
        return sorted(ranked, key=lambda x: (-x["score"], x["id"]))[:limit]


class BlobStore:
    def __init__(self, root, max_bytes):
        self.root, self.max_bytes = Path(root), max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, stream):
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as f:
                name, total, h = f.name, 0, hashlib.sha256()
                while part := stream.read(65536):
                    total += len(part)
                    if total > self.max_bytes:
                        raise FileTooLargeError(f"单文件不得超过{self.max_bytes}字节")
                    h.update(part)
                    f.write(part)
            if not total:
                raise ValueError("不接受空文件")
            hash_ = h.hexdigest()
            os.replace(name, self.root / hash_)
            return hash_
        finally:
            if name and Path(name).exists():
                Path(name).unlink()

    def read(self, hash_):
        with self.open(hash_) as stream:
            return stream.read()

    def read_verified(self, hash_):
        """Read a content-addressed artifact only after checking its bytes against its key."""
        with self.open(hash_) as stream:
            content = stream.read()
        if hashlib.sha256(content).hexdigest() != hash_:
            raise ValueError("产物哈希校验失败")
        return content

    def open(self, hash_):
        if not re.fullmatch(r"[a-f0-9]{64}", hash_):
            raise ValueError("无效产物标识")
        return (self.root / hash_).open("rb")
