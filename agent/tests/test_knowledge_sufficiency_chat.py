"""Beta strict输出通道的离线契约;Mock不代表供应商支持或质量通过。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_knowledge_sufficiency import row

from baseline_agent.knowledge_sufficiency import (
    REPO,
    SUFFICIENCY_FUNCTION,
    SufficiencyBlocked,
    contract,
    development_rows,
    parse_response,
    request_body,
    response_observation,
    sha256,
)
from baseline_agent.knowledge_sufficiency_run import ExperimentLedger, run_development

C5_ARCHIVE = REPO / "docs/implementation/evidence/issue190-development-c5-20260831a"


def chat_payload(arguments: str = '{"sufficient":false,"evidence":[]}') -> dict[str, Any]:
    return {
        "id": "synthetic-chat-response",
        "object": "chat.completion",
        "model": "deepseek-v4-flash",
        "system_fingerprint": None,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "synthetic-call",
                            "type": "function",
                            "function": {"name": SUFFICIENCY_FUNCTION, "arguments": arguments},
                        }
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 10,
            "prompt_cache_miss_tokens": 90,
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


def test_beta_request_keeps_context_and_uses_supported_schema() -> None:
    frozen = contract(development_version="c6")
    source = row()
    source["fusedCandidates"][0]["snippet"] += "长正文" * 1000
    body = request_body(source, frozen)
    prior = request_body(source, contract(development_version="c5"))
    assert body["messages"][1]["content"] == prior["input"]
    assert "must-not-leave" not in json.dumps(body)
    assert frozen["config"]["endpoint"] == "https://api.deepseek.com/beta/chat/completions"
    assert body["thinking"] == {"type": "disabled"}
    assert body["max_tokens"] == 256 and body["stream"] is False
    assert body["tool_choice"] == {"type": "function", "function": {"name": SUFFICIENCY_FUNCTION}}
    assert len(body["tools"]) == 1 and body["tools"][0]["function"]["strict"] is True
    schema = body["tools"][0]["function"]["parameters"]
    assert schema["properties"]["evidence"]["items"]["properties"]["quote"]["pattern"] == (
        r"^[\s\S]{1,24}$"
    )
    assert not {"response_format", "reasoning", "previous_response_id"} & body.keys()
    assert not any(key in json.dumps(schema) for key in ("minLength", "maxLength", "maxItems"))


def test_old_c5_request_bytes_are_unchanged() -> None:
    manifest = json.loads((C5_ARCHIVE / "requests.json").read_text(encoding="utf-8-sig"))
    frozen = contract(development_version="c5")
    actual = [
        {
            "query_id": source["id"],
            "request_sha256": sha256(
                json.dumps(
                    request_body(source, frozen), ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            ),
        }
        for source in development_rows()
    ]
    assert actual == manifest


@pytest.mark.parametrize("details_present", [True, False])
def test_chat_usage_and_decision_preserve_raw_quotes(details_present: bool) -> None:
    decision = {
        "sufficient": True,
        "evidence": [{"chunk": 1, "quote": "日落时关闭"}] * 2,
    }
    response = chat_payload(json.dumps(decision, ensure_ascii=False))
    if not details_present:
        del response["usage"]["completion_tokens_details"]
    parsed = parse_response(
        response,
        row(),
        expected_identity=("deepseek-v4-flash", None),
        duration_ms=1,
        c_v2=True,
        chat=True,
    )
    assert parsed["decision"] == decision
    observation = parsed["observation"]
    assert observation["usage"] == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    assert observation["usage_upper_micro_cny"] == 480
    assert observation["reasoning_tokens"] == (0 if details_present else None)
    assert observation["wire_usage"]["prompt_tokens"] == 100
    assert observation["response_status"] == "tool_calls"
    assert set(observation["contract_checks"].values()) == {"PASS"}


@pytest.mark.parametrize(
    "evidence,layer",
    [
        ([{"chunk": 1, "quote": "甲" * 25}], "evidence_fields"),
        ([{"chunk": 1, "quote": "日落时关闭"}] * 6, "evidence_fields"),
        ([{"chunk": True, "quote": "日落时关闭"}], "evidence_fields"),
        ([{"chunk": 6, "quote": "日落时关闭"}], "authorized_chunks"),
        ([{"chunk": 1, "quote": "不存在的原文"}], "verbatim_quotes"),
        ([], "cross_fields"),
    ],
)
def test_chat_keeps_local_evidence_checks(evidence: list[dict[str, Any]], layer: str) -> None:
    response = chat_payload(json.dumps({"sufficient": True, "evidence": evidence}))
    with pytest.raises(SufficiencyBlocked, match="INVALID_EVIDENCE") as error:
        parse_response(response, row(), expected_identity=None, duration_ms=1, c_v2=True, chat=True)
    assert error.value.observation["contract_checks"][layer] == "FAIL"


@pytest.mark.parametrize("defect", ["length", "plain-message", "two-calls", "other-function"])
def test_chat_never_accepts_truncation_or_falls_back_to_message(defect: str) -> None:
    response = chat_payload()
    choice = response["choices"][0]
    message = choice["message"]
    if defect == "length":
        choice["finish_reason"] = "length"
    elif defect == "plain-message":
        message["content"] = '{"sufficient":false,"evidence":[]}'
        del message["tool_calls"]
    elif defect == "two-calls":
        message["tool_calls"] *= 2
    else:
        message["tool_calls"][0]["function"]["name"] = "other_function"
    with pytest.raises(SufficiencyBlocked):
        parse_response(response, row(), expected_identity=None, duration_ms=1, c_v2=True, chat=True)
    assert response_observation(response, 1, chat=True)["usage_upper_micro_cny"] == 480


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["quote", "missing-usage", "http-400", "timeout", "drift"])
async def test_chat_failure_stops_once_and_preserves_budget_history(
    tmp_path: Path, defect: str
) -> None:
    path = tmp_path / "ledger.json"
    path.write_bytes((C5_ARCHIVE / "cost-ledger.json").read_bytes())
    frozen = contract(development_version="c6")
    ledger = ExperimentLedger(path, frozen)
    # 模拟其他已完成阶段;不读取独立留出的账本或结果。
    ledger.state["phases"]["synthetic_previous_phase"] = {"status": "STOPPED"}
    original = copy.deepcopy(ledger.state)
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["attempts"][-1]["status"] == "PENDING"
        assert saved["attempts"][-1]["request_sha256"] == sha256(request.content)
        assert str(request.url) == frozen["config"]["endpoint"]
        if defect == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if defect == "http-400":
            return httpx.Response(400, json={"error": "synthetic unsupported schema"})
        response = chat_payload()
        if defect == "quote":
            response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = (
                '{"sufficient":true,"evidence":[{"chunk":1,"quote":"test-key"}]}'
            )
        elif defect == "missing-usage":
            del response["usage"]
        else:
            response["system_fingerprint"] = "changed"
        return httpx.Response(200, json=response)

    report: dict[str, Any] = {"run_id": "c6-offline-failure", "metrics": None}
    with pytest.raises(SufficiencyBlocked):
        await run_development(
            report,
            ledger,
            frozen,
            api_key="test-key",
            development_version="c6",
            transport=httpx.MockTransport(handle),
        )
    ledger.finish("STOPPED")
    assert calls == 1 and report["rows"] == [] and report["metrics"] is None
    assert ledger.state["attempts"][:-1] == original["attempts"]
    assert all(ledger.state["phases"][key] == value for key, value in original["phases"].items())
    settled = defect in {"quote", "drift"}
    assert ledger.totals() == {
        "settled_upper_micro_cny": 473070 + (480 if settled else 0),
        "unsettled_reserved_micro_cny": 0 if settled else 3148032,
    }
    observation = ledger.state["attempts"][-1]["observation"]
    if defect == "quote":
        diagnostic = observation["decision_diagnostic"]
        assert "[REDACTED]" in diagnostic["output_text"]
        assert "test-key" not in diagnostic["output_text"]
        assert observation["contract_checks"]["verbatim_quotes"] == "FAIL"


@pytest.mark.asyncio
async def test_chat_whole_development_keeps_one_request_per_query(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    path.write_bytes((C5_ARCHIVE / "cost-ledger.json").read_bytes())
    frozen = contract(development_version="c6")
    ledger = ExperimentLedger(path, frozen)
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert len(json.loads(request.content)["messages"]) == 2
        return httpx.Response(200, json=chat_payload())

    report: dict[str, Any] = {"run_id": "c6-offline-whole", "metrics": None}
    await run_development(
        report,
        ledger,
        frozen,
        api_key="offline-only",
        development_version="c6",
        transport=httpx.MockTransport(handle),
    )
    assert calls == len(report["rows"]) == len(report["request_manifest"]) == 72
    assert report["contract_validation"] == "PASS_72_OF_72"
    assert report["semantic_validation"] == "FAIL"  # 全拒答的Mock不能冒充模型质量。
    assert ledger.totals() == {
        "settled_upper_micro_cny": 507630,
        "unsettled_reserved_micro_cny": 0,
    }
