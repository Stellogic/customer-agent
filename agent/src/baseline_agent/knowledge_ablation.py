"""#168 独立消融编排；真实分路执行与评分由 #190 集成适配器提供。"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict
from importlib import import_module
from pathlib import Path
from typing import Any, Literal

from baseline_agent.rag_eval_v1 import EvalQuery, compute_content_sha256, load_rag_eval_v1

RetrievalMode = Literal["lexical", "dense", "rrf"]
MODES: tuple[RetrievalMode, ...] = ("lexical", "dense", "rrf")
# 回调必须返回该模式独立完成硬过滤、拒答判定及 #190 评分后的行。
# 不能把混合结果的 recall/MRR 复制给两路候选，也不能在此重新实现检索。
QueryRunner = Callable[[RetrievalMode, EvalQuery], dict[str, Any]]
Metrics = Callable[[list[dict[str, Any]]], dict[str, float]]


def report_template(environment: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    dataset = load_rag_eval_v1()
    digest = compute_content_sha256()
    if digest != dataset.manifest.content_sha256:
        raise ValueError("冻结评测资产哈希不符")
    return {
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


def run_ablation(
    run_query: QueryRunner,
    metrics: Metrics,
    *,
    environment: dict[str, Any],
    parameters: dict[str, Any],
    output: Path,
    modes: tuple[RetrievalMode, ...] = MODES,
) -> dict[str, Any]:
    """显式执行入口；失败保存已有逐题证据，绝不把异常当作正确拒答。"""
    if not modes or len(set(modes)) != len(modes) or any(mode not in MODES for mode in modes):
        raise ValueError("必须显式选择非空、不重复的已知检索模式")
    report = report_template(environment, parameters)
    dataset = load_rag_eval_v1()
    thresholds = asdict(dataset.thresholds)
    thresholds.pop("k")
    active: dict[str, Any] | None = None
    try:
        for mode in modes:
            active = report["modes"][mode]
            active["status"] = "RUNNING"
            for query in dataset.queries:
                row = run_query(mode, query)
                if row["id"] != query.id or row["kind"] != query.kind:
                    raise ValueError("分路结果与冻结查询不符")
                if len(row["results"]) > dataset.thresholds.k:
                    raise ValueError("分路结果超过冻结 Top-K")
                active["rows"].append(row)
            measured = metrics(active["rows"])
            if measured.keys() != thresholds.keys() or any(
                not math.isfinite(value) or not 0 <= value <= 1 for value in measured.values()
            ):
                raise ValueError("指标不满足冻结协议")
            active["metrics"] = measured
            active["status"] = "PASS" if all(
                value <= thresholds[name] if name.endswith("hit_rate") else value >= thresholds[name]
                for name, value in measured.items()
            ) else "FAIL"
        # 三路执行完不代表每路合格，更不代表收益可复现或允许切默认。
        report["status"] = "MEASURED" if set(modes) == set(MODES) else "PARTIAL"
    except Exception as error:
        report["status"] = "ERROR"
        report["error_type"] = type(error).__name__
        if active is not None:
            active["status"] = "ERROR"
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report


def run_reference_rrf(
    base_url: str,
    *,
    environment: dict[str, Any],
    parameters: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    """适配 PR203 的公开融合评分接口；两条单路保持 NOT_RUN，不冒充完整消融。"""
    evaluation = import_module("baseline_agent.knowledge_evaluation")
    return run_ablation(
        lambda _mode, query: evaluation.run_query(base_url, query),
        evaluation.metrics,
        environment=environment,
        parameters=parameters,
        output=output,
        modes=("rrf",),
    )
