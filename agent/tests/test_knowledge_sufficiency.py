"""C接缝离线契约测试源码。MockTransport不是模型质量证据,不得作为真实回退。"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import baseline_agent.knowledge_sufficiency_run as runner
from baseline_agent.knowledge_sufficiency import (
    ARCHIVE,
    SufficiencyBlocked,
    budget_plan,
    contract,
    development_rows,
    parse_response,
    replay_metrics,
    request_body,
    response_observation,
)
from baseline_agent.knowledge_sufficiency_run import ExperimentLedger, run_development


@pytest.mark.asyncio
async def test_remaining_diagnostic_preserves_67_order_history_and_null_metrics(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cost.json"
    path.write_bytes(runner.REMAINING_LEDGER.read_bytes())
    frozen = contract()
    ledger = ExperimentLedger(path, frozen)
    original = copy.deepcopy(ledger.state)
    source = development_rows()
    expected = [item["query_id"] for item in runner.remaining_manifest()["requests"]]
    assert expected == [item["id"] for item in source[5:]] and len(expected) == 67
    assert not set(expected) & {item["query_id"] for item in original["attempts"]}
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        stored = json.loads(path.read_text(encoding="utf-8"))
        entry = stored["attempts"][-1]
        assert entry["query_id"] == expected[calls]
        assert entry["request_sha256"] == hashlib.sha256(request.content).hexdigest()
        assert entry["status"] == "PENDING"
        calls += 1
        response = payload(fingerprint=None)
        response["model"] = "deepseek-v4-flash"
        response["output"][0]["content"][0]["text"] = '{"sufficient":false,"evidence":[]}'
        return httpx.Response(200, json=response)

    report: dict[str, Any] = {"run_id": "remaining-complete-offline", "metrics": None}
    await run_development(
        report,
        ledger,
        frozen,
        api_key="offline-only",
        transport=httpx.MockTransport(handle),
        diagnose_remaining_once=True,
    )
    ledger.finish(report["status"])
    assert calls == 67
    assert report["status"] == "DIAGNOSTIC_COMPLETED" and report["metrics"] is None
    assert "quality_thresholds" not in report
    assert [item["query_id"] for item in report["rows"]] == expected
    assert ledger.state["attempts"][:6] == original["attempts"]
    for phase, record in original["phases"].items():
        assert ledger.state["phases"][phase] == record
    assert ledger.totals() == {
        "settled_upper_micro_cny": 42933,
        "unsettled_reserved_micro_cny": 0,
    }
    with pytest.raises(SufficiencyBlocked, match="CALL_LIMIT_NO_RETRY"):
        ledger.reserve(expected[0], report["request_manifest"][0]["request_sha256"])
    resumed = ExperimentLedger(path, frozen)
    with pytest.raises(SufficiencyBlocked, match="REMAINING_ALREADY_STARTED_NO_RETRY"):
        await run_development(
            {"run_id": "must-not-replay"},
            resumed,
            frozen,
            api_key="offline-only",
            transport=httpx.MockTransport(handle),
            diagnose_remaining_once=True,
        )
    assert calls == 67


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["invalid", "drift", "unknown_usage", "supplier"])
async def test_remaining_diagnostic_stops_on_first_error_without_retry_or_quality(
    tmp_path: Path,
    failure: str,
) -> None:
    path = tmp_path / "cost.json"
    path.write_bytes(runner.REMAINING_LEDGER.read_bytes())
    frozen = contract()
    ledger = ExperimentLedger(path, frozen)
    original = copy.deepcopy(ledger.state)
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        response = payload(fingerprint=None)
        response["model"] = "deepseek-v4-flash"
        response["output"][0]["content"][0]["text"] = '{"sufficient":false,"evidence":[]}'
        if calls == 3:
            if failure == "supplier":
                return httpx.Response(402, json={"error": "offline-only"})
            if failure == "unknown_usage":
                del response["usage"]
            elif failure == "drift":
                response["system_fingerprint"] = "changed-offline"
            else:
                response["output"][0]["content"][0]["text"] = '{"sufficient":"false"}'
        return httpx.Response(200, json=response)

    expected_error = {
        "invalid": "INVALID_DECISION_SCHEMA",
        "drift": "PROVIDER_IDENTITY_DRIFT",
        "unknown_usage": "USAGE_UNTRUSTED",
        "supplier": "INSUFFICIENT_BALANCE",
    }[failure]
    report: dict[str, Any] = {"run_id": "remaining-stop-offline", "metrics": None}
    with pytest.raises(SufficiencyBlocked, match=expected_error):
        await run_development(
            report,
            ledger,
            frozen,
            api_key="offline-only",
            transport=httpx.MockTransport(handle),
            diagnose_remaining_once=True,
        )
    ledger.finish("STOPPED")
    assert calls == 3 and len(report["rows"]) == 2 and report["metrics"] is None
    assert ledger.state["attempts"][:6] == original["attempts"]
    for phase, record in original["phases"].items():
        assert ledger.state["phases"][phase] == record
    assert ledger.totals() == {
        "settled_upper_micro_cny": 11733 if failure in {"unknown_usage", "supplier"} else 12213,
        "unsettled_reserved_micro_cny": 3148032 if failure in {"unknown_usage", "supplier"} else 0,
    }
    if failure == "invalid":
        assert "decision_diagnostic" in ledger.state["attempts"][-1]["observation"]
    resumed = ExperimentLedger(path, frozen)
    before = path.read_bytes()
    with pytest.raises(SufficiencyBlocked, match="REMAINING_ALREADY_STARTED_NO_RETRY"):
        await run_development(
            {"run_id": "new-id-not-allowed"},
            resumed,
            frozen,
            api_key="offline-only",
            transport=httpx.MockTransport(handle),
            diagnose_remaining_once=True,
        )
    assert calls == 3 and path.read_bytes() == before


def test_remaining_manifest_rejects_reordering_and_reserve_outside_fixed_sequence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cost.json"
    path.write_bytes(runner.REMAINING_LEDGER.read_bytes())
    frozen = contract()
    ledger = ExperimentLedger(path, frozen)
    requests = [
        {"query_id": item["query_id"], "request_sha256": "offline-sha"}
        for item in runner.remaining_manifest()["requests"]
    ]
    before = path.read_bytes()
    with pytest.raises(SufficiencyBlocked, match="REMAINING_REQUEST_MANIFEST_MISMATCH"):
        ledger.begin_remaining_diagnostic("reorder-offline", frozen["asset_sha256"], requests[::-1])
    assert path.read_bytes() == before
    ledger.begin_remaining_diagnostic("order-offline", frozen["asset_sha256"], requests)
    with pytest.raises(SufficiencyBlocked, match="REMAINING_REQUEST_ORDER_MISMATCH"):
        ledger.reserve(runner.FIFTH_QUERY_ID, runner.FIFTH_REQUEST_SHA)
    ledger.plan["total_budget_micro_cny"] = 10773 + 3148032 - 1
    with pytest.raises(SufficiencyBlocked, match="BUDGET_INCOMPLETE"):
        ledger.reserve(requests[0]["query_id"], "offline-sha")
    assert len(ledger.state["attempts"]) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["valid", "invalid", "unknown_usage"])
async def test_fifth_diagnostic_is_once_exact_request_and_keeps_original_stopped(
    tmp_path: Path,
    result: str,
) -> None:
    path = tmp_path / "cost.json"
    path.write_bytes(runner.ORIGINAL_LEDGER.read_bytes())
    frozen = contract()
    ledger = ExperimentLedger(path, frozen)
    original = copy.deepcopy(ledger.state)
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert hashlib.sha256(request.content).hexdigest() == runner.FIFTH_REQUEST_SHA
        response = payload(fingerprint=None)
        response["model"] = "deepseek-v4-flash"
        response["output"][0]["content"][0]["text"] = json.dumps(
            {"sufficient": False if result == "valid" else "false", "evidence": []}
        )
        if result == "unknown_usage":
            del response["usage"]
        return httpx.Response(200, json=response)

    report: dict[str, Any] = {"run_id": "diagnostic-offline", "metrics": None}
    if result == "valid":
        await run_development(
            report,
            ledger,
            frozen,
            api_key="offline-only",
            transport=httpx.MockTransport(handle),
            diagnose_fifth_once=True,
        )
        assert report["status"] == "DIAGNOSTIC_COMPLETED"
        assert len(report["rows"]) == 1
    else:
        expected = "USAGE_UNTRUSTED" if result == "unknown_usage" else "INVALID_DECISION_SCHEMA"
        with pytest.raises(SufficiencyBlocked, match=expected):
            await run_development(
                report,
                ledger,
                frozen,
                api_key="offline-only",
                transport=httpx.MockTransport(handle),
                diagnose_fifth_once=True,
            )
        report["status"] = "STOPPED"
        assert report["rows"] == []
    ledger.finish(report["status"])
    assert calls == 1 and report["metrics"] is None
    assert ledger.state["phases"][runner.PHASE] == original["phases"][runner.PHASE]
    assert ledger.state["attempts"][:5] == original["attempts"]
    assert len(ledger.state["attempts"]) == 6
    assert ledger.state["identity"] == original["identity"]
    assert ledger.totals() == {
        "settled_upper_micro_cny": 9084 if result == "unknown_usage" else 9564,
        "unsettled_reserved_micro_cny": 3148032 if result == "unknown_usage" else 0,
    }
    if result == "invalid":
        evidence = ledger.state["attempts"][-1]["observation"]["decision_diagnostic"]
        assert evidence["fields"][0] == {"name": "sufficient", "type": "str"}
    resumed = ExperimentLedger(path, frozen)
    before_retry = path.read_bytes()
    with pytest.raises(SufficiencyBlocked, match="DIAGNOSTIC_ALREADY_STARTED_NO_RETRY"):
        await run_development(
            {"run_id": "new-id-must-not-retry"},
            resumed,
            frozen,
            api_key="offline-only",
            transport=httpx.MockTransport(handle),
            diagnose_fifth_once=True,
        )
    assert calls == 1 and path.read_bytes() == before_retry
    with pytest.raises(SufficiencyBlocked, match=r"ALREADY_STARTED|UNSETTLED_COST"):
        resumed.begin("must-not-resume-development", frozen["asset_sha256"])


@pytest.mark.asyncio
async def test_fifth_diagnostic_rejects_changed_request_before_ledger_write_or_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "cost.json"
    path.write_bytes(runner.ORIGINAL_LEDGER.read_bytes())
    original = path.read_bytes()
    frozen = contract()
    source = development_rows()
    source[4]["text"] += "离线契约故意改字，不是新题或实际提示变更"
    monkeypatch.setattr(runner, "development_rows", lambda: source)

    def no_send(_: httpx.Request) -> httpx.Response:
        raise AssertionError("changed request must not be sent")

    with pytest.raises(SufficiencyBlocked, match="DIAGNOSTIC_REQUEST_MISMATCH"):
        await run_development(
            {"run_id": "mismatch-offline"},
            ExperimentLedger(path, frozen),
            frozen,
            api_key="offline-only",
            transport=httpx.MockTransport(no_send),
            diagnose_fifth_once=True,
        )
    assert path.read_bytes() == original


def test_fifth_diagnostic_rejects_lost_history_and_uses_original_budget(tmp_path: Path) -> None:
    frozen = contract()
    ledger = ExperimentLedger(tmp_path / "cost.json", frozen)
    with pytest.raises(SufficiencyBlocked, match="LEDGER_PRECONDITION_CHANGED"):
        ledger.begin_fifth_diagnostic(
            "no-history",
            frozen["asset_sha256"],
            runner.FIFTH_QUERY_ID,
            runner.FIFTH_REQUEST_SHA,
        )
    ledger.path.write_bytes(runner.ORIGINAL_LEDGER.read_bytes())
    ledger = ExperimentLedger(ledger.path, frozen)
    ledger.begin_fifth_diagnostic(
        "budget-offline",
        frozen["asset_sha256"],
        runner.FIFTH_QUERY_ID,
        runner.FIFTH_REQUEST_SHA,
    )
    ledger.plan["total_budget_micro_cny"] = 9084 + 3148032 - 1
    with pytest.raises(SufficiencyBlocked, match="BUDGET_INCOMPLETE"):
        ledger.reserve(runner.FIFTH_QUERY_ID, runner.FIFTH_REQUEST_SHA)
    assert ledger.totals()["settled_upper_micro_cny"] == 9084
    assert len(ledger.state["attempts"]) == 5


def row(index: int = 0) -> dict[str, Any]:
    return {
        "id": f"contract-{index}",
        "text": "合成装置何时关闭？",
        "topic": "contract-only",
        "kind": "direct" if index % 2 == 0 else "missing",
        "answerable": index % 2 == 0,
        "support": "must-not-leave",
        "reason": "must-not-leave",
        "features": [0.1, 0.2, 0.3, 0.4],
        "recall": 1.0 if index % 2 == 0 else 0.0,
        "reciprocal_rank": 1.0 if index % 2 == 0 else 0.0,
        "fusedCandidates": [
            {
                "chunkId": f"local-{part}",
                "snippet": f"合成片段{part}：装置在日落时关闭。",
                "applicability": ["INTERNAL"],
                "score": 0.9,
            }
            for part in range(1, 6)
        ],
    }


def payload(*, fingerprint: str | None = "test-fingerprint") -> dict[str, Any]:
    return {
        "id": "test-response",
        "object": "response",
        "status": "completed",
        "model": "deepseek-v4-flash-20260831",
        "system_fingerprint": fingerprint,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "sufficient": True,
                                "evidence": [{"chunk": 1, "quote": "日落时关闭"}],
                            }
                        ),
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_tokens_details": {"cached_tokens": 10},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def test_request_preserves_all_legal_text_but_excludes_labels_scores_and_identity() -> None:
    source = row()
    source["fusedCandidates"][0]["snippet"] += "长正文" * 2000
    body = request_body(source, contract())
    sent = json.loads(body["input"])
    assert set(sent) == {"question", "chunks"}
    assert [hit["text"] for hit in sent["chunks"]] == [
        hit["snippet"] for hit in source["fusedCandidates"]
    ]
    assert [hit["chunk"] for hit in sent["chunks"]] == [1, 2, 3, 4, 5]
    assert "must-not-leave" not in json.dumps(body)
    assert not {"tools", "previous_response_id", "max_input_tokens"} & body.keys()
    assert body["reasoning"] == {"effort": "none"}
    assert body["max_output_tokens"] == 256


def test_archive_reader_rejects_unapproved_input_before_parsing(tmp_path: Path) -> None:
    target = tmp_path / ARCHIVE
    target.parent.mkdir(parents=True)
    target.write_text('{"synthetic": false}', encoding="utf-8")
    with pytest.raises(SufficiencyBlocked, match="SYNTHETIC_ARCHIVE_MISMATCH"):
        development_rows(tmp_path)


def test_budget_is_per_request_reservation_not_whole_dataset_worst_case_admission() -> None:
    plan = budget_plan(contract())
    assert plan["per_call_reservation_micro_cny"] == 3_148_032
    assert plan["forecast_micro_cny"] == 4_435_968
    assert plan["total_budget_micro_cny"] == 6_000_000
    assert plan["forecast_is_not_spend_or_input_limit"] is True


def test_ledger_reserves_before_send_and_unknown_usage_survives_restart(tmp_path: Path) -> None:
    frozen = contract()
    path = tmp_path / "cost.json"
    ledger = ExperimentLedger(path, frozen)
    ledger.begin("contract-run", frozen["asset_sha256"])
    entry = ledger.reserve("contract-0", "request-sha")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["attempts"][0]["status"] == "PENDING"
    ledger.settle(entry, {"usage_trusted": False})
    resumed = ExperimentLedger(path, frozen)
    assert resumed.totals()["unsettled_reserved_micro_cny"] == 3_148_032
    with pytest.raises(SufficiencyBlocked, match="UNSETTLED_COST"):
        resumed.begin("another-run-must-not-reset", frozen["asset_sha256"])


def test_ledger_settles_trusted_usage_and_enforces_next_request_budget(tmp_path: Path) -> None:
    frozen = contract()
    ledger = ExperimentLedger(tmp_path / "cost.json", frozen)
    ledger.begin("contract-run", frozen["asset_sha256"])
    entry = ledger.reserve("contract-0", "request-sha")
    observation = response_observation(payload(), 7)
    ledger.settle(entry, observation)
    assert ledger.totals() == {
        "settled_upper_micro_cny": 480,
        "unsettled_reserved_micro_cny": 0,
    }
    # 历史已花费用也计入下一请求判断;不是每个RunId获得新的6元。
    ledger.state["prior_paid_micro_cny"] = 2_851_969
    with pytest.raises(SufficiencyBlocked, match="BUDGET_INCOMPLETE"):
        ledger.reserve("contract-1", "next-request-sha")
    assert len(ledger.state["attempts"]) == 1


def test_invalid_citation_and_identity_drift_are_errors_not_abstentions() -> None:
    response = payload()
    expected = ("deepseek-v4-flash-20260831", "another-fingerprint")
    with pytest.raises(SufficiencyBlocked, match="PROVIDER_IDENTITY_DRIFT") as error:
        parse_response(response, row(), expected_identity=expected, duration_ms=2)
    assert error.value.observation["usage_trusted"] is True
    response["output"][0]["content"][0]["text"] = json.dumps(
        {
            "sufficient": True,
            "evidence": [{"chunk": 1, "quote": "未在原文中出现"}],
        }
    )
    with pytest.raises(SufficiencyBlocked, match="INVALID_EVIDENCE"):
        parse_response(response, row(), expected_identity=None, duration_ms=2)
    with pytest.raises(SufficiencyBlocked, match="INCOMPLETE_REPLAY"):
        replay_metrics([row()], [False])


@pytest.mark.asyncio
async def test_invalid_decision_is_preserved_redacted_settled_and_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "development_rows", lambda: [row(i) for i in range(72)])
    calls = 0
    secret = "offline-secret-must-not-leak"
    invalid = json.dumps({"sufficient": "false", "evidence": [], "extra": secret})

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        response = payload()
        response["output"][0]["content"][0]["text"] = invalid
        return httpx.Response(200, json=response)

    frozen = contract()
    path = tmp_path / "cost.json"
    ledger = ExperimentLedger(path, frozen)
    report: dict[str, Any] = {"run_id": "invalid-decision-test", "metrics": None}
    with pytest.raises(SufficiencyBlocked, match="INVALID_DECISION_SCHEMA"):
        await run_development(
            report, ledger, frozen, api_key=secret, transport=httpx.MockTransport(handle)
        )
    persisted = json.loads(path.read_text(encoding="utf-8"))
    observation = persisted["attempts"][0]["observation"]
    diagnostic = observation["decision_diagnostic"]
    assert diagnostic["output_text"] == invalid.replace(secret, "[REDACTED]")
    assert diagnostic["truncated"] is False
    assert diagnostic["top_level_type"] == "dict"
    assert diagnostic["fields"] == [
        {"name": "sufficient", "type": "str"},
        {"name": "evidence", "type": "list"},
        {"name": "extra", "type": "str"},
    ]
    assert observation["failure"] == "INVALID_DECISION_SCHEMA"
    assert secret not in json.dumps([report, persisted])
    assert calls == 1
    assert report["rows"] == [] and report["metrics"] is None
    assert ledger.totals() == {
        "settled_upper_micro_cny": 480,
        "unsettled_reserved_micro_cny": 0,
    }


@pytest.mark.asyncio
async def test_invalid_json_diagnostic_is_bounded_without_changing_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "development_rows", lambda: [row(i) for i in range(72)])
    secret = "offline-secret-crossing-cutoff"
    invalid = "x" * 4090 + secret + "y" * 100
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        response = payload()
        response["output"][0]["content"][0]["text"] = invalid
        return httpx.Response(200, json=response)

    frozen = contract()
    ledger = ExperimentLedger(tmp_path / "cost.json", frozen)
    report: dict[str, Any] = {"run_id": "bounded-invalid-json", "metrics": None}
    with pytest.raises(SufficiencyBlocked, match="INVALID_DECISION_JSON"):
        await run_development(
            report, ledger, frozen, api_key=secret, transport=httpx.MockTransport(handle)
        )
    diagnostic = ledger.state["attempts"][0]["observation"]["decision_diagnostic"]
    sanitized = "x" * 4090 + "[REDACTED]" + "y" * 100
    assert len(diagnostic["output_text"]) == 4096
    assert diagnostic["output_text"].endswith("[REDAC")
    assert diagnostic["truncated"] is True
    assert diagnostic["sanitized_char_count"] == 4200
    assert diagnostic["sanitized_text_sha256"] == hashlib.sha256(sanitized.encode()).hexdigest()
    assert diagnostic["json_valid"] is False
    assert diagnostic["top_level_type"] is None
    assert "offline-secret" not in json.dumps([report, ledger.state])
    assert calls == 1 and report["metrics"] is None
    assert ledger.totals()["unsettled_reserved_micro_cny"] == 0


@pytest.mark.asyncio
async def test_balance_failure_sends_once_keeps_reserve_and_no_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "development_rows", lambda: [row(i) for i in range(72)])
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(402, json={"error": "test-secret-must-not-leak"})

    frozen = contract()
    ledger = ExperimentLedger(tmp_path / "cost.json", frozen)
    report: dict[str, Any] = {"run_id": "balance-test", "metrics": None}
    with pytest.raises(SufficiencyBlocked, match="INSUFFICIENT_BALANCE"):
        await run_development(
            report,
            ledger,
            frozen,
            api_key="test-secret-must-not-leak",
            transport=httpx.MockTransport(handle),
        )
    assert calls == 1
    assert report["metrics"] is None
    assert ledger.totals()["unsettled_reserved_micro_cny"] == 3_148_032
    assert "test-secret-must-not-leak" not in json.dumps([report, ledger.state])


@pytest.mark.asyncio
async def test_provider_drift_stops_second_call_but_settles_valid_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "development_rows", lambda: [row(i) for i in range(72)])
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=payload(fingerprint=f"backend-{calls}"))

    frozen = contract()
    ledger = ExperimentLedger(tmp_path / "cost.json", frozen)
    report: dict[str, Any] = {"run_id": "drift-test", "metrics": None}
    with pytest.raises(SufficiencyBlocked, match="PROVIDER_IDENTITY_DRIFT"):
        await run_development(
            report,
            ledger,
            frozen,
            api_key="offline-test-only",
            transport=httpx.MockTransport(handle),
        )
    assert calls == 2
    assert len(report["rows"]) == 1
    assert ledger.totals() == {
        "settled_upper_micro_cny": 960,
        "unsettled_reserved_micro_cny": 0,
    }
    with pytest.raises(SufficiencyBlocked, match="ALREADY_STARTED"):
        ledger.begin("retry-forbidden", frozen["asset_sha256"])


@pytest.mark.asyncio
async def test_timeout_keeps_unknown_charge_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "development_rows", lambda: [row(i) for i in range(72)])
    calls = 0

    async def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(1)
        raise AssertionError("timeout must cancel offline handler")

    frozen = contract()
    frozen["config"]["call_deadline_seconds"] = 0.001
    ledger = ExperimentLedger(tmp_path / "cost.json", frozen)
    report: dict[str, Any] = {"run_id": "timeout-test"}
    with pytest.raises(SufficiencyBlocked, match="TIMEOUT_OR_TRANSPORT_ERROR"):
        await run_development(
            report,
            ledger,
            frozen,
            api_key="offline-test-only",
            transport=httpx.MockTransport(handle),
        )
    assert calls == 1
    assert ledger.totals()["unsettled_reserved_micro_cny"] == 3_148_032


@pytest.mark.asyncio
async def test_complete_mock_replay_preserves_order_and_reports_quality_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "development_rows", lambda: [row(i) for i in range(72)])
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=payload())

    frozen = contract()
    ledger = ExperimentLedger(tmp_path / "cost.json", frozen)
    report: dict[str, Any] = {"run_id": "complete-offline-test"}
    await run_development(
        report, ledger, frozen, api_key="offline-test-only", transport=httpx.MockTransport(handle)
    )
    assert calls == 72
    assert report["status"] == "FAIL"  # mock接受全部,必须真实记无答案拒答失败
    assert report["metrics"]["unanswered_recall"] == 0
    assert report["rows"][0]["accepted_chunk_ids"] == [f"local-{i}" for i in range(1, 6)]
