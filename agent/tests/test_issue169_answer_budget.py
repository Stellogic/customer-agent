"""调用前预算边界测试,所有响应仅为测试fixture,不作为回答质量。"""

import importlib
import json
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring-test")
    monkeypatch.setenv("SPRING_DATABASE_URI", "postgresql://test")
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    return importlib.import_module("issue169_customer_answer_run")


def ledger_file(tmp_path, spent):
    path = tmp_path / "ledger.json"
    path.write_text(
        json.dumps(
            {
                "schema": "issue190-sufficiency-cost-v1",
                "prior_paid_micro_cny": spent,
                "phases": {},
                "attempts": [],
                "identity": ["deepseek-v4-flash", None],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_budget_blocks_before_transport_when_remaining_cannot_reserve_full_call(
    runner, tmp_path
):
    path = ledger_file(tmp_path, 3_000_000)
    budget = runner.BudgetTransport(path, "test-budget-bound")

    def forbidden(_):
        raise AssertionError("request must not reach provider")

    await budget.inner.aclose()
    budget.inner = httpx.MockTransport(forbidden)
    request = httpx.Request(
        "POST",
        "https://provider-test",
        json={"model": "deepseek-v4-flash", "max_output_tokens": 1536},
    )
    with pytest.raises(runner.BudgetStop, match="BUDGET_INCOMPLETE"):
        await budget.handle_async_request(request)
    assert json.loads(path.read_text())["attempts"] == []


@pytest.mark.asyncio
async def test_unknown_usage_retains_reservation_and_blocks_next_request(runner, tmp_path):
    path = ledger_file(tmp_path, 620805)
    budget = runner.BudgetTransport(path, "test-unknown-usage")
    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(503, request=request)

    await budget.inner.aclose()
    budget.inner = httpx.MockTransport(response)
    request = httpx.Request(
        "POST",
        "https://provider-test",
        json={"model": "deepseek-v4-flash", "max_output_tokens": 1536},
    )
    await budget.handle_async_request(request)
    with pytest.raises(runner.BudgetStop, match="未知usage"):
        await budget.handle_async_request(request)
    saved = json.loads(path.read_text())
    assert len(calls) == 1
    assert saved["prior_paid_micro_cny"] == 620805
    assert saved["attempts"][0]["reserved_micro_cny"] == 3159552
    assert saved["attempts"][0]["status"] == "PENDING"
