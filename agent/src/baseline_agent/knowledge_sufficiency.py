"""C实验的固定合成回放合同。不接入默认产品策略或读取未见留出。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast

from baseline_agent.knowledge_answerability import QUALITY, measure

ASSETS = Path(__file__).with_name("knowledge_sufficiency_v1")
REPO = Path(__file__).resolve().parents[3]
ARCHIVE = "docs/implementation/evidence/issue190-logistic-fit-20260831b/calibration-collect.json"
ARCHIVE_SHA256 = "b4ec9872012c90c795b0356a74f9ac3f4f7343bff207a76b16d9185265b06387"
SOURCE_SHA = "98b49949d6d835d510c4959d787b443fa95bc794"
DATA_SHA256 = "4ba56767f8729ba064f614c856076c30f08e5852bad0255c2bf6b443c31014b6"
BGE_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
ASSET_SHA256 = {
    "prompt.txt": "38d163c700dbdd5d39872864d781f573d06c05d23439f17044685dda201fd494",
    "schema.json": "27ef4d19440b4279ac4b0426eb299e87445a455be5206716ad82c0da6f3733f4",
    "config.json": "11e970eca4aa7ee711af9602f14eea5a5c4ea28efe1e67c74f712843b9cbad45",
}
V2_ASSETS = Path(__file__).with_name("knowledge_sufficiency_v2")
V2_ASSET_SHA256 = {
    "prompt.txt": "a18bfb7648847dd9b040cdcbb9832e21e50143b9b1496068a1b645c2c4fa9b32",
    "schema.json": "27ef4d19440b4279ac4b0426eb299e87445a455be5206716ad82c0da6f3733f4",
    "config.json": "3716498d23b0ce1586599d7ad6f7ae28bab913414b28607ea1105899a3167212",
}
CONTRACT_CHECK_LAYERS = (
    "json_syntax",
    "decision_schema",
    "evidence_fields",
    "cross_fields",
    "authorized_chunks",
    "verbatim_quotes",
)


class SufficiencyBlocked(ValueError):
    """仅保存固定错误代码与脱敏调用元数据,不转抄供应商错误正文。"""

    def __init__(self, code: str, observation: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.observation = observation or {}


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def contract(*, c_v2: bool = False) -> dict[str, Any]:
    assets = V2_ASSETS if c_v2 else ASSETS
    expected = V2_ASSET_SHA256 if c_v2 else ASSET_SHA256
    hashes = {name: sha256((assets / name).read_bytes()) for name in expected}
    if hashes != expected:
        raise SufficiencyBlocked("FROZEN_CONTRACT_CHANGED")
    config = json.loads((assets / "config.json").read_text(encoding="utf-8"))
    prompt = (assets / "prompt.txt").read_text(encoding="utf-8")
    schema = json.loads((assets / "schema.json").read_text(encoding="utf-8"))
    return {
        "config": config,
        "prompt": prompt,
        "schema": schema,
        "asset_sha256": hashes,
    }


def development_rows(repo: Path = REPO) -> list[dict[str, Any]]:
    # 不接受任意数据文件/留出路径。固定归档hash同时绑定合成来源与当时硬过滤结果。
    content = (repo / ARCHIVE).read_bytes()
    if sha256(content) != ARCHIVE_SHA256:
        raise SufficiencyBlocked("SYNTHETIC_ARCHIVE_MISMATCH")
    observed = json.loads(content)
    rows = observed["rows"]
    if (
        observed["status"] != "COLLECTED"
        or observed["split"] != "calibration"
        or observed["head_sha"] != SOURCE_SHA
        or observed["dataset_sha256"] != DATA_SHA256
        or observed["model_revision"] != BGE_REVISION
        or len(rows) != 72
        or len({row["id"] for row in rows}) != 72
    ):
        raise SufficiencyBlocked("DEVELOPMENT_PROVENANCE_MISMATCH")
    return rows


def request_body(row: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    hits = row["fusedCandidates"]
    if not 1 <= len(hits) <= 5:
        raise SufficiencyBlocked("INVALID_FIXED_TOP5")
    if any(hit["applicability"] != ["INTERNAL"] for hit in hits):
        raise SufficiencyBlocked("ARCHIVE_SCOPE_MISMATCH")
    config = frozen["config"]
    return {
        "model": config["model"],
        "instructions": frozen["prompt"],
        # 只有问题和完整片段正文外发: 不传标签、支持答案、特征、分数或真实身份。
        "input": json.dumps(
            {
                "question": row["text"],
                "chunks": [
                    {"chunk": index, "text": hit["snippet"]} for index, hit in enumerate(hits, 1)
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "reasoning": config["reasoning"],
        "temperature": config["temperature"],
        "max_output_tokens": config["max_output_tokens"],
        "stream": config["stream"],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "knowledge_sufficiency_c_v2"
                if config["method"] == "context-sufficiency-c-v2"
                else "knowledge_sufficiency_c_v1",
                "strict": True,
                "schema": frozen["schema"],
            }
        },
    }


def budget_plan(frozen: dict[str, Any]) -> dict[str, Any]:
    config = frozen["config"]
    prices = config["pricing_cny_per_million"]
    # 微元整数: 不将USD估算当CNY,不把字符长度当计费token,不预支缓存折扣。
    per_call = (
        config["input_bound"]["tokens"] * prices["uncached_input"]
        + config["max_output_tokens"] * prices["output"]
    )
    forecast_per_call = (
        config["forecast_input_tokens_per_call"] * prices["uncached_input"]
        + config["max_output_tokens"] * prices["output"]
    )
    stages = {
        name: {"maximum_calls": count, "forecast_micro_cny": count * forecast_per_call}
        for name, count in config["validation_call_plan"].items()
    }
    return {
        "status": "BOUNDED_SPEND_NOT_COMPLETION_GUARANTEE",
        "total_budget_micro_cny": config["total_budget_micro_cny"],
        "per_call_reservation_micro_cny": per_call,
        "forecast_micro_cny": sum(stage["forecast_micro_cny"] for stage in stages.values()),
        "stages": stages,
        "all_necessary_validation_inventory_verified": False,
        "smaller_request_input_bound_verified": False,
        "forecast_is_not_spend_or_input_limit": True,
    }


def response_observation(payload: dict[str, Any], duration_ms: int) -> dict[str, Any]:
    observation: dict[str, Any] = {
        key: payload.get(source) if isinstance(payload.get(source), str) else None
        for key, source in (
            ("response_model", "model"),
            ("system_fingerprint", "system_fingerprint"),
            ("response_id", "id"),
            ("response_status", "status"),
        )
    }
    observation.update(duration_ms=duration_ms, usage_trusted=False)
    model = observation["response_model"]
    if not isinstance(model, str) or not re.fullmatch(r"deepseek-v4-flash(?:-[0-9]{4,8})?", model):
        return observation
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return observation
    keys = ("input_tokens", "output_tokens", "total_tokens")
    counts = [usage.get(key) for key in keys]
    observation["usage"] = {key: usage[key] for key in keys if type(usage.get(key)) is int}
    if any(type(value) is not int or value < 0 for value in counts):
        return observation
    # 上面已逐项验证整数和非负;显式收窄,不改变usage准入条件。
    inputs, outputs, total = (cast(int, value) for value in counts)
    if total != inputs + outputs or inputs > 1_048_576 or outputs > 256:
        return observation
    details = usage.get("output_tokens_details")
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
    cache = usage.get("input_tokens_details")
    cached = cache.get("cached_tokens") if isinstance(cache, dict) else None
    observation.update(reasoning_tokens=reasoning, cached_tokens=cached)
    if (
        type(reasoning) is not int
        or not 0 <= reasoning <= outputs
        or (cached is not None and (type(cached) is not int or not 0 <= cached <= inputs))
    ):
        return observation
    # 峰值无缓存价格作支出上界;不是账单实付金额。与语义判定是否成功分开。
    observation.update(usage_trusted=True, usage_upper_micro_cny=inputs * 3 + outputs * 9)
    return observation


def parse_response(
    payload: dict[str, Any],
    row: dict[str, Any],
    *,
    expected_identity: tuple[str, str | None] | None,
    duration_ms: int,
    c_v2: bool = False,
) -> dict[str, Any]:
    """供应商契约解析;首次实返标识由实验账本持久化,后续逐次比较。"""
    model = payload.get("model")
    fingerprint = payload.get("system_fingerprint")
    observation = response_observation(payload, duration_ms)
    checks: dict[str, str] = dict.fromkeys(CONTRACT_CHECK_LAYERS, "NOT_EVALUATED")
    if c_v2:
        observation["contract_checks"] = checks

    def check_layer(name: str, valid: bool, code: str) -> None:
        if c_v2:
            checks[name] = "PASS" if valid else "FAIL"
        if not valid:
            raise SufficiencyBlocked(code, observation)

    if (
        payload.get("object") != "response"
        or payload.get("status") != "completed"
        or payload.get("error") is not None
        or payload.get("incomplete_details") is not None
        or not observation["response_id"]
    ):
        raise SufficiencyBlocked("PROVIDER_RESPONSE_NOT_COMPLETED", observation)
    if (
        not isinstance(model, str)
        or not re.fullmatch(r"deepseek-v4-flash(?:-[0-9]{4,8})?", model)
        or (fingerprint is not None and not isinstance(fingerprint, str))
    ):
        raise SufficiencyBlocked("PROVIDER_IDENTITY_INVALID", observation)
    if expected_identity is not None and (model, fingerprint) != expected_identity:
        raise SufficiencyBlocked("PROVIDER_IDENTITY_DRIFT", observation)
    if not observation["usage_trusted"]:
        raise SufficiencyBlocked("USAGE_UNTRUSTED", observation)
    if observation["reasoning_tokens"] != 0:
        raise SufficiencyBlocked("TOKEN_CONTRACT_INVALID", observation)
    output = payload.get("output")
    if not isinstance(output, list) or len(output) != 1:
        raise SufficiencyBlocked("OUTPUT_CONTRACT_INVALID", observation)
    message = output[0]
    if (
        not isinstance(message, dict)
        or message.get("type") != "message"
        or message.get("role") != "assistant"
        or message.get("status") != "completed"
    ):
        raise SufficiencyBlocked("OUTPUT_CONTRACT_INVALID", observation)
    content = message.get("content")
    if (
        not isinstance(content, list)
        or len(content) != 1
        or not isinstance(content[0], dict)
        or content[0].get("type") != "output_text"
        or not isinstance(content[0].get("text"), str)
    ):
        raise SufficiencyBlocked("OUTPUT_CONTRACT_INVALID", observation)
    try:
        decision = json.loads(content[0]["text"])
    except json.JSONDecodeError:
        if c_v2:
            checks["json_syntax"] = "FAIL"
        raise SufficiencyBlocked("INVALID_DECISION_JSON", observation) from None
    check_layer("json_syntax", True, "INVALID_DECISION_JSON")
    check_layer(
        "decision_schema",
        isinstance(decision, dict)
        and set(decision) == {"sufficient", "evidence"}
        and type(decision["sufficient"]) is bool
        and isinstance(decision["evidence"], list),
        "INVALID_DECISION_SCHEMA",
    )
    evidence = decision["evidence"]
    hits = row["fusedCandidates"]
    check_layer(
        "evidence_fields",
        len(evidence) <= 5
        and all(
            isinstance(item, dict)
            and set(item) == {"chunk", "quote"}
            and type(item["chunk"]) is int
            and isinstance(item["quote"], str)
            and 1 <= len(item["quote"]) <= 24
            for item in evidence
        ),
        "INVALID_EVIDENCE",
    )
    check_layer("cross_fields", bool(evidence) == decision["sufficient"], "INVALID_EVIDENCE")
    check_layer(
        "authorized_chunks",
        all(1 <= item["chunk"] <= len(hits) for item in evidence),
        "INVALID_EVIDENCE",
    )
    check_layer(
        "verbatim_quotes",
        all(
            item["quote"].strip() and item["quote"] in hits[item["chunk"] - 1]["snippet"]
            for item in evidence
        ),
        "INVALID_EVIDENCE",
    )
    if not c_v2 and len({item["chunk"] for item in evidence}) != len(evidence):
        raise SufficiencyBlocked("INVALID_EVIDENCE", observation)
    return {"decision": decision, "observation": observation}


def replay_metrics(rows: list[dict[str, Any]], decisions: list[bool]) -> dict[str, Any]:
    if len(rows) != 72 or len(decisions) != 72 or any(type(x) is not bool for x in decisions):
        raise SufficiencyBlocked("INCOMPLETE_REPLAY_NOT_QUALITY_RESULT")
    values = measure(rows, decisions)
    return {
        "status": "PASS" if all(values[key] >= limit for key, limit in QUALITY.items()) else "FAIL",
        "metrics": values,
        "quality_thresholds": dict(QUALITY),
        "permission_validation": "NOT_RERUN_ARCHIVE_ONLY",
        "product_validation": "NOT_RUN",
    }
