"""C接缝离线契约测试源码。MockTransport不是模型质量证据,不得作为真实回退。"""

from __future__ import annotations

import asyncio
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
        "output": [{
            "type": "message", "role": "assistant", "status": "completed",
            "content": [{
                "type": "output_text",
                "text": json.dumps({
                    "sufficient": True,
                    "evidence": [{"chunk": 1, "quote": "日落时关闭"}],
                }),
            }],
        }],
        "usage": {
            "input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
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
    response["output"][0]["content"][0]["text"] = json.dumps({
        "sufficient": True, "evidence": [{"chunk": 1, "quote": "未在原文中出现"}],
    })
    with pytest.raises(SufficiencyBlocked, match="INVALID_EVIDENCE"):
        parse_response(response, row(), expected_identity=None, duration_ms=2)
    with pytest.raises(SufficiencyBlocked, match="INCOMPLETE_REPLAY"):
        replay_metrics([row()], [False])


@pytest.mark.asyncio
async def test_balance_failure_sends_once_keeps_reserve_and_no_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
            report, ledger, frozen, api_key="test-secret-must-not-leak",
            transport=httpx.MockTransport(handle),
        )
    assert calls == 1
    assert report["metrics"] is None
    assert ledger.totals()["unsettled_reserved_micro_cny"] == 3_148_032
    assert "test-secret-must-not-leak" not in json.dumps([report, ledger.state])


@pytest.mark.asyncio
async def test_provider_drift_stops_second_call_but_settles_valid_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
            report, ledger, frozen, api_key="offline-test-only", transport=httpx.MockTransport(handle)
        )
    assert calls == 2
    assert len(report["rows"]) == 1
    assert ledger.totals() == {
        "settled_upper_micro_cny": 960, "unsettled_reserved_micro_cny": 0,
    }
    with pytest.raises(SufficiencyBlocked, match="ALREADY_STARTED"):
        ledger.begin("retry-forbidden", frozen["asset_sha256"])


@pytest.mark.asyncio
async def test_timeout_keeps_unknown_charge_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
            report, ledger, frozen, api_key="offline-test-only", transport=httpx.MockTransport(handle)
        )
    assert calls == 1
    assert ledger.totals()["unsettled_reserved_micro_cny"] == 3_148_032


@pytest.mark.asyncio
async def test_complete_mock_replay_preserves_order_and_reports_quality_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
