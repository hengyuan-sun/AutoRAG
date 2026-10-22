"""显式的本地基线解析器，以及独立RAGFlow Go桥接协议适配。"""
import io
import re
from pathlib import Path

import httpx
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader


def parse_local(name, data, revision):
    ext, blocks = Path(name).suffix.lower(), []

    def add(text, kind="text", page=None, section=None, rows=None):
        if text.strip():
            blocks.append({"id": f"b{len(blocks)}", "type": kind, "text": text, "page": page,
                           "section_path": section or [], "rows": rows})

    if ext in {".txt", ".md"}:
        raw = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        section = []
        for group in re.split(r"\n\s*\n", raw):
            if group.startswith("#"):
                section = [group.splitlines()[0].lstrip("# ")]
            rows = group.splitlines()
            table = len(rows) > 1 and all("|" in r for r in rows)
            add(group, "table" if table else "text", section=section, rows=rows if table else None)
    elif ext == ".docx":
        if not data.startswith(b"PK"):
            raise ValueError("DOCX文件签名无效")
        document, section = Document(io.BytesIO(data)), []
        for child in document.element.body:
            if child.tag.endswith("}p"):
                p = Paragraph(child, document)
                if p.style and p.style.name.startswith("Heading"):
                    section = [p.text]
                add(p.text, section=section)
            elif child.tag.endswith("}tbl"):
                rows = [" | ".join(cell.text for cell in row.cells) for row in Table(child, document).rows]
                add("\n".join(rows), "table", section=section, rows=rows)
    elif ext == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("PDF文件签名无效")
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("暂不支持加密PDF")
        for page, content in enumerate(reader.pages, 1):
            add(content.extract_text() or "", page=page)
    else:
        raise ValueError("首期支持TXT/MD/DOCX/文本PDF")
    if not blocks:
        raise ValueError("未提取到文本；扫描件需要配置OCR/RAGFlow解析器")
    return {"schema_version": 1, "revision": revision, "parser": "local-baseline@1",
            "blocks": blocks, "warnings": ["本地基线不是RAGFlow；DOCX页码与PDF表格结构不保证"]}


def parse_ragflow(name, data, revision, url, token):
    if not url:
        raise ValueError("RAGFlow解析桥接尚未配置；请先部署bridge或显式选择本地基线")
    with httpx.Client(timeout=180, trust_env=False) as client:
        response = client.post(url.rstrip("/")+"/internal/v1/parse",
                               files={"file": (name, data)}, data={"revision": revision},
                               headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        parsed = response.json()
    if parsed.get("revision") != revision or not parsed.get("blocks") or not parsed.get("parser", "").startswith("ragflow"):
        raise ValueError("RAGFlow响应契约不合法")
    for block in parsed["blocks"]:
        if not isinstance(block.get("text"), str) or not block.get("id"):
            raise ValueError("RAGFlow块缺少文本/来源")
    return parsed
