"""独立开发数据的一次阈值选择与留出审计;不导入冻结评测查询。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import time
from dataclasses import asdict
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from typing import Any

from baseline_agent import knowledge_embedding
from baseline_agent.knowledge_calibration_v1 import DATA_PATH, load_development_data


def classification(rows: list[dict[str, Any]], threshold: float) -> dict[str, float]:
    positives = [row for row in rows if row["expected_chunks"]]
    negatives = [row for row in rows if not row["expected_chunks"]]
    if not positives or not negatives:
        raise ValueError("校准和审计组都必须包含有答案与无答案样本")
    return {
        "answerable_acceptance": sum(row["score"] >= threshold for row in positives)
        / len(positives),
        "unanswerable_rejection": sum(row["score"] < threshold for row in negatives)
        / len(negatives),
    }


def choose_threshold(rows: list[dict[str, Any]]) -> float:
    calibration = [row for row in rows if row["split"] == "calibration"]
    scores = sorted({float(row["score"]) for row in calibration})
    if not scores or any(not math.isfinite(score) or not -1 <= score <= 1 for score in scores):
        raise ValueError("缺少有效的校准分数")
    candidates = [
        -1.0,
        1.0,
        *[(left + right) / 2 for left, right in pairwise(scores)],
    ]

    def objective(threshold: float) -> tuple[float, float, float]:
        values = classification(calibration, threshold).values()
        return min(values), sum(values) / 2, threshold

    return max(candidates, key=objective)


def cosine(left: list[float], right: list[float]) -> float:
    dot = math.fsum(a * b for a, b in zip(left, right, strict=True))
    norms = math.sqrt(math.fsum(a * a for a in left) * math.fsum(b * b for b in right))
    return max(-1.0, min(1.0, dot / norms))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--working-tree-dirty", action="store_true")
    args = parser.parse_args()
    # 先独占创建报告,防止覆盖前次证据。仅由持锁 PowerShell 入口启动。
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        started = time.perf_counter()
        report: dict[str, Any] = {
            "dataset_id": "knowledge-calibration-v1",
            "dataset_sha256": hashlib.sha256(DATA_PATH.read_bytes()).hexdigest(),
            "source_sha256": {
                name: hashlib.sha256(path.read_bytes()).hexdigest()
                for name, path in {
                    "calibrator": Path(__file__),
                    "encoder": Path(knowledge_embedding.__file__),
                    "dataset_loader": DATA_PATH.with_name("__init__.py"),
                }.items()
            },
            "run_id": args.run_id,
            "head_sha": args.head_sha,
            "base_sha": args.base_sha,
            "working_tree_dirty": args.working_tree_dirty,
            "status": "ERROR",
            "paid_model_cost_cny": 0,
            "environment": {"python": platform.python_version(), "platform": platform.platform()},
            "selection": "calibration-only max(min(class recalls)), then balanced accuracy, then higher threshold",
            "rows": [],
            "proposed_policy": None,
        }
        try:
            report["environment"].update(
                {name: version(name) for name in ("torch", "transformers", "safetensors")}
            )
            report["model"] = knowledge_embedding.load_model_protocol()
            encoder = knowledge_embedding.configured_encoder()
            documents, queries = load_development_data()
            ids = list(documents)
            vectors: list[list[float]] = []
            for start in range(0, len(ids), 32):
                vectors.extend(
                    encoder.encode([documents[key] for key in ids[start : start + 32]], query=False)
                )
            for query in queries:
                vector = encoder.encode([query.text], query=True)[0]
                candidates: list[dict[str, Any]] = [
                    {"chunk_id": key, "score": cosine(vector, value)}
                    for key, value in zip(ids, vectors, strict=True)
                ]
                candidates.sort(key=lambda hit: (-hit["score"], hit["chunk_id"]))
                top_ids = {hit["chunk_id"] for hit in candidates[:5]}
                report["rows"].append(
                    {
                        **asdict(query),
                        "score": candidates[0]["score"],
                        "candidates": candidates,
                        "required_chunks_in_top5": all(
                            key in top_ids for key in query.expected_chunks
                        ),
                    }
                )
            threshold = choose_threshold(report["rows"])
            report["threshold"] = threshold
            report["splits"] = {
                split: {
                    "count": len(rows := [row for row in report["rows"] if row["split"] == split]),
                    **classification(rows, threshold),
                    "answerable_recall_at_5": sum(
                        row["required_chunks_in_top5"] for row in rows if row["expected_chunks"]
                    )
                    / sum(bool(row["expected_chunks"]) for row in rows),
                }
                for split in ("calibration", "audit")
            }
            report["proposed_policy"] = {
                "id": "independent-cosine-v1",
                "status": "CALIBRATED",
                "modelRevision": report["model"]["revision"],
                "calibrationDatasetSha256": report["dataset_sha256"],
                "threshold": threshold,
            }
            report["status"] = "MEASURED"
        except Exception as error:
            report["error_type"] = type(error).__name__
        finally:
            report["elapsed_seconds"] = time.perf_counter() - started
            json.dump(report, output, ensure_ascii=False, indent=2)
    # MEASURED 表示选参和审计已执行,不是冻结质量 PASS,也不会自动修改产品配置。
    raise SystemExit(0 if report["status"] == "MEASURED" else 1)


if __name__ == "__main__":
    main()
