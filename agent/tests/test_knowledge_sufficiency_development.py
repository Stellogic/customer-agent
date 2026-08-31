"""版本化开发沿用完整分区和共享账本;Mock不代表模型质量。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_knowledge_sufficiency import payload

from baseline_agent.knowledge_sufficiency import SufficiencyBlocked, contract, sha256
from baseline_agent.knowledge_sufficiency_run import (
    DEVELOPMENT_ANCHOR,
    ExperimentLedger,
    run_development,
)


@pytest.mark.asyncio
async def test_development_version_preserves_history_and_counts_one_whole_run(tmp_path: Path) -> None:
    path = tmp_path / "cost.json"
    path.write_bytes(DEVELOPMENT_ANCHOR.read_bytes())
    frozen = contract(development_version="c3")
    ledger = ExperimentLedger(path, frozen)
    original = copy.deepcopy(ledger.state)
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        stored = json.loads(path.read_text(encoding="utf-8"))
        entry = stored["attempts"][-1]
        assert entry["status"] == "PENDING"
        assert entry["request_sha256"] == sha256(request.content)
        response = payload(fingerprint=None)
        response["model"] = "deepseek-v4-flash"
        response["output"][0]["content"][0]["text"] = '{"sufficient":false,"evidence":[]}'
        return httpx.Response(200, json=response)

    report: dict[str, Any] = {"run_id": "development-offline", "metrics": None}
    await run_development(report, ledger, frozen, api_key="offline-only",
                          development_version="c3", transport=httpx.MockTransport(handle))
    ledger.finish(report["status"])
    assert calls == len(report["rows"]) == 72
    assert report["contract_validation"] == "PASS_72_OF_72"
    assert report["status"] == "FAIL"
    assert ledger.totals() == {"settled_upper_micro_cny": 230139, "unsettled_reserved_micro_cny": 0}
    assert ledger.state["attempts"][:122] == original["attempts"]
    assert all(ledger.state["phases"][key] == value for key, value in original["phases"].items())
    with pytest.raises(SufficiencyBlocked, match="VERSION_ALREADY_RUN"):
        ledger.begin_version("c3", "new-run-id", frozen["asset_sha256"], report["request_manifest"])


def test_development_version_keeps_budget_and_old_history(tmp_path: Path) -> None:
    frozen = contract(development_version="c3")
    empty = ExperimentLedger(tmp_path / "empty.json", frozen)
    with pytest.raises(SufficiencyBlocked, match="DEVELOPMENT_HISTORY_CHANGED"):
        empty.begin_version("c3", "missing-history", frozen["asset_sha256"], [])
    path = tmp_path / "cost.json"
    path.write_bytes(DEVELOPMENT_ANCHOR.read_bytes())
    ledger = ExperimentLedger(path, frozen)
    ledger.begin_version("c3", "budget", frozen["asset_sha256"], [{"query_id":"one", "request_sha256":"hash"}])
    ledger.plan["total_budget_micro_cny"] = 195579 + 3148032 - 1
    with pytest.raises(SufficiencyBlocked, match="BUDGET_INCOMPLETE"):
        ledger.reserve("one", "hash")
    assert len(ledger.state["attempts"]) == 122
