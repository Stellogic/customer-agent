"""开发评分/选择公共接缝；人工分数只验证编排，不代表真实模型质量。"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from baseline_agent.knowledge_reranker import evaluate_development, verify_directory


def samples() -> list[dict[str, Any]]:
    return [
        {
            "id": name,
            "text": name,
            "answerable": answerable,
            "recall": 1.0 if answerable else 0.0,
            "reciprocal_rank": 1.0 if answerable else 0.0,
            "vectorCandidates": [{"chunkId": "first"}],
            "fusedCandidates": [
                {"chunkId": chunk, "snippet": chunk, "applicability": ["INTERNAL"]}
                for chunk in ("first", "second")
            ],
        }
        for name, answerable in (("supported", True), ("unsupported", False))
    ]


def test_feasible_threshold_keeps_rrf_order_and_never_changes_source() -> None:
    rows = samples()
    original = copy.deepcopy(rows)
    report: dict[str, Any] = {}
    evaluate_development(
        rows, lambda query, _: [1.0, 4.0] if query == "supported" else [-2.0, 0.0], report
    )
    assert report["status"] == "DEVELOPMENT_FEASIBLE"
    assert report["selection"]["selected"]["threshold"] == 2.0
    assert [hit["chunkId"] for hit in report["rows"][0]["results"]] == ["first", "second"]
    assert report["rows"][1]["results"] == []
    assert report["metrics"]["unanswered_precision"] == 1.0
    assert rows == original


def test_indistinguishable_scores_stop_without_best_effort_policy() -> None:
    report: dict[str, Any] = {}
    evaluate_development(samples(), lambda *_: [0.0, 0.0], report)
    assert report["status"] == "INFEASIBLE"
    assert report["selection"]["selected"] is None
    assert report["metrics"] is None
    assert all("results" not in row for row in report["rows"])


def test_scoring_failure_preserves_partial_evidence_without_quality_result() -> None:
    def score(query: str, _: list[str]) -> list[float]:
        if query == "unsupported":
            raise ValueError("synthetic model failure")
        return [1.0, 2.0]

    report: dict[str, Any] = {"metrics": None}
    with pytest.raises(ValueError, match="synthetic model failure"):
        evaluate_development(samples(), score, report)
    assert len(report["rows"]) == 1
    assert report["metrics"] is None
    assert "selection" not in report


def test_missing_local_model_fails_before_loading_framework(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="文件缺失"):
        verify_directory(tmp_path)
