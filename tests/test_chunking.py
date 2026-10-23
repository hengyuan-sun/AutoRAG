import pytest

from raglab.chunking import chunk_document, presets


def document(text, kind="text", rows=None):
    return {"revision": "r1", "blocks": [{"id": "b0", "text": text, "type": kind,
            "section_path": ["工艺"], "page": 1, "rows": rows}]}


@pytest.mark.parametrize("strategy", ["recursive", "window", "heading", "faq", "table"])
def test_all_presets_preserve_source(strategy):
    text = "标题\n\n问：温度？\n答：80℃。\n" * 30
    overlap = 0 if strategy == "table" else 20
    chunks = chunk_document(document(text), strategy, 100, overlap)
    assert chunks
    covered = set()
    for c in chunks:
        assert c["text"]
        for span in c["spans"]:
            assert span["item_uid"] == span["block_id"]
            assert span["page"] == 1
            assert text[span["start"]:span["end"]] in c["text"]
            covered.update(range(span["start"], span["end"]))
    assert len(covered) == len(text)


def test_unicode_and_overlap_have_progress():
    text = "甲😀乙" * 100
    chunks = chunk_document(document(text), "window", 100, 20)
    assert [len(c["text"]) for c in chunks] == [100, 100, 100, 60]
    assert chunks[-1]["spans"][0]["end"] == 300


def test_table_headers_repeat_with_original_source():
    rows = ["编号 | 温度", *[f"{i} | 80℃" for i in range(50)]]
    text = "\n".join(rows)
    chunks = chunk_document(document(text, "table", rows), "table", 100, 0)
    assert len(chunks) > 1
    assert all(c["text"].startswith(rows[0]) for c in chunks)
    assert all(c["spans"][0]["start"] == 0 for c in chunks)


@pytest.mark.parametrize("length,overlap", [(0, 0), (100, 100), (100, -1), (1601, 0)])
def test_invalid_settings_rejected(length, overlap):
    with pytest.raises(ValueError):
        chunk_document(document("x"), "window", length, overlap)


def test_unknown_and_empty_document_rejected():
    with pytest.raises(ValueError):
        chunk_document(document(""), "recursive", 100, 0)
    with pytest.raises(ValueError):
        chunk_document(document("abc"), "unknown", 100, 0)
    assert len(presets()) == 5
