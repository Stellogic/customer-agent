from baseline_agent.knowledge_onnx_evaluation import rank_vectors


def test_numeric_ranking_uses_cosine_then_stable_chunk_identity():
    documents = {"b": [2.0, 0.0], "a": [1.0, 0.0], "c": [0.0, 1.0]}
    assert rank_vectors([3.0, 0.0], documents, ["c", "b", "a"], 2) == ["a", "b"]
    assert rank_vectors([0.0, 1.0], documents, ["c", "b", "a"], 2) == ["c", "a"]
    assert rank_vectors([1.0, 0.0], documents, [], 5) == []
