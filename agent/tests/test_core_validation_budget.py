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
    assert known["supplierChargeMicros"] is None
    assert overrun["status"] == "PENDING"
    assert overrun["estimatedCostMicros"] == 9_090
    assert overrun["supplierChargeMicros"] is None
    with pytest.raises(CoreBudgetStopped):
        budget.reserve("after-overrun", role="action", request=request)
