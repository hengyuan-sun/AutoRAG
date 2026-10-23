import hashlib
import io

import pytest

from raglab.parsing import parse_local
from raglab.persistence import BlobStore, Store


def test_records_are_scoped_and_blobs_content_addressed(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'db'}", 3)
    a = store.create("document", "w1", {"name": "a"})
    assert store.get(a["id"], "w1")["data"]["name"] == "a"
    with pytest.raises(KeyError):
        store.get(a["id"], "w2")
    blobs = BlobStore(tmp_path / "blobs", 10)
    one = blobs.put(io.BytesIO(b"hello"))
    assert one == blobs.put(io.BytesIO(b"hello"))
    assert one == hashlib.sha256(b"hello").hexdigest()
    assert blobs.read(one) == b"hello"
    assert blobs.read_verified(one) == b"hello"
    with pytest.raises(ValueError):
        blobs.put(io.BytesIO(b"x" * 11))
    with pytest.raises(ValueError):
        blobs.read("../db")


def test_blob_verified_read_detects_corruption(tmp_path):
    blobs = BlobStore(tmp_path / "blobs", 100)
    key = blobs.put(io.BytesIO(b"original"))
    (tmp_path / "blobs" / key).write_bytes(b"changed")
    with pytest.raises(ValueError, match="哈希校验"):
        blobs.read_verified(key)


def test_job_lease_and_publish_cas(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'db'}", 3)
    job = store.enqueue("w1", "build", {"id": "a"}, "key")
    assert store.enqueue("w1", "build", {"id": "a"}, "key")["id"] == job["id"]
    claim = store.claim("worker1", lease_seconds=10)
    assert store.claim("worker2") is None
    with pytest.raises(ValueError):
        store.finish(job["id"], "worker2", claim["fence"], {"ok": True})
    store.finish(job["id"], "worker1", claim["fence"], {"ok": True})
    kb = store.create("knowledge_base", "w1", {"name": "test"})
    assert store.activate(kb["id"], "w1", "r1", None)
    assert not store.activate(kb["id"], "w1", "r2", None)
    assert store.activate(kb["id"], "w1", "r2", "r1")


def test_local_parser_reports_identity_and_no_fake_pages():
    parsed = parse_local("x.md", "# 工艺\n\n温度80℃\n\n|列|数值|\n|--|--|\n|A|80|".encode(), "r1")
    assert parsed["parser"] == "local-baseline@2"
    assert parsed["blocks"]
    assert all(b["page"] is None for b in parsed["blocks"])
    assert any(b["type"] == "table" for b in parsed["blocks"])
    with pytest.raises(ValueError):
        parse_local("file.exe", b"MZ", "r1")
