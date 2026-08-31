"""一次开发可行性候选;不接入默认检索、不训练分类器、不调用云模型。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from baseline_agent.knowledge_answerability import accepted_rows, select_threshold

PROTOCOL_PATH = Path(__file__).with_name("knowledge_reranker_v1.json")


def protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def verify_directory(directory: Path) -> Path:
    directory = directory.resolve(strict=True)
    for name, expected in protocol()["files"].items():
        path = directory / name
        if not path.is_file() or path.stat().st_size != expected["size_bytes"]:
            raise ValueError(f"固定 reranker 文件缺失或长度不符: {name}")
        if "sha256" in expected:
            with path.open("rb") as source:
                actual = hashlib.file_digest(source, "sha256").hexdigest()
            target = expected["sha256"]
        else:
            data = path.read_bytes()
            actual = hashlib.sha1(
                f"blob {len(data)}\0".encode() + data, usedforsecurity=False
            ).hexdigest()
            target = expected["git_blob_sha1"]
        if actual != target:
            raise ValueError(f"固定 reranker 文件哈希不符: {name}")
    return directory


class OfflineReranker:
    def __init__(self, directory: Path):
        path = verify_directory(directory)
        # 模型文件校验通过后才导入框架;运行阶段不能下载模型。
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self._protocol = protocol()
        torch.set_num_threads(self._protocol["torch_threads"])
        torch.use_deterministic_algorithms(True)
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(path),
            use_fast=True,
            local_files_only=True,
            trust_remote_code=False,
            truncation_side=self._protocol["truncation_side"],
        )
        if not self._tokenizer.is_fast:
            raise ValueError("需要固定 tokenizer.json 的 fast tokenizer")
        self._model = (
            AutoModelForSequenceClassification.from_pretrained(
                str(path),
                local_files_only=True,
                trust_remote_code=False,
                use_safetensors=True,
                attn_implementation="eager",
            )
            .to(device="cpu", dtype=torch.float32)
            .eval()
        )

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not query.strip() or not 1 <= len(passages) <= 5:
            raise ValueError("需要一个问题和原合法 Top5 片段")
        scores = []
        with self._torch.inference_mode():
            for passage in passages:
                tokens = self._tokenizer(
                    query,
                    passage,
                    padding=True,
                    truncation=self._protocol["truncation"],
                    max_length=self._protocol["max_length"],
                    return_tensors="pt",
                )
                logits = self._model(**tokens).logits
                if logits.shape != (1, 1) or not bool(self._torch.isfinite(logits).all()):
                    raise ValueError("reranker 必须返回单个有限原始 logit")
                scores.append(float(logits.item()))
        return scores


def evaluate_development(
    rows: list[dict[str, Any]],
    score: Callable[[str, list[str]], list[float]],
    report: dict[str, Any],
) -> None:
    """保留原候选顺序,只选择一次整体接受/拒答界限;不导出产品参数。"""
    report["rows"] = []
    maximum_scores = []
    for row in rows:
        hits = row["fusedCandidates"]
        if not 1 <= len(hits) <= 5 or any(hit["applicability"] != ["INTERNAL"] for hit in hits):
            raise ValueError("固定开发 Top5 或历史授权范围不符")
        values = score(row["text"], [hit["snippet"] for hit in hits])
        if len(values) != len(hits) or any(not math.isfinite(value) for value in values):
            raise ValueError("reranker 分数数量或有限性不符")
        maximum = max(values)
        maximum_scores.append(maximum)
        report["rows"].append(
            {
                "query_id": row["id"],
                "candidate_chunk_ids": [hit["chunkId"] for hit in hits],
                "candidate_logits": values,
                "maximum_logit": maximum,
            }
        )
    selection = select_threshold(rows, maximum_scores)
    report["selection"] = selection
    selected = selection["selected"]
    report["status"] = "DEVELOPMENT_FEASIBLE" if selected else "INFEASIBLE"
    report["metrics"] = selected["metrics"] if selected else None
    if selected:
        decisions = accepted_rows(rows, maximum_scores, selected["threshold"])
        for source, recorded, accept in zip(rows, report["rows"], decisions, strict=True):
            recorded["accepted"] = accept
            recorded["results"] = source["fusedCandidates"] if accept else []
