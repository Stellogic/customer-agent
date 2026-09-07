from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from test_deepseek_customer_communication_model import _input as communication_input
from test_deepseek_intake_model import _clarifying_intake_input
from test_deepseek_investigation_model import MODEL_INPUT

from baseline_agent.core_validation_budget import CoreBudgetStopped, CoreValidationBudget
from baseline_agent.customer_communication_model_runtime import configured_customer_communication_model
from baseline_agent.intake_model_runtime import configured_intake_model
from baseline_agent.investigation_action_model_runtime import configured_investigation_action_model
from baseline_agent.investigation_model_runtime import configured_investigation_model


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["intake", "action", "judgment", "communication"])
async def test_formal_runtime_uses_existing_shared_budget_before_sending(
    tmp_path: Path, role: str
) -> None:
    path = tmp_path / "budget.json"
    CoreValidationBudget.create(
        path,
        authorization_id="synthetic-runtime-budget",
        limit_micros=1,
        max_attempts=10,
        max_tokens=100_000,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
    )
    environment = {
        "DEEPSEEK_API_KEY": "synthetic-test-key",
        "DEEPSEEK_MODEL": "deepseek-v4-flash",
        "INVESTIGATION_MODEL_MODE": "deepseek-formal",
        "AGENT_INVESTIGATION_MODEL_MODE": "deepseek-formal",
        "AGENT_INVESTIGATION_ACTION_MODEL_MODE": "deepseek-formal",
        "AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE": "deepseek-formal",
        "CORE_VALIDATION_BUDGET_PATH": str(path),
        "CORE_VALIDATION_AUTHORIZATION_ID": "synthetic-runtime-budget",
    }
    requests: list[httpx.Request] = []

    def supplier(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(400)

    transport = httpx.MockTransport(supplier)
    with pytest.raises(CoreBudgetStopped):
        if role == "intake":
            model, _ = configured_intake_model(environment, transport=transport)
            await model.understand(_clarifying_intake_input())
        elif role == "action":
            action = configured_investigation_action_model(environment, transport=transport)
            await action.model.choose({})
        elif role == "judgment":
            judgment = configured_investigation_model(environment, transport=transport)
            await judgment.model.judge(MODEL_INPUT)
        else:
            communication = configured_customer_communication_model(environment, transport=transport)
            await communication.model.compose(communication_input())
    assert requests == []
