"""C-v2离线实验接缝;合成HTTP响应不代表真实模型或质量通过。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_knowledge_sufficiency import payload, row

import baseline_agent.knowledge_sufficiency_run as runner
from baseline_agent.knowledge_sufficiency import (
    SufficiencyBlocked,
    contract,
    development_rows,
    parse_response,
    request_body,
    sha256,
)


def test_v2_allows_multiple_quotes_without_rewriting_v1_or_response() -> None:
    response = payload()
    decision = {
        "sufficient": True,
        "evidence": [{"chunk": 1, "quote": "合成片段1"}, {"chunk": 1, "quote": "日落时关闭"}],
    }
    response["output"][0]["content"][0]["text"] = json.dumps(decision)
    with pytest.raises(SufficiencyBlocked, match="INVALID_EVIDENCE"):
        parse_response(response, row(), expected_identity=None, duration_ms=1)
    result = parse_response(response, row(), expected_identity=None, duration_ms=1, c_v2=True)
    assert result["decision"] == decision
    old, new = contract(), contract(c_v2=True)
    assert old["schema"] == new["schema"]
    assert "每个编号只出现一次" in old["prompt"]
    assert "重复编号不代表多个独立来源" in new["prompt"]
    old_request, new_request = request_body(row(), old), request_body(row(), new)
    assert new_request["text"]["format"]["name"] == "knowledge_sufficiency_c_v2"
    for key in old_request.keys() - {"instructions", "text"}:
        assert old_request[key] == new_request[key]


@pytest.mark.parametrize(
    "evidence",
    [
        [{"chunk": 6, "quote": "日落时关闭"}],
        [{"chunk": 1, "quote": "虚构内容"}],
        [{"chunk": True, "quote": "日落时关闭"}],
        [{"chunk": 1, "quote": "日落时关闭"}] * 6,
    ],
)
def test_v2_still_rejects_invalid_evidence(evidence: list[dict[str, Any]]) -> None:
    response = payload()
    response["output"][0]["content"][0]["text"] = json.dumps(
        {"sufficient": True, "evidence": evidence}
    )
    with pytest.raises(SufficiencyBlocked, match="INVALID_EVIDENCE"):
        parse_response(response, row(), expected_identity=None, duration_ms=1, c_v2=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "invalid", "unknown_usage", "supplier", "drift"])
async def test_v2_whole_replay_is_once_and_preserves_original_ledger(
    tmp_path: Path, failure: str | None
) -> None:
    path = tmp_path / "ledger.json"
    path.write_bytes(runner.V2_LEDGER.read_bytes())
    frozen = contract(c_v2=True)
    ledger = runner.ExperimentLedger(path, frozen)
    original = copy.deepcopy(ledger.state)
    source = development_rows()
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        position = calls
        calls += 1
        entry = json.loads(path.read_text(encoding="utf-8"))["attempts"][-1]
        assert entry["status"] == "PENDING"
        assert entry["query_id"] == source[position]["id"]
        assert entry["request_sha256"] == sha256(request.content)
        response = payload(fingerprint=None)
        response["model"] = "deepseek-v4-flash"
        snippet = source[position]["fusedCandidates"][0]["snippet"]
        response["output"][0]["content"][0]["text"] = json.dumps(
            {
                "sufficient": True,
                "evidence": [
                    {"chunk": 1, "quote": snippet[:2]},
                    {"chunk": 1, "quote": snippet[2:4]},
                ],
            }
        )
        if calls == 2:
            if failure == "invalid":
                response["output"][0]["content"][0]["text"] = '{"sufficient":"false","evidence":[]}'
            elif failure == "unknown_usage":
                del response["usage"]
            elif failure == "supplier":
                return httpx.Response(402)
            elif failure == "drift":
                response["system_fingerprint"] = "changed-offline"
        return httpx.Response(200, json=response)

    report: dict[str, Any] = {"run_id": "c-v2-offline", "metrics": None}
    arguments: dict[str, Any] = dict(
        api_key="offline-only", transport=httpx.MockTransport(handle), c_v2_whole_once=True
    )
    if failure:
        with pytest.raises(SufficiencyBlocked):
            await runner.run_development(report, ledger, frozen, **arguments)
        ledger.finish("STOPPED")
        assert calls == 2 and len(report["rows"]) == 1 and report["metrics"] is None
        pending = failure in {"unknown_usage", "supplier"}
        assert ledger.totals() == {
            "settled_upper_micro_cny": 80403 if pending else 80883,
            "unsettled_reserved_micro_cny": 3148032 if pending else 0,
        }
        if failure == "invalid":
            assert "decision_diagnostic" in ledger.state["attempts"][-1]["observation"]
    else:
        await runner.run_development(report, ledger, frozen, **arguments)
        ledger.finish(report["status"])
        assert calls == 72
        assert report["contract_validation"] == "PASS_72_OF_72"
        assert report["semantic_validation"] == report["status"] == "FAIL"
        assert report["metrics"]["unanswered_recall"] == 0
        assert sum(report["confusion_counts"].values()) == 72
        assert ledger.totals() == {
            "settled_upper_micro_cny": 114483,
            "unsettled_reserved_micro_cny": 0,
        }
    assert report["rows"][0]["evidence_item_count"] == 2
    assert report["rows"][0]["distinct_cited_article_count"] == 1
    assert len(report["rows"][0]["decision"]["evidence"]) == 2
    assert ledger.state["attempts"][:50] == original["attempts"]
    for phase, record in original["phases"].items():
        assert ledger.state["phases"][phase] == record
    before = path.read_bytes()
    with pytest.raises(SufficiencyBlocked, match="V2_ALREADY_STARTED_NO_RETRY"):
        await runner.run_development(
            {"run_id": "new-id-not-retry"},
            runner.ExperimentLedger(path, frozen),
            frozen,
            **arguments,
        )
    assert path.read_bytes() == before


def test_v2_request_order_history_and_shared_budget_are_hard_boundaries(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    path.write_bytes(runner.V2_LEDGER.read_bytes())
    frozen = contract(c_v2=True)
    ledger = runner.ExperimentLedger(path, frozen)
    requests = json.loads(runner.V2_REQUESTS.read_bytes())["requests"]
    before = path.read_bytes()
    with pytest.raises(SufficiencyBlocked, match="V2_REQUEST_MANIFEST_MISMATCH"):
        ledger.begin_v2("reorder", frozen["asset_sha256"], requests[::-1])
    assert path.read_bytes() == before
    ledger.begin_v2("budget", frozen["asset_sha256"], requests)
    with pytest.raises(SufficiencyBlocked, match="REQUEST_ORDER_MISMATCH"):
        ledger.reserve(requests[1]["query_id"], requests[1]["request_sha256"])
    ledger.plan["total_budget_micro_cny"] = 79923 + 3148032 - 1
    with pytest.raises(SufficiencyBlocked, match="BUDGET_INCOMPLETE"):
        ledger.reserve(requests[0]["query_id"], requests[0]["request_sha256"])
    assert len(ledger.state["attempts"]) == 50
    empty = runner.ExperimentLedger(tmp_path / "empty.json", frozen)
    with pytest.raises(SufficiencyBlocked, match="V2_LEDGER_PRECONDITION_CHANGED"):
        empty.begin_v2("lost-history", frozen["asset_sha256"], requests)
