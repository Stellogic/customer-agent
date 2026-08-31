"""#168 独立消融编排;真实分路执行与评分由 #190 集成适配器提供。"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict
from importlib import import_module
from pathlib import Path
from typing import Any, Literal

from baseline_agent.rag_eval_v1 import (
    AllowedHit,
    EvalQuery,
    compute_content_sha256,
    load_rag_eval_v1,
)

RetrievalMode = Literal["lexical", "dense", "rrf"]
EvaluationProtocol = Literal["rag-eval-v1", "rag-layered-v2"]
MODES: tuple[RetrievalMode, ...] = ("lexical", "dense", "rrf")
# v2 回调返回该模式硬过滤后的排序及 #190 检索评分,无答案题也保留候选。
# v1 仅用于重现旧口径,包含旧拒答评分;两版回调不可混用。
# 不能把混合结果的 recall/MRR 复制给两路候选,也不能在此重新实现检索。
QueryRunner = Callable[[RetrievalMode, EvalQuery], dict[str, Any]]
Metrics = Callable[[list[dict[str, Any]]], dict[str, float]]


def report_template(
    environment: dict[str, Any],
    parameters: dict[str, Any],
    *,
    protocol: EvaluationProtocol = "rag-layered-v2",
) -> dict[str, Any]:
    if protocol not in ("rag-eval-v1", "rag-layered-v2"):
        raise ValueError("未知消融协议")
    dataset = load_rag_eval_v1()
    digest = compute_content_sha256()
    if digest != dataset.manifest.content_sha256:
        raise ValueError("冻结评测资产哈希不符")
    report: dict[str, Any] = {
        "schema": "knowledge-ablation-v1",
        "status": "NOT_RUN",
        "dataset": dataset.dataset_id,
        "dataset_sha256": digest,
        "model_revision": dataset.protocol.model.revision,
        "environment": environment,
        "parameters": parameters,
        "thresholds": asdict(dataset.thresholds),
        "modes": {mode: {"rows": [], "metrics": None, "status": "NOT_RUN"} for mode in MODES},
        "baseline_qualification": "NOT_ESTABLISHED_BY_THIS_REPORT",
        "parameter_freeze": "PENDING_REPRODUCIBLE_BENEFIT",
        "default_change": "NOT_AUTHORIZED",
    }
    if protocol == "rag-layered-v2":
        thresholds = report["thresholds"]
        report.update(
            {
                "schema": "knowledge-ablation-v2",
                "protocol": protocol,
                "evaluation_protocol": "rag-layered-v2-retrieval",
                "pass_scope": "RETRIEVAL_ONLY",
                "answer_evaluation": {
                    "owners": [169, 170],
                    "status": "NOT_EVALUATED",
                    "thresholds": {
                        "unanswered_precision": thresholds.pop("unanswered_precision"),
                        "unanswered_recall": thresholds.pop("unanswered_recall"),
                    },
                    "metrics": None,
                },
            }
        )
    return report


def run_ablation(
    run_query: QueryRunner,
    metrics: Metrics,
    *,
    environment: dict[str, Any],
    parameters: dict[str, Any],
    output: Path,
    modes: tuple[RetrievalMode, ...] = MODES,
    protocol: EvaluationProtocol = "rag-layered-v2",
) -> dict[str, Any]:
    """显式执行入口;失败保存已有逐题证据,绝不把异常当作正确拒答。"""
    if not modes or len(set(modes)) != len(modes) or any(mode not in MODES for mode in modes):
        raise ValueError("必须显式选择非空、不重复的已知检索模式")
    report = report_template(environment, parameters, protocol=protocol)
    dataset = load_rag_eval_v1()
    thresholds = dict(report["thresholds"])
    thresholds.pop("k")
    active: dict[str, Any] | None = None
    try:
        for mode in modes:
            mode_report: dict[str, Any] = report["modes"][mode]
            active = mode_report
            mode_report["status"] = "RUNNING"
            for query in dataset.queries:
                row = run_query(mode, query)
                if row["id"] != query.id or row["kind"] != query.kind:
                    raise ValueError("分路结果与冻结查询不符")
                if len(row["results"]) > dataset.thresholds.k:
                    raise ValueError("分路结果超过冻结 Top-K")
                mode_report["rows"].append(row)
            measured = metrics(mode_report["rows"])
            if measured.keys() != thresholds.keys() or any(
                not math.isfinite(value) or not 0 <= value <= 1 for value in measured.values()
            ):
                raise ValueError("指标不满足冻结协议")
            mode_report["metrics"] = measured
            mode_report["status"] = (
                "PASS"
                if all(
                    value <= thresholds[name]
                    if name.endswith("hit_rate")
                    else value >= thresholds[name]
                    for name, value in measured.items()
                )
                else "FAIL"
            )
        # 三路执行完不代表每路合格,更不代表收益可复现或允许切默认。
        report["status"] = "MEASURED" if set(modes) == set(MODES) else "PARTIAL"
    except Exception as error:
        report["status"] = "ERROR"
        report["error_type"] = type(error).__name__
        if active is not None:
            active["status"] = "ERROR"
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
    return report


def run_reference_rrf(
    base_url: str,
    *,
    environment: dict[str, Any],
    parameters: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    """仅重现 PR203@5402bd4 的 v1 评分;不得用作新版检索层适配器。"""
    evaluation = import_module("baseline_agent.knowledge_evaluation")
    return run_ablation(
        lambda _mode, query: evaluation.run_query(base_url, query),
        evaluation.metrics,
        environment=environment,
        parameters=parameters,
        output=output,
        modes=("rrf",),
        protocol="rag-eval-v1",
    )


def score_candidates(
    query: EvalQuery,
    hits: list[dict[str, Any]],
    matches: Callable[[dict[str, Any], AllowedHit], bool],
) -> dict[str, Any]:
    """按公共 matches 规则独立计数该路 Top-K;不继承融合评分或判断充分性。"""
    matched = [any(matches(hit, allowed) for hit in hits) for allowed in query.allowed_hits]
    ranks = [
        rank
        for rank, hit in enumerate(hits, start=1)
        if any(matches(hit, allowed) for allowed in query.allowed_hits)
    ]
    violations = {
        forbidden.reason
        for forbidden in query.forbidden_hits
        if any(
            hit["articleId"] == forbidden.article_id and hit["version"] == forbidden.version
            for hit in hits
        )
    }
    denied = (
        query.principal.subject_type != "INTERNAL"
        or "KNOWLEDGE_READ_ACCESS" not in query.principal.capabilities
        or query.search_context == "CUSTOMER_PUBLIC"
    )
    if denied and hits:
        violations.add("unauthorized")
    if query.kind == "out_of_scope" and hits:
        violations.add("out_of_scope")
    return {
        "results": hits,
        "recall": sum(matched) / len(matched) if matched else 0.0,
        "reciprocal_rank": 1 / min(ranks) if ranks else 0.0,
        "checked_prohibitions": sorted({item.reason for item in query.forbidden_hits}),
        "violations": sorted(violations),
    }


def run_layered_ablation(
    base_url: str,
    *,
    environment: dict[str, Any],
    parameters: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    """静态适配 PR203@802a343;实际执行仍须前置交付与协调运行窗口。"""
    evaluation = import_module("baseline_agent.knowledge_evaluation")
    responses: dict[str, dict[str, Any]] = {}
    k = load_rag_eval_v1().thresholds.k

    def run_route(mode: RetrievalMode, query: EvalQuery) -> dict[str, Any]:
        # 每题仅请求一次,三路比较使用同一实际响应;不跨运行缓存。
        if query.id not in responses:
            responses[query.id] = evaluation.run_query(
                base_url, query, expected_schema="knowledge-hybrid-v2"
            )
        row = responses[query.id]
        if mode == "rrf":
            return row
        field = "lexicalCandidates" if mode == "lexical" else "vectorCandidates"
        return {**row, **score_candidates(query, row[field][:k], evaluation.matches)}

    return run_ablation(
        run_route,
        evaluation.retrieval_metrics,
        environment=environment,
        parameters=parameters,
        output=output,
        protocol="rag-layered-v2",
    )
