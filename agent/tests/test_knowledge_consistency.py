import pytest

from baseline_agent.knowledge_consistency import (
    ConsistencyTolerance,
    RankingPair,
    VectorPair,
    compare_consistency,
)


def tolerance():
    # 仅用于算术单测,不是项目 ONNX 验收阈值。
    return ConsistencyTolerance("synthetic-test-only", 0.01, 0.01, 0.01, 1.0, 1.0, 5)


def test_vector_similarity_does_not_hide_ranking_reversal():
    report = compare_consistency(
        [VectorPair("query:q1", [1.0, 0.0], [1.0, 0.001])],
        [RankingPair("q1", ["a/v1/c1", "b/v2/c1"], ["b/v2/c1", "a/v1/c1"])],
        tolerance=tolerance(),
        dimensions=2,
    )
    assert report["metrics"]["min_top_k_overlap"] == 1.0
    assert report["metrics"]["exact_order_rate"] == 0.0
    assert report["status"] == "FAIL"


def test_wrong_version_and_one_sided_empty_ranking_are_disagreement():
    report = compare_consistency(
        [VectorPair("document:a", [1.0, 0.0], [1.0, 0.0])],
        [RankingPair("version", ["a/v1/c1"], ["a/v2/c1"]), RankingPair("missing", ["a/v1/c1"], [])],
        tolerance=tolerance(),
        dimensions=2,
    )
    assert report["metrics"]["min_top_k_overlap"] == 0.0
    assert report["status"] == "FAIL"


def test_identical_short_lists_and_empty_rankings_pass_supplied_scope_only():
    report = compare_consistency(
        [VectorPair("query:q1", [1.0, 0.0], [1.0, 0.0])],
        [RankingPair("q1", ["a/v1/c1"], ["a/v1/c1"]), RankingPair("q2", [], [])],
        tolerance=tolerance(),
        dimensions=2,
    )
    assert report["status"] == "PASS"
    assert report["scope"] == "SUPPLIED_SAMPLES_ONLY"
    assert report["default_change"] == "NOT_AUTHORIZED"


def test_nonfinite_model_output_cannot_produce_pass():
    with pytest.raises(ValueError, match="非有限"):
        compare_consistency(
            [VectorPair("q1", [1.0, 0.0], [float("nan"), 0.0])],
            [RankingPair("q1", [], [])],
            tolerance=tolerance(),
            dimensions=2,
        )


def test_matching_unnormalized_vectors_do_not_satisfy_l2_contract():
    report = compare_consistency(
        [VectorPair("document:a", [2.0, 0.0], [2.0, 0.0])],
        [RankingPair("q1", [], [])],
        tolerance=tolerance(),
        dimensions=2,
    )
    assert report["metrics"]["max_norm_error"] == 1.0
    assert report["status"] == "FAIL"
