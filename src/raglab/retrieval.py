"""冻结Chunk集合上的中文字符/二元词组BM25基线。"""
import math
import re
from collections import Counter


def tokens(text):
    parts = re.findall(r"[a-z0-9_.-]+|[\u4e00-\u9fff]", text.lower())
    return parts + [a+b for a, b in zip(parts, parts[1:]) if len(a) == len(b) == 1]


def bm25(chunks, query, limit=50):
    docs = [Counter(tokens(c["text"])) for c in chunks]
    lengths = [sum(d.values()) for d in docs]
    average = sum(lengths) / max(1, len(docs)) or 1
    terms = set(tokens(query))
    df = {t: sum(t in d for d in docs) for t in terms}
    scored = []
    for chunk, doc, size in zip(chunks, docs, lengths, strict=True):
        score = 0
        for term in terms:
            freq = doc[term]
            if freq:
                idf = math.log(1+(len(docs)-df[term]+.5)/(df[term]+.5))
                score += idf * freq * 2.5 / (freq+1.5*(.25+.75*size/average))
        if score:
            scored.append(dict(chunk, score=score))
    return sorted(scored, key=lambda c: (-c["score"], c["id"]))[:limit]
