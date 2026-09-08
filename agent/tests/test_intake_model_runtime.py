import json

import httpx
import pytest

from baseline_agent.deepseek_intake_model import DeepSeekIntakeModel
from baseline_agent.deepseek_investigation_model import InMemoryModelCallAuditSink
from baseline_agent.intake_model import FixedFakeIntakeModel, IntakeModelInput, VisibleOrder
from baseline_agent.intake_model_runtime import configured_intake_model


def test_intake_defaults_to_the_explicit_fixed_fake_ci_mode() -> None:
    model, mode = configured_intake_model({})

    assert isinstance(model, FixedFakeIntakeModel)
    assert mode == "fixed-fake-intake-v1"


def test_formal_intake_requires_deepseek_credentials_and_never_falls_back() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        configured_intake_model({"INVESTIGATION_MODEL_MODE": "deepseek-formal"})

    model, mode = configured_intake_model(
        {
            "INVESTIGATION_MODEL_MODE": "deepseek-formal",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
        }
    )
    assert isinstance(model, DeepSeekIntakeModel)
    assert mode == "deepseek-formal-intake-v4"


@pytest.mark.asyncio
async def test_global_pro_selection_reaches_the_intake_provider_request() -> None:
    requests: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(400)

    model, _ = configured_intake_model(
        {
            "INVESTIGATION_MODEL_MODE": "deepseek-formal",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
            "DEEPSEEK_MODEL": "deepseek-v4-pro",
        },
        transport=httpx.MockTransport(provider),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await model.understand(
            IntakeModelInput(
                customer_message="ORDER-230 请解释物流状态",
                visible_orders=(VisibleOrder("ORDER-230", "合成订单"),),
            )
        )
    assert len(requests) == 1
    assert json.loads(requests[0].content)["model"] == "deepseek-v4-pro"
    assert isinstance(model, DeepSeekIntakeModel)
    assert isinstance(model.audit_sink, InMemoryModelCallAuditSink)
    assert model.audit_sink.records[0].request_model == "deepseek-v4-pro"
