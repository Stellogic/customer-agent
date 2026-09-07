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
            "DEEPSEEK_MODEL": "unsupported-model",
        },
        {"AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE": "unknown"},
    ],
)
def test_invalid_formal_customer_communication_configuration_fails_without_fallback(
    environment: dict[str, str],
) -> None:
    with pytest.raises(CustomerCommunicationFailure):
        configured_customer_communication_model(environment)


@pytest.mark.parametrize(
    ("base_model", "override"),
    [
        ("deepseek-v4-flash", None),
        ("deepseek-v4-pro", None),
        ("deepseek-v4-flash", "deepseek-v4-pro"),
        ("deepseek-v4-pro", "deepseek-v4-flash"),
    ],
)
def test_formal_customer_communication_runtime_freezes_bounded_attempts_and_deadline(
    base_model: str,
    override: str | None,
) -> None:
    environment = {
        "AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE": "deepseek-formal",
        "DEEPSEEK_API_KEY": "synthetic-test-key",
        "DEEPSEEK_MODEL": base_model,
    }
    if override is not None:
        environment["DEEPSEEK_COMMUNICATION_MODEL"] = override
    runtime = configured_customer_communication_model(
        environment,
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    )

    assert runtime.mode == f"{override or base_model}-customer-communication-formal-v1"
    assert isinstance(runtime.model, DeepSeekResponsesCustomerCommunicationModel)
    assert runtime.maximum_attempts == 2
    assert runtime.call_deadline_seconds == 15
