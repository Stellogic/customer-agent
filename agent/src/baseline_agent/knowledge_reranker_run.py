"""固定72题的单次本地可行性入口；不提供留出、冻结集或续跑模式。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

from baseline_agent.knowledge_reranker import (
    PROTOCOL_PATH,
    OfflineReranker,
    evaluate_development,
    protocol,
    verify_directory,
)
from baseline_agent.knowledge_sufficiency import (
    ARCHIVE,
    ARCHIVE_SHA256,
    DATA_SHA256,
    SOURCE_SHA,
    development_rows,
)
from baseline_agent.knowledge_sufficiency_run import write_json


def prepare(directory: Path) -> None:
    # 仅显式 prepare 阶段下载，不由评分器触发，也不生成新依赖锁。
    import httpx

    fixed = protocol()
    directory.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        for name in fixed["files"]:
            with client.stream(
                "GET",
                f"https://huggingface.co/{fixed['model']}/resolve/{fixed['revision']}/{name}",
            ) as response:
                response.raise_for_status()
                with (directory / name).open("wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
    verify_directory(directory)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "development"))
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    if not os.environ.get("CUSTOMER_AGENT_TEST_GATE_TOKEN"):
        raise ValueError("须通过持有仓库锁的 PowerShell 入口运行")
    report: dict[str, Any] = {
        "schema": "issue190-reranker-feasibility-v1",
        "phase": args.phase,
        "status": "RUNNING",
        "run_id": args.run_id,
        "head_sha": args.head_sha,
        "base_sha": args.base_sha,
        "protocol": protocol(),
        "protocol_sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
        "source_archive": ARCHIVE,
        "source_archive_sha256": ARCHIVE_SHA256,
        "source_dataset_sha256": DATA_SHA256,
        "source_head_sha": SOURCE_SHA,
        "quality_scope": "SEEN_DEVELOPMENT_NOT_HOLDOUT_OR_DELIVERY",
        "permission_validation": "NOT_RERUN_ARCHIVE_ONLY",
        "product_validation": "NOT_RUN",
        "paid_model_cost_cny": 0,
        "metrics": None,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "libraries": {name: version(name) for name in ("torch", "transformers", "safetensors")},
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # 正式入口给 development 固定的共享路径；换 RunId 不会重启终结阶段。
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    started = time.perf_counter()
    try:
        if args.phase == "prepare":
            prepare(args.model_directory)
            report["status"] = "PREPARED"
        else:
            rows = development_rows()
            model = OfflineReranker(args.model_directory)
            evaluate_development(rows, model.score, report)
    except Exception as error:
        report.update(status="ERROR", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report["duration_seconds"] = time.perf_counter() - started
        report["completed_queries"] = len(report.get("rows", []))
        write_json(args.output, report)
    if report["status"] == "INFEASIBLE":
        raise SystemExit("无可行界限，停止；不重选、不进入独立验证或冻结门。")


if __name__ == "__main__":
    main()
