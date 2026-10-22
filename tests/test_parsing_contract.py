import io

import httpx
import pytest
from docx import Document

from raglab.parsing import parse_local, parse_ragflow


def test_docx_preserves_table_order():
    doc = Document()
    doc.add_heading("工艺", 1)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "部件"
    table.cell(0, 1).text = "温度"
    table.cell(1, 0).text = "A"
    table.cell(1, 1).text = "80"
    doc.add_paragraph("结束")
    stream = io.BytesIO()
    doc.save(stream)
    parsed = parse_local("test.docx", stream.getvalue(), "r")
    assert [b["type"] for b in parsed["blocks"]] == ["text", "table", "text"]
    assert "A | 80" in parsed["blocks"][1]["text"]


def test_ragflow_protocol_does_not_silently_fallback(monkeypatch):
    with pytest.raises(ValueError, match="尚未配置"):
        parse_ragflow("x.txt", b"hello", "r", "", "")
    original_client = httpx.Client

    def handler(request):
        assert request.url.path == "/internal/v1/parse"
        assert request.headers["Authorization"] == "Bearer bridge-secret"
        return httpx.Response(200, json={"parser": "ragflow@fixture", "revision": "WRONG", "blocks": [{"id": "b0", "text": "x"}]})

    monkeypatch.setattr(httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ValueError, match="契约"):
        parse_ragflow("x.txt", b"hello", "r", "http://bridge", "bridge-secret")
