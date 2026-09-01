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


def test_provider_transport_propagates_container_https_proxy(runner, monkeypatch):
    captured = {}

    class FakeTransport:
        pass

    def build_transport(**kwargs):
        captured.update(kwargs)
        return FakeTransport()

    monkeypatch.setattr(runner.httpx, "AsyncHTTPTransport", build_transport)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:8080")

    assert isinstance(runner.provider_transport(), FakeTransport)
    assert captured == {"proxy": "http://proxy.example.test:8080", "retries": 0}


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


@pytest.mark.asyncio
async def test_user_released_connection_timeout_preserves_history_and_allows_next_request(
    runner, tmp_path
):
    path = ledger_file(tmp_path, 620805)
    state = json.loads(path.read_text())
    state["attempts"].append(
        {
            "phase": "timed-out-run",
            "query_id": "delivery-01-a",
            "request_sha256": "request-hash",
            "status": "TIMEOUT_RELEASED",
            "reserved_micro_cny": 3159552,
            "observation": {
                "failure_classification": "CONNECTION_TIMEOUT",
                "usage_reported": False,
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            },
            "release": {
                "authority": "USER",
                "reason": "CONNECTION_TIMEOUT_NO_USAGE",
                "supplier_nonbilling_confirmed": False,
                "authorized_retry_run": "retry-run",
            },
        }
    )
    path.write_text(json.dumps(state), encoding="utf-8")

    wrong_run_path = tmp_path / "wrong-run-ledger.json"
    wrong_run_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(runner.BudgetStop, match="最新超时释放未授权本次运行"):
        runner.BudgetTransport(wrong_run_path, "another-run")

    conflicting_usage_path = tmp_path / "conflicting-usage-ledger.json"
    conflicting_state = json.loads(json.dumps(state))
    conflicting_state["attempts"][0]["observation"]["usage_reported"] = True
    conflicting_state["attempts"][0]["observation"]["input_tokens"] = 1
    conflicting_usage_path.write_text(json.dumps(conflicting_state), encoding="utf-8")
    with pytest.raises(runner.BudgetStop, match="存在未结算预留"):
        runner.BudgetTransport(conflicting_usage_path, "retry-run")

    budget = runner.BudgetTransport(path, "retry-run")

    await budget.inner.aclose()
    budget.inner = httpx.MockTransport(lambda request: httpx.Response(200, request=request))
    budget.query_id = "delivery-01-a"
    request = httpx.Request(
        "POST",
        "https://provider-test",
        json={"model": "deepseek-v4-flash", "max_output_tokens": 1536},
    )
    await budget.handle_async_request(request)

    saved = json.loads(path.read_text())
    assert saved["attempts"][0] == state["attempts"][0]
    assert saved["attempts"][1]["status"] == "PENDING"


def test_latest_release_authorizes_retry_without_reopening_older_release(runner, tmp_path):
    path = ledger_file(tmp_path, 620805)
    state = json.loads(path.read_text())
    released = {
        "query_id": "delivery-01-a",
        "request_sha256": "request-hash",
        "status": "TIMEOUT_RELEASED",
        "reserved_micro_cny": 3159552,
        "observation": {
            "failure_classification": "CONNECTION_TIMEOUT",
            "usage_reported": False,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        },
        "release": {
            "authority": "USER",
            "reason": "CONNECTION_TIMEOUT_NO_USAGE",
            "supplier_nonbilling_confirmed": False,
        },
    }
    first = json.loads(json.dumps(released))
    first.update(phase="first-timeout")
    first["release"]["authorized_retry_run"] = "second-timeout"
    latest = json.loads(json.dumps(released))
    latest.update(phase="second-timeout")
    latest["release"]["authorized_retry_run"] = "fixed-retry"
    state["attempts"] = [first, latest]
    path.write_text(json.dumps(state), encoding="utf-8")

    runner.BudgetTransport(path, "fixed-retry")

    wrong_path = tmp_path / "wrong-latest-release.json"
    state["phases"] = {}
    wrong_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(runner.BudgetStop, match="最新超时释放未授权本次运行"):
        runner.BudgetTransport(wrong_path, "unapproved-retry")


def test_final_pending_total_excludes_valid_timeout_release(runner):
    released = {
        "status": "TIMEOUT_RELEASED",
        "reserved_micro_cny": 3159552,
        "observation": {
            "failure_classification": "CONNECTION_TIMEOUT",
            "usage_reported": False,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        },
        "release": {
            "authority": "USER",
            "reason": "CONNECTION_TIMEOUT_NO_USAGE",
            "supplier_nonbilling_confirmed": False,
            "authorized_retry_run": "fixed-retry",
        },
    }
    pending = {"status": "PENDING", "reserved_micro_cny": 42}

    assert runner.pending_micro_cny([released, pending]) == 42
