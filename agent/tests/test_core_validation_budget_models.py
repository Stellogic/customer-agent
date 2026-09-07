import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from test_deepseek_customer_communication_model import _completed, _streamed
from test_deepseek_customer_communication_model import _input as communication_input
from test_deepseek_intake_model import _clarifying_intake_input, _completed_intake_response
from test_deepseek_investigation_action_model import _completed_action
from test_deepseek_investigation_model import MODEL_INPUT, _response

from baseline_agent.core_validation_budget import CoreBudgetStopped, CoreValidationBudget
from baseline_agent.deepseek_customer_communication_model import (
    DeepSeekCustomerCommunicationConfig,
    DeepSeekResponsesCustomerCommunicationModel,
)
from baseline_agent.deepseek_intake_model import DeepSeekIntakeModel
from baseline_agent.deepseek_investigation_action_model import (
    DeepSeekActionConfig,
    DeepSeekResponsesInvestigationActionModel,
)
from baseline_agent.deepseek_investigation_model import (
    DeepSeekResponsesConfig,
    DeepSeekResponsesInvestigationModel,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["intake", "action", "judgment", "communication"])
async def test_each_model_role_stops_before_http_when_shared_budget_cannot_reserve(
    tmp_path: Path, role: str
) -> None:
    budget = CoreValidationBudget.create(
        tmp_path / "budget.json",
        authorization_id="synthetic-four-role-budget",
        limit_micros=1,
        max_attempts=10,
        max_tokens=100_000,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
    )
    requests: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503)

    transport = httpx.MockTransport(provider)
    with pytest.raises(CoreBudgetStopped):
        await _invoke_model(role, transport, budget)
    assert requests == []


async def _invoke_model(
    role: str, transport: httpx.MockTransport, budget: CoreValidationBudget
) -> None:
    if role == "intake":
        result = await DeepSeekIntakeModel(
            "synthetic-test-key", transport=transport, budget=budget
        ).understand(_clarifying_intake_input())
        assert result.status == "READY_TO_CONFIRM"
        assert [issue.kind for issue in result.issues] == ["DUPLICATE_CHARGE"]
    elif role == "action":
        decision = await DeepSeekResponsesInvestigationActionModel(
            DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
            transport=transport,
            budget=budget,
        ).choose({})
        assert decision.action.kind.value == "CONFIRM_ORDER"
    elif role == "judgment":
        judgment = await DeepSeekResponsesInvestigationModel(
            DeepSeekResponsesConfig(api_key="synthetic-test-key", max_attempts=1),
            transport=transport,
            budget=budget,
        ).judge(MODEL_INPUT)
        assert judgment.compensation_review_required is True
        assert judgment.reason_code.value == "LOGISTICS_DELAY"
    else:
        reply = await DeepSeekResponsesCustomerCommunicationModel(
            DeepSeekCustomerCommunicationConfig(api_key="synthetic-test-key", max_attempts=1),
            transport=transport,
            budget=budget,
        ).compose(communication_input())
        assert reply.intent.value == "COMPENSATION_REVIEW_PENDING"
        assert reply.body == _communication_body()


def _communication_body() -> str:
    return (
        "调查结果显示，订单 ORDER-C129 的物流出现延迟。"
        "补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "input_tokens", "output_tokens"),
    [("intake", 80, 20), ("action", 30, 10), ("judgment", 19, 8), ("communication", 80, 30)],
)
async def test_each_model_role_settles_actual_response_usage_after_success(
    tmp_path: Path, role: str, input_tokens: int, output_tokens: int
) -> None:
    ledger_path = tmp_path / "budget.json"
    budget = CoreValidationBudget.create(
        ledger_path,
        authorization_id="synthetic-success-budget",
        limit_micros=3_000_000,
        max_attempts=10,
        max_tokens=1_000_000,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
    )
    requests: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if role == "communication":
            return _streamed(_completed(_communication_body()), split_at=80)
        payload = {
            "intake": _completed_intake_response,
            "action": lambda: _completed_action("CONFIRM_ORDER"),
            "judgment": _response,
        }[role]()
        return httpx.Response(200, json=payload)

    await _invoke_model(role, httpx.MockTransport(provider), budget)

    assert len(requests) == 1
    assert requests[0].method == "POST"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert len(ledger["entries"]) == 1
    entry = ledger["entries"][0]
    assert entry["status"] == "SETTLED"
    assert entry["role"] == role
    assert entry["inputTokens"] == input_tokens
    assert entry["outputTokens"] == output_tokens
    assert entry["estimatedCostMicros"] == input_tokens * 3 + output_tokens * 9
    assert entry["supplierChargeMicros"] is None


@pytest.mark.asyncio
async def test_intake_read_timeout_preserves_pending_and_blocks_the_next_post(tmp_path: Path) -> None:
    ledger_path = tmp_path / "budget.json"
    budget = CoreValidationBudget.create(
        ledger_path,
        authorization_id="synthetic-timeout-budget",
        limit_micros=3_000_000,
        max_attempts=10,
        max_tokens=1_000_000,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
    )
    requests: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("synthetic read timeout", request=request)

    transport = httpx.MockTransport(provider)
    with pytest.raises(httpx.ReadTimeout):
        await _invoke_model("intake", transport, budget)
    assert len(requests) == 1
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert len(saved["entries"]) == 1
    pending = saved["entries"][0]
    assert pending["status"] == "PENDING"
    assert pending["reservedMicros"] > 0
    for field in ("inputTokens", "outputTokens", "estimatedCostMicros", "supplierChargeMicros"):
        assert pending[field] is None
    with pytest.raises(CoreBudgetStopped):
        await _invoke_model("intake", transport, budget)
    assert len(requests) == 1
    assert json.loads(ledger_path.read_text(encoding="utf-8")) == saved
