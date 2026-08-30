"""独立开发契约的测试源码;人工示例不是本票真实校准或质量证据。"""

import pytest

from baseline_agent.knowledge_answerability import FEATURE_NAMES, linear_score, select_threshold
from baseline_agent.knowledge_answerability_v1 import ROOT, articles, file_sha, load_data, queries


def row(answerable, recalled=True):
    return {"answerable": answerable, "recall": float(answerable and recalled),
        "reciprocal_rank": float(answerable and recalled), "vectorCandidates": [{"chunkId": "example"}]}


def test_no_feasible_threshold_means_stop_not_best_effort_policy():
    result = select_threshold([row(True), row(False)], [0.5, 0.5])
    assert result["status"] == "INFEASIBLE"
    assert result["selected"] is None


def test_threshold_uses_post_refusal_recall_and_does_not_hide_retrieval_misses():
    result = select_threshold([row(True, recalled=False), row(False)], [0.9, 0.1])
    assert result["status"] == "INFEASIBLE"
    result = select_threshold([row(True), row(False)], [0.9, 0.1])
    assert result["selected"]["threshold"] == 0.5
    assert result["selected"]["metrics"]["unanswered_precision"] == 1.0


def test_linear_export_matches_java_hand_calculated_contract():
    policy = {"featureNames": FEATURE_NAMES, "mean": [0.5, 0.1, 0.5, 0.25],
        "scale": [0.5, 0.1, 0.5, 0.25], "coefficients": [2, -1, 0.5, 3], "intercept": -0.5}
    assert linear_score([0.75, 0.2, 1.0, 0.5], policy) == 3.0
    with pytest.raises(ValueError, match="契约"):
        linear_score([0.75, 0.2, 1.0, 0.5], {**policy, "featureNames": list(reversed(FEATURE_NAMES))})


def test_only_committed_training_and_calibration_data_follow_the_registered_counts():
    import json

    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8-sig"))
    groups = []
    for entry in manifest["datasets"]:
        path = ROOT / entry["file"]
        assert file_sha(path) == entry["sha256"]
        data = load_data(path)
        assert len(queries(data)) == entry["queryCount"]
        assert len(articles(data)) == entry["articleCount"]
        groups.append({topic["id"] for topic in data["topics"]})
    assert groups[0].isdisjoint(groups[1])
    assert not (ROOT / "holdout.json").exists()
