import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from baseline_agent.core_validation_budget import CoreBudgetStopped, CoreValidationBudget


def test_concurrent_requests_share_reservation_and_unknown_usage_survives_reopening(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "core-validation-budget.json"
    budget = CoreValidationBudget.create(
        ledger_path,
        authorization_id="synthetic-core-budget",
        limit_micros=6_000,
        max_attempts=10,
        max_tokens=20_000,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
    )
    request = {
        "model": "deepseek-v4-flash",
        "input": "synthetic support question",
        "max_output_tokens": 128,
    }
    ready = Barrier(2)

    def start_attempt(attempt_id: str) -> str | None:
        ready.wait(timeout=5)
        try:
            budget.reserve(attempt_id, role="intake", request=request)
            return attempt_id
        except CoreBudgetStopped:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        admitted = list(workers.map(start_attempt, ["attempt-a", "attempt-b"]))
    accepted = [attempt for attempt in admitted if attempt is not None]
    assert len(accepted) == 1

    budget.settle(accepted[0], input_tokens=None, output_tokens=None)
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert saved["currency"] == "CNY"
    assert len(saved["entries"]) == 1
    pending = saved["entries"][0]
    assert pending["status"] == "PENDING"
    assert 0 < pending["reservedMicros"] <= 6_000
    assert pending["estimatedCostMicros"] is None
    assert pending["supplierChargeMicros"] is None
    assert "synthetic support question" not in ledger_path.read_text(encoding="utf-8")

    reopened = CoreValidationBudget.open(ledger_path, authorization_id="synthetic-core-budget")
    with pytest.raises(CoreBudgetStopped):
        reopened.reserve("attempt-after-restart", role="communication", request=request)
    assert json.loads(ledger_path.read_text(encoding="utf-8")) == saved


def test_known_usage_releases_reservation_but_overrun_stops_further_requests(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "core-validation-budget.json"
    budget = CoreValidationBudget.create(
        ledger_path,
        authorization_id="synthetic-core-budget",
        limit_micros=6_000,
        max_attempts=10,
        max_tokens=20_000,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
    )
    request = {
        "model": "deepseek-v4-flash",
        "input": "synthetic support question",
        "max_output_tokens": 128,
    }
    budget.reserve("known-attempt", role="intake", request=request)
    budget.settle("known-attempt", input_tokens=100, output_tokens=10)
    # 两次完整预留不能同时容纳;已知实际 usage 使下一次请求有足够余量。
    budget.reserve("overrun-attempt", role="communication", request=request)
    with pytest.raises(CoreBudgetStopped):
        budget.settle("overrun-attempt", input_tokens=3_000, output_tokens=10)

    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    known, overrun = saved["entries"]
    assert known["status"] == "SETTLED"
    assert known["estimatedCostMicros"] == 390
    assert known["model"] == "deepseek-v4-flash"
    assert known["price"] == {"inputMicrosPerToken": 3, "outputMicrosPerToken": 9}
    assert known["supplierChargeMicros"] is None
    assert overrun["status"] == "PENDING"
    assert overrun["estimatedCostMicros"] == 9_090
    assert overrun["supplierChargeMicros"] is None
    with pytest.raises(CoreBudgetStopped):
        budget.reserve("after-overrun", role="action", request=request)


def test_stop_survives_reopening_and_allows_inflight_usage_to_settle(tmp_path: Path) -> None:
    budget = CoreValidationBudget.create(
        tmp_path / "budget.json",
        authorization_id="synthetic-stop",
        limit_micros=3_000_000,
        max_attempts=10,
        max_tokens=1_000_000,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
    )
    request = {"model": "deepseek-v4-flash", "input": "synthetic", "max_output_tokens": 128}
    budget.reserve("inflight", role="action", request=request)
    budget.stop("FIRST_CASE_FAILED")
    reopened = CoreValidationBudget.open(budget.path, authorization_id="synthetic-stop")
    with pytest.raises(CoreBudgetStopped, match="CORE_BUDGET_STOPPED"):
        reopened.reserve("after-stop", role="action", request=request)
    reopened.settle("inflight", input_tokens=100, output_tokens=10)
    reopened.stop("LATER_FAILURE")
    saved = json.loads(budget.path.read_text(encoding="utf-8"))
    assert saved["stopReason"] == "FIRST_CASE_FAILED"
    assert len(saved["entries"]) == 1
    assert saved["entries"][0]["status"] == "SETTLED"
    assert saved["entries"][0]["estimatedCostMicros"] == 390


def test_pro_communication_uses_its_frozen_price_and_rejects_pro_action(tmp_path: Path) -> None:
    budget = CoreValidationBudget.create(
        tmp_path / "budget.json",
        authorization_id="synthetic-pro",
        limit_micros=3_000_000,
        max_attempts=10,
        max_tokens=100_000,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        communication_model="deepseek-v4-pro",
    )
    request = {"model": "deepseek-v4-pro", "input": "synthetic", "max_output_tokens": 128}
    with pytest.raises(CoreBudgetStopped, match="CORE_BUDGET_REQUEST_MISMATCH"):
        budget.reserve("pro-action", role="action", request=request)
    budget.reserve("pro-reply", role="communication", request=request)
    saved = json.loads(budget.path.read_text(encoding="utf-8"))
    assert saved["communicationModel"] == "deepseek-v4-pro"
    entry = saved["entries"][0]
    assert entry["model"] == "deepseek-v4-pro"
    assert entry["price"] == {"inputMicrosPerToken": 9, "outputMicrosPerToken": 27}
    assert entry["reservedMicros"] == (
        entry["reservedInputTokens"] * 9 + entry["reservedOutputTokens"] * 27
    )
    reopened = CoreValidationBudget.open(budget.path, authorization_id="synthetic-pro")
    reopened.settle("pro-reply", input_tokens=100, output_tokens=10)
    reopened.reserve(
        "flash-action", role="action", request={**request, "model": "deepseek-v4-flash"}
    )
    reopened.settle("flash-action", input_tokens=100, output_tokens=10)
    saved = json.loads(budget.path.read_text(encoding="utf-8"))
    assert [entry["estimatedCostMicros"] for entry in saved["entries"]] == [1170, 390]


def test_legacy_flash_ledger_settles_and_reopens_without_reinitializing(tmp_path: Path) -> None:
    budget = CoreValidationBudget.create(
        tmp_path / "budget.json",
        authorization_id="synthetic-legacy",
        limit_micros=3_000_000,
        max_attempts=10,
        max_tokens=100_000,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
    )
    request = {"model": "deepseek-v4-flash", "input": "synthetic", "max_output_tokens": 128}
    budget.reserve("old-inflight", role="communication", request=request)
    saved = json.loads(budget.path.read_text(encoding="utf-8"))
    del saved["communicationModel"], saved["pricesByModel"]
    del saved["entries"][0]["model"], saved["entries"][0]["price"]
    budget.path.write_text(json.dumps(saved), encoding="utf-8")

    reopened = CoreValidationBudget.open(budget.path, authorization_id="synthetic-legacy")
    assert json.loads(budget.path.read_text(encoding="utf-8")) == saved
    reopened.settle("old-inflight", input_tokens=100, output_tokens=10)
    with pytest.raises(CoreBudgetStopped, match="CORE_BUDGET_REQUEST_MISMATCH"):
        reopened.reserve(
            "unauthorized-pro",
            role="communication",
            request={**request, "model": "deepseek-v4-pro"},
        )
    reopened.reserve("new-flash", role="communication", request=request)
    saved = json.loads(budget.path.read_text(encoding="utf-8"))
    assert saved["entries"][0]["estimatedCostMicros"] == 390
    assert saved["entries"][1]["model"] == "deepseek-v4-flash"
