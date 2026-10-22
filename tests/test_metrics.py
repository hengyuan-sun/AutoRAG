import pytest

from raglab.metrics import assemble, evidence_metrics, ranking_metrics, rrf


def span(start, end, block="b", doc="d"):
    return {"document_id": doc, "block_id": block, "start": start, "end": end}


def test_evidence_unique_and_real_cost():
    result = evidence_metrics([span(0, 100)], [span(20, 100), span(100, 220)], 250)
    assert result["evidence_recall"] == .8
    assert result["evidence_precision"] == .4
    assert result["evidence_iou"] == pytest.approx(80 / 220)
    assert result["effective_precision"] == .32
    assert result["redundancy"] == pytest.approx(.2)


def test_equal_words_different_documents_not_hits():
    assert evidence_metrics([span(0, 10)], [span(0, 10, doc="other")], 10)["evidence_recall"] == 0
    assert evidence_metrics([], [], 0)["evidence_recall"] is None
    assert evidence_metrics([span(0, 10)], [], 0)["evidence_recall"] == 0


def test_ranking_and_duplicates():
    result = ranking_metrics(["a", "b"], ["a", "a", "c", "b"], 2)
    assert result["recall"] == .5
    assert result["hit"] == 1
    assert result["mrr"] == 1
    assert ranking_metrics([], [], 5)["recall"] is None


def test_rrf_uses_positions_and_assembly_accounts_actual_output():
    a = {"id": "a", "text": "abcdef", "spans": [span(0, 6)]}
    b = {"id": "b", "text": "ghijkl", "spans": [span(6, 12)]}
    fused = rrf([[a, b], [b]])
    assert fused[0]["id"] == "b"
    assert fused[0]["score"] == pytest.approx(1/62 + 1/61)
    context = assemble([a, b], budget=8, unit="characters")
    assert context["text"] == "abcdef\ng"
    assert context["cost"] == 8
    assert context["spans"][-1]["end"] == 7
    with pytest.raises(ValueError):
        assemble([a], budget=8, unit="tokens")
