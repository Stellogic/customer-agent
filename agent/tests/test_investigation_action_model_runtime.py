import httpx
import pytest

from baseline_agent.deepseek_investigation_action_model import (
    DeepSeekResponsesInvestigationActionModel,
)
from baseline_agent.investigation_action_loop import (
    ActionLoopFailure,
    DeterministicActionModel,
)
from baseline_agent.investigation_action_model_runtime import (
    configured_investigation_action_model,
)


def test_default_action_runtime_is_deterministic_without_reading_provider_credentials() -> None:
    runtime = configured_investigation_action_model({"DEEPSEEK_API_KEY": "must-not-be-read"})

    assert runtime.mode == "deterministic-action-model-v1"
    assert isinstance(runtime.model, DeterministicActionModel)


@pytest.mark.parametrize(
    "environment",
    [
        {"AGENT_INVESTIGATION_ACTION_MODEL_MODE": "deepseek-formal"},
        {
            "AGENT_INVESTIGATION_ACTION_MODEL_MODE": "deepseek-formal",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
        },
        {
            "AGENT_INVESTIGATION_ACTION_MODEL_MODE": "deepseek-formal",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
            "DEEPSEEK_MODEL": "deepseek-v4-pro",
        },
        {"AGENT_INVESTIGATION_ACTION_MODEL_MODE": "unknown"},
    ],
)
def test_invalid_formal_action_configuration_fails_without_fallback(
    environment: dict[str, str],
) -> None:
    with pytest.raises(ActionLoopFailure):
        configured_investigation_action_model(environment)


def test_formal_action_runtime_freezes_one_model_attempt_and_deadline() -> None:
    runtime = configured_investigation_action_model(
        {
            "AGENT_INVESTIGATION_ACTION_MODEL_MODE": "deepseek-formal",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
            "DEEPSEEK_MODEL": "deepseek-v4-flash",
        },
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    )

    assert runtime.mode == "deepseek-v4-flash-action-formal-v1"
    assert isinstance(runtime.model, DeepSeekResponsesInvestigationActionModel)
    assert runtime.maximum_attempts_per_action == 1
    assert runtime.call_deadline_seconds == 12
