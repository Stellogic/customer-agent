"""在真实消融响应的完整授权候选集上比较两种编码器,不改变服务检索实现。"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

from baseline_agent.knowledge_consistency import (
    ConsistencyTolerance,
    RankingPair,
    VectorPair,
    compare_consistency,
)
from baseline_agent.knowledge_embedding import OfflineBgeEncoder
from baseline_agent.knowledge_onnx import OnnxBgeEncoder, export_bge_model
from baseline_agent.knowledge_resources import Encoder, ResourceWorkload, measure_encoder
from baseline_agent.rag_eval_v1 import load_rag_eval_v1


def rank_vectors(
    query: list[float], documents: dict[str, list[float]], ids: list[str], k: int
) -> list[str]:
    """只做给定向量的余弦排序比较;候选可见性完全来自 Spring 实际响应。"""
    query_norm = math.sqrt(sum(value * value for value in query))
    scores = {
        key: sum(a * b for a, b in zip(query, documents[key], strict=True))
        / (query_norm * math.sqrt(sum(value * value for value in documents[key])))
        for key in ids
    }
    return sorted(ids, key=lambda key: (-scores[key], key))[:k]


def compare_encoders(
    pytorch: Encoder,
    onnx: Encoder,
    ablation: dict[str, Any],
    tolerance: ConsistencyTolerance,
) -> dict[str, Any]:
    dataset = load_rag_eval_v1()
    if (
        ablation["evaluation_protocol"] != "rag-layered-v2-retrieval"
        or ablation["status"] != "MEASURED"
        or ablation["modes"]["rrf"]["status"] != "PASS"
        or ablation["dataset_sha256"] != dataset.manifest.content_sha256
        or ablation["model_revision"] != dataset.protocol.model.revision
    ):
        raise ValueError("需要同一冻结集上完整且 RRF 合格的真实新版消融报告")
    rows = ablation["modes"]["dense"]["rows"]
    if [row["id"] for row in rows] != [query.id for query in dataset.queries]:
        raise ValueError("排序比较必须覆盖完整冻结查询")
    if any(len(row["vectorCandidates"]) >= 20 for row in rows):
        raise ValueError("候选触及服务20条上限,不能证明这是完整授权语料;须另行提供完整接缝")
    documents = {hit["chunkId"]: hit for row in rows for hit in row["vectorCandidates"]}
    vector_pairs: list[VectorPair] = []
    encoded: dict[str, tuple[dict[str, list[float]], dict[str, list[float]]]] = {}
    cases = {
        "query": [(query.id, query.query) for query in dataset.queries],
        "document": [(key, documents[key]["snippet"]) for key in sorted(documents)],
    }
    for kind, samples in cases.items():
        left: dict[str, list[float]] = {}
        right: dict[str, list[float]] = {}
        for size in (1, 8, 32):
            for start in range(0, len(samples), size):
                batch = samples[start : start + size]
                texts = [text for _, text in batch]
                pv = pytorch.encode(texts, query=kind == "query")
                ov = onnx.encode(texts, query=kind == "query")
                for (key, _), pvec, ovec in zip(batch, pv, ov, strict=True):
                    vector_pairs.append(VectorPair(f"{kind}:batch{size}:{key}", pvec, ovec))
                    left[key], right[key] = pvec, ovec
        encoded[kind] = left, right
    # 查询/文档都覆盖短文本与超长右截断,同一内容在不同 batch 中有独立记录。
    for query in (True, False):
        texts = ["物流", "物" * 600 + "甲", "物" * 600 + "乙"]
        pv = pytorch.encode(texts, query=query)
        ov = onnx.encode(texts, query=query)
        for index, (pvec, ovec) in enumerate(zip(pv, ov, strict=True)):
            vector_pairs.append(VectorPair(f"length:query{query}:{index}", pvec, ovec))
        if pv[1] != pv[2] or ov[1] != ov[2]:
            raise ValueError("两种编码器都必须满足冻结右截断规则")
    pq, oq = encoded["query"]
    pd, od = encoded["document"]
    ranking_pairs = []
    baseline_rows = []
    for row in rows:
        ids = [hit["chunkId"] for hit in row["vectorCandidates"]]
        porder = rank_vectors(pq[row["id"]], pd, ids, tolerance.k)
        oorder = rank_vectors(oq[row["id"]], od, ids, tolerance.k)
        service_order = ids[: tolerance.k]
        baseline_rows.append(
            {
                "query_id": row["id"],
                "http_status": row["http_status"],
                "service": service_order,
                "local_pytorch": porder,
                "matches_service": porder == service_order,
            }
        )

        def identity(key: str) -> str:
            hit = documents[key]
            return f"{hit['articleId']}/{hit['version']}/{key}"

        ranking_pairs.append(
            RankingPair(
                row["id"], [identity(key) for key in porder], [identity(key) for key in oorder]
            )
        )
    result = compare_consistency(
        vector_pairs,
        ranking_pairs,
        tolerance=tolerance,
        dimensions=dataset.protocol.model.output_dimensions,
    )
    result["service_baseline"] = baseline_rows
    if not all(row["matches_service"] for row in baseline_rows):
        result["status"] = "FAIL"
    result["ranking_scope"] = "COMPLETE_SPRING_AUTHORIZED_DENSE_CANDIDATES_BELOW_LIMIT"
    result["answer_quality"] = "NOT_EVALUATED"
    return result


def measure_pair(
    model_directory: Path, onnx_directory: Path, *, hardware_id: str
) -> list[dict[str, Any]]:
    queries = tuple(query.query for query in load_rag_eval_v1().queries)
    batches = tuple(queries[start : start + 8] for start in range(0, len(queries), 8))
    factories = {
        "pytorch": ("baseline_agent.knowledge_embedding:OfflineBgeEncoder", model_directory),
        "onnx": ("baseline_agent.knowledge_onnx:OnnxBgeEncoder", onnx_directory),
    }
    rows = []
    for query in (True, False):
        workload = ResourceWorkload(batches, query, 1, 3)
        for repeat in range(3):
            order = ("pytorch", "onnx") if repeat % 2 == 0 else ("onnx", "pytorch")
            for backend in order:
                factory, directory = factories[backend]
                result = measure_encoder(
                    factory, directory, workload, timeout_seconds=300, hardware_id=hardware_id
                )
                rows.append({"repeat": repeat, "query": query, "backend": backend, **result})
                if result["status"] != "MEASURED":
                    return rows
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--onnx-directory", type=Path, required=True)
    parser.add_argument("--ablation", type=Path, required=True)
    parser.add_argument("--tolerance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hardware-id", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    tolerance = ConsistencyTolerance(**json.loads(args.tolerance.read_text(encoding="utf-8")))
    report: dict[str, Any] = {
        "schema": "issue168-onnx-comparison-v1",
        "status": "ERROR",
        "head_sha": args.head_sha,
        "base_sha": args.base_sha,
        "model_revision": load_rag_eval_v1().protocol.model.revision,
        "tolerance": asdict(tolerance),
        "consistency": None,
        "resources": [],
        "default_change": "NOT_AUTHORIZED",
        "answer_quality": "NOT_EVALUATED",
    }
    try:
        report["export"] = export_bge_model(args.model_directory, args.onnx_directory)
        report["consistency"] = compare_encoders(
            OfflineBgeEncoder(args.model_directory),
            OnnxBgeEncoder(args.onnx_directory),
            json.loads(args.ablation.read_text(encoding="utf-8")),
            tolerance,
        )
        report["resources"] = measure_pair(
            args.model_directory, args.onnx_directory, hardware_id=args.hardware_id
        )
        report["status"] = (
            "MEASURED"
            if all(row["status"] == "MEASURED" for row in report["resources"])
            and len(report["resources"]) == 12
            else "ERROR"
        )
    except Exception as error:
        report["error_type"] = type(error).__name__
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0 if report["status"] == "MEASURED" else 1)


if __name__ == "__main__":
    main()
