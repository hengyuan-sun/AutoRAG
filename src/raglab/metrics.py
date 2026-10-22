"""确定性证据与检索指标，不依赖生成式评审。"""
import math
from collections import defaultdict


def _intervals(spans):
    groups = defaultdict(list)
    for s in spans:
        if s["start"] < 0 or s["end"] <= s["start"]:
            raise ValueError("无效证据区间")
        groups[(s["document_id"], s["block_id"])].append((s["start"], s["end"]))
    result = {}
    for key, values in groups.items():
        merged = []
        for a, b in sorted(values):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        result[key] = merged
    return result


def evidence_metrics(gold, retrieved, cost):
    g, r = _intervals(gold), _intervals(retrieved)
    ng = sum(b-a for spans in g.values() for a, b in spans)
    nr = sum(b-a for spans in r.values() for a, b in spans)
    hits = 0
    for key, gi in g.items():
        ri, i, j = r.get(key, []), 0, 0
        while i < len(gi) and j < len(ri):
            hits += max(0, min(gi[i][1], ri[j][1]) - max(gi[i][0], ri[j][0]))
            if gi[i][1] < ri[j][1]:
                i += 1
            else:
                j += 1
    return {"evidence_recall": hits/ng if ng else None,
            "evidence_precision": hits/nr if nr else (0.0 if ng else None),
            "evidence_iou": hits/(ng+nr-hits) if ng+nr-hits else None,
            "effective_precision": hits/cost if cost else 0.0,
            "redundancy": max(0, 1-nr/cost) if cost else 0.0}


def ranking_metrics(relevant, retrieved, k):
    unique = list(dict.fromkeys(retrieved))[:k]
    gold = set(relevant)
    ranks = [i+1 for i, d in enumerate(unique) if d in gold]
    dcg = sum(1/math.log2(r+1) for r in ranks)
    ideal = sum(1/math.log2(r+1) for r in range(1, min(k, len(gold))+1))
    return {"recall": len(ranks)/len(gold) if gold else None,
            "hit": int(bool(ranks)) if gold else None,
            "mrr": (1/ranks[0] if ranks else 0) if gold else None,
            "ndcg": dcg/ideal if ideal else None}


def rrf(rankings):
    scores, rows = defaultdict(float), {}
    for ranking in rankings:
        seen = set()
        for rank, c in enumerate(ranking, 1):
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            rows[c["id"]] = c
            scores[c["id"]] += 1/(60+rank)
    return [dict(rows[key], score=scores[key]) for key in sorted(scores, key=lambda k: (-scores[k], k))]


def assemble(candidates, budget, unit="characters"):
    if unit != "characters":
        raise ValueError("未绑定精确Tokenizer；当前仅支持字符预算")
    if budget < 1:
        raise ValueError("上下文预算必须为正")
    text, spans, seen = "", [], set()
    for c in candidates:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        separator = "\n" if text else ""
        count = min(len(c["text"]), budget - len(text) - len(separator))
        if count <= 0:
            break
        text += separator + c["text"][:count]
        segments = c.get("segments")
        if segments is None:
            segments, cursor = [], 0
            for span in c["spans"]:
                size = span["end"]-span["start"]
                segments.append({"start": cursor, "end": cursor+size, "span": span})
                cursor += size
        for segment in segments:
            used = min(count, segment["end"]) - segment["start"]
            if used > 0 and segment.get("span"):
                span = segment["span"]
                spans.append(dict(span, end=span["start"]+used))
        if len(text) >= budget:
            break
    return {"text": text, "spans": spans, "cost": len(text), "unit": unit}
