"""四特征监督拒答的一次拟合/门槛选择。只读独立开发报告,不导入冻结题。"""

from __future__ import annotations

import math
import warnings
from itertools import pairwise
from typing import Any

FEATURE_NAMES = ["dense_max", "dense_margin", "query_term_coverage", "retriever_agreement"]
QUALITY = {"answered_recall_at_5": 0.90, "answered_mrr_at_5": 0.75,
    "unanswered_precision": 0.90, "unanswered_recall": 0.85}


def linear_score(features: list[float], policy: dict[str, Any]) -> float:
    if len(features) != 4 or policy["featureNames"] != FEATURE_NAMES:
        raise ValueError("四特征契约不符")
    result = float(policy["intercept"])
    for index in range(4):
        scale = policy["scale"][index]
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("无效标准化尺度")
        result += ((features[index] - policy["mean"][index]) / scale) * policy["coefficients"][index]
    if not math.isfinite(result):
        raise ValueError("判别分数非有限值")
    return result


def measure(rows: list[dict[str, Any]], decisions: list[bool]) -> dict[str, Any]:
    answered = [(row, accepted) for row, accepted in zip(rows, decisions, strict=True) if row["answerable"]]
    unanswered = [(row, accepted) for row, accepted in zip(rows, decisions, strict=True) if not row["answerable"]]
    if not answered or not unanswered:
        raise ValueError("测量分区必须包含两类问题")
    true_abstentions = sum(not accepted for _, accepted in unanswered)
    false_abstentions = sum(not accepted for _, accepted in answered)
    abstentions = true_abstentions + false_abstentions
    recalls = [row["recall"] if accepted else 0.0 for row, accepted in answered]
    ranks = [row["reciprocal_rank"] if accepted else 0.0 for row, accepted in answered]
    return {"answered_recall_at_5": sum(recalls) / len(answered),
        "answered_mrr_at_5": sum(ranks) / len(answered),
        "unanswered_precision": true_abstentions / abstentions if abstentions else 0.0,
        "unanswered_recall": true_abstentions / len(unanswered),
        "answerable_false_rejection": false_abstentions / len(answered),
        "unanswerable_false_acceptance": 1 - true_abstentions / len(unanswered),
        "counts": {"answered": len(answered), "unanswered": len(unanswered),
            "true_abstentions": true_abstentions, "false_abstentions": false_abstentions,
            "recall_sum": sum(recalls), "reciprocal_rank_sum": sum(ranks)}}


def accepted_rows(rows: list[dict[str, Any]], scores: list[float], threshold: float) -> list[bool]:
    return [bool(row["vectorCandidates"]) and score >= threshold
        for row, score in zip(rows, scores, strict=True)]


def select_threshold(rows: list[dict[str, Any]], scores: list[float]) -> dict[str, Any]:
    values = sorted(set(scores))
    if not values or any(not math.isfinite(score) for score in values):
        raise ValueError("缺少有限校准分数")
    thresholds = [values[0], math.nextafter(values[-1], math.inf),
        *[(left + right) / 2 for left, right in pairwise(values)]]
    candidates = [{"threshold": threshold, "metrics": measure(rows, accepted_rows(rows, scores, threshold))}
        for threshold in thresholds]
    feasible = [entry for entry in candidates
        if all(entry["metrics"][key] >= target for key, target in QUALITY.items())]
    if not feasible:
        return {"status": "INFEASIBLE", "candidates": candidates, "selected": None}
    selected = max(feasible, key=lambda entry: (entry["metrics"]["answered_recall_at_5"],
        entry["metrics"]["unanswered_precision"], entry["threshold"]))
    return {"status": "CALIBRATED", "candidates": candidates, "selected": selected}


def fit_once(training: list[dict[str, Any]], calibration: list[dict[str, Any]]) -> dict[str, Any]:
    # 安装/导入训练库仅在受锁运行阶段;产品服务不加载 sklearn。
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    labels = [int(row["answerable"] and row["recall"] == 1.0) for row in training]
    if len(set(labels)) != 2:
        raise ValueError("训练标签没有两个类别,停止拟合")
    pipeline = make_pipeline(StandardScaler(), LogisticRegression(
        penalty="l2", C=1.0, solver="lbfgs", fit_intercept=True,
        class_weight=None, max_iter=1000, random_state=0))
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        pipeline.fit([row["features"] for row in training], labels)
    scaler = pipeline.named_steps["standardscaler"]
    classifier = pipeline.named_steps["logisticregression"]
    policy = {"id": "retrieval-logistic-v1", "featureNames": FEATURE_NAMES,
        "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
        "coefficients": classifier.coef_[0].tolist(), "intercept": float(classifier.intercept_[0])}
    scores = [linear_score(row["features"], policy) for row in calibration]
    reference = pipeline.decision_function([row["features"] for row in calibration])
    if any(not math.isclose(left, float(right), rel_tol=1e-12, abs_tol=1e-12)
        for left, right in zip(scores, reference, strict=True)):
        raise ValueError("导出参数与训练器分数不一致")
    selection = select_threshold(calibration, scores)
    result = {"status": selection["status"], "fitted_model": dict(policy),
        "training_label_counts": {"supported": sum(labels), "unsupported": len(labels) - sum(labels)},
        "selection": selection, "calibration_scores": scores, "proposed_policy": None}
    if selection["selected"] is not None:
        policy.update(status="CALIBRATED", threshold=selection["selected"]["threshold"])
        result["proposed_policy"] = policy
    return result
