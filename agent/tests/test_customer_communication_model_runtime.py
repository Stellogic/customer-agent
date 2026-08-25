import httpx
import pytest

from baseline_agent.customer_communication_model import (
    CustomerCommunicationFailure,
    FixedFakeCustomerCommunicationModel,
)
from baseline_agent.customer_communication_model_runtime import (
    configured_customer_communication_model,
)
from baseline_agent.deepseek_customer_communication_model import (
    DeepSeekResponsesCustomerCommunicationModel,
)


def test_default_customer_communication_runtime_is_fixed_fake_without_credentials() -> None:
    runtime = configured_customer_communication_model({"DEEPSEEK_API_KEY": "must-not-be-read"})

    assert runtime.mode == "fixed-fake-customer-communication-v1"
    assert isinstance(runtime.model, FixedFakeCustomerCommunicationModel)


@pytest.mark.parametrize(
    "environment",
    [
        {"AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE": "deepseek-formal"},
        {
            "AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE": "deepseek-formal",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
        },
        {
            "AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE": "deepseek-formal",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
            "DEEPSEEK_MODEL": "deepseek-v4-pro",
        },
        {"AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE": "unknown"},
    ],
)
def test_invalid_formal_customer_communication_configuration_fails_without_fallback(
    environment: dict[str, str],
) -> None:
    with pytest.raises(CustomerCommunicationFailure):
        configured_customer_communication_model(environment)


def test_formal_customer_communication_runtime_freezes_bounded_attempts_and_deadline() -> None:
    runtime = configured_customer_communication_model(
        {
            "AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE": "deepseek-formal",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
            "DEEPSEEK_MODEL": "deepseek-v4-flash",
        },
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    )

    assert runtime.mode == "deepseek-v4-flash-customer-communication-formal-v1"
    assert isinstance(runtime.model, DeepSeekResponsesCustomerCommunicationModel)
    assert runtime.maximum_attempts == 2
    assert runtime.call_deadline_seconds == 15
