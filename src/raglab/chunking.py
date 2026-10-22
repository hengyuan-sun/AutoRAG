"""五种可追溯切分预设。所有位置均为块内Unicode码点左闭右开区间。"""
import hashlib
import re


def presets():
    return [{"id": key, "name": name, "version": "1.0", "length": 800, "overlap": 100}
            for key, name in [("recursive", "通用递归"), ("window", "滑动窗口"),
                              ("heading", "标题条款"), ("faq", "FAQ问答对"), ("table", "表格行组")]]


def _ranges(text, length, overlap, strategy):
    start = 0
    while start < len(text):
        end = min(start + length, len(text))
        if end < len(text) and strategy != "window":
            if strategy == "faq":
                pattern = r"\n(?=[Q问][：:])"
            elif strategy == "heading":
                pattern = r"\n(?=#+ |[一二三四五六七八九十]+[、.]|\d+[.、])"
            else:
                pattern = r"\n\n|\n|[。！？.!?]"
            boundaries = [m.end() for m in re.finditer(pattern, text[start:end])
                          if m.end() > max(length // 2, overlap)]
            if boundaries:
                end = start + boundaries[-1]
        yield start, end
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def chunk_document(document, strategy, length, overlap):
    if strategy not in {p["id"] for p in presets()}:
        raise ValueError("未知切分策略")
    if not 1 <= length <= 1600 or not 0 <= overlap < length:
        raise ValueError("长度必须在1–1600之间，重叠必须小于长度且非负")
    chunks = []
    for block in document["blocks"]:
        text = block["text"]
        if not text.strip():
            continue
        doc_id = document["revision"]

        def emit(parts):
            body, spans, segments = "", [], []
            for start, end in parts:
                span = {"document_id": doc_id, "block_id": block["id"], "start": start, "end": end}
                segments.append({"start": len(body), "end": len(body) + end - start, "span": span})
                body += text[start:end]
                spans.append(span)
            identity = f"{doc_id}:{block['id']}:{strategy}:{length}:{overlap}:{parts}"
            chunks.append({"id": hashlib.sha256(identity.encode()).hexdigest()[:32], "text": body,
                           "spans": spans, "segments": segments, "document_id": doc_id,
                           "page": block.get("page"), "section_path": block.get("section_path", []),
                           "warnings": ["单个结构超过目标长度"] if len(body) > length else []})

        if strategy == "table" and block.get("type") == "table" and block.get("rows"):
            lines = text.splitlines(keepends=True)
            header_end = len(lines[0])
            position, group_start = header_end, header_end
            for line in lines[1:]:
                if position > group_start and header_end + position + len(line) - group_start > length:
                    emit([(0, header_end), (group_start, position)])
                    group_start = position
                position += len(line)
            if position > group_start:
                emit([(0, header_end), (group_start, position)])
            elif len(lines) == 1:
                emit([(0, header_end)])
        else:
            for start, end in _ranges(text, length, overlap, strategy):
                emit([(start, end)])
    if not chunks:
        raise ValueError("文档没有可切分文本")
    return chunks
