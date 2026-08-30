"""比较同一文本/查询的向量与外部检索排序；不实现新的检索器或默认切换。"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ConsistencyTolerance:
    # #189 没有冻结 ONNX 容差；调用者必须提供经审查的独立协议标识，无内置宽松默认。
    protocol_id: str
    max_absolute_error: float
    max_cosine_distance: float
    max_norm_error: float
    min_top_k_overlap: float
    min_exact_order_rate: float
    k: int

    def __post_init__(self) -> None:
        if not self.protocol_id.strip() or self.k < 1:
            raise ValueError("必须提供容差协议标识及正数 K")
        values = (
            self.max_absolute_error,
            self.max_cosine_distance,
            self.max_norm_error,
            self.min_top_k_overlap,
            self.min_exact_order_rate,
        )
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("容差必须为有限非负值")
        if self.max_cosine_distance > 2 or max(values[3:]) > 1:
            raise ValueError("余弦距离或排序比例容差超出定义域")


@dataclass(frozen=True)
class VectorPair:
    # sample_id 应区分 query/document、batch、短文本与右截断样本。
    sample_id: str
    pytorch: list[float]
    onnx: list[float]


@dataclass(frozen=True)
class RankingPair:
    query_id: str
    # 唯一标识须包含 article/version/chunk，不能只用 articleId。
    pytorch: list[str]
    onnx: list[str]


def compare_consistency(
    vectors: list[VectorPair],
    rankings: list[RankingPair],
    *,
    tolerance: ConsistencyTolerance,
    dimensions: int,
) -> dict[str, Any]:
    if not vectors or not rankings or dimensions < 1:
        raise ValueError("一致性比较需要非空的向量、排序及维度")
    if len({pair.sample_id for pair in vectors}) != len(vectors) or len(
        {pair.query_id for pair in rankings}
    ) != len(rankings):
        raise ValueError("一致性样本标识重复")
    vector_rows: list[dict[str, Any]] = []
    for pair in vectors:
        if any(len(vector) != dimensions for vector in (pair.pytorch, pair.onnx)) or any(
            not math.isfinite(value) for value in pair.pytorch + pair.onnx
        ):
            raise ValueError("向量维度不符或包含非有限值")
        norms = [math.sqrt(sum(value * value for value in vector)) for vector in (pair.pytorch, pair.onnx)]
        if min(norms) == 0:
            raise ValueError("零向量不能计算余弦距离")
        cosine = sum(a * b for a, b in zip(pair.pytorch, pair.onnx, strict=True)) / math.prod(norms)
        vector_rows.append({
            "sample_id": pair.sample_id,
            "max_absolute_error": max(abs(a - b) for a, b in zip(pair.pytorch, pair.onnx, strict=True)),
            "cosine_distance": 1 - max(-1.0, min(1.0, cosine)),
            "pytorch_norm": norms[0],
            "onnx_norm": norms[1],
        })
    ranking_rows: list[dict[str, Any]] = []
    for pair in rankings:
        left, right = pair.pytorch[:tolerance.k], pair.onnx[:tolerance.k]
        if len(set(left)) != len(left) or len(set(right)) != len(right):
            raise ValueError("Top-K 包含重复片段")
        denominator = max(len(left), len(right))
        ranking_rows.append({
            "query_id": pair.query_id,
            "pytorch": left,
            "onnx": right,
            # 双方都拒答视为一致；一方拒答另一方命中则为零。
            "overlap": len(set(left) & set(right)) / denominator if denominator else 1.0,
            "exact_order": left == right,
        })
    measured = {
        "max_absolute_error": max(row["max_absolute_error"] for row in vector_rows),
        "max_cosine_distance": max(row["cosine_distance"] for row in vector_rows),
        "max_norm_error": max(
            abs(row[name] - 1) for row in vector_rows for name in ("pytorch_norm", "onnx_norm")
        ),
        "min_top_k_overlap": min(row["overlap"] for row in ranking_rows),
        "exact_order_rate": sum(row["exact_order"] for row in ranking_rows) / len(ranking_rows),
    }
    passed = (
        measured["max_absolute_error"] <= tolerance.max_absolute_error
        and measured["max_cosine_distance"] <= tolerance.max_cosine_distance
        and measured["max_norm_error"] <= tolerance.max_norm_error
        and measured["min_top_k_overlap"] >= tolerance.min_top_k_overlap
        and measured["exact_order_rate"] >= tolerance.min_exact_order_rate
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "scope": "SUPPLIED_SAMPLES_ONLY",
        "tolerance": asdict(tolerance),
        "dimensions": dimensions,
        "metrics": measured,
        "vectors": vector_rows,
        "rankings": ranking_rows,
        "default_change": "NOT_AUTHORIZED",
    }
