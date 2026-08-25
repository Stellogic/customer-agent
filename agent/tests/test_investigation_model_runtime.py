import httpx
import pytest

from baseline_agent.deepseek_investigation_model import DeepSeekResponsesInvestigationModel
from baseline_agent.investigation_model import (
    FixedFakeInvestigationModel,
    InvestigationJudgmentFailure,
    InvestigationJudgmentFailureCode,
    InvestigationJudgmentInput,
)
from baseline_agent.investigation_model_runtime import configured_investigation_model


def test_default_runtime_is_explicit_fake_without_reading_provider_credentials() -> None:
    runtime = configured_investigation_model({"DEEPSEEK_API_KEY": "must-not-be-read"})

    assert runtime.mode == "fixed-fake-model-v1"
    assert isinstance(runtime.model, FixedFakeInvestigationModel)


def test_shadow_and_formal_flash_are_mutually_exclusive() -> None:
    with pytest.raises(InvestigationJudgmentFailure) as captured:
        configured_investigation_model(
            {
                "AGENT_INVESTIGATION_MODEL_MODE": "deepseek-formal",
                "AGENT_INVESTIGATION_SHADOW_MODE": "deepseek",
                "DEEPSEEK_API_KEY": "synthetic-test-key",
                "DEEPSEEK_MODEL": "deepseek-v4-flash",
            }
        )

    assert captured.value.code is InvestigationJudgmentFailureCode.CONFIGURATION_ERROR


@pytest.mark.parametrize(
    "environment",
    [
        {"AGENT_INVESTIGATION_MODEL_MODE": "deepseek-formal"},
        {
            "AGENT_INVESTIGATION_MODEL_MODE": "deepseek-formal",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
        },
        {
            "AGENT_INVESTIGATION_MODEL_MODE": "deepseek-formal",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
            "DEEPSEEK_MODEL": "deepseek-v4-pro",
        },
        {"AGENT_INVESTIGATION_MODEL_MODE": "unknown"},
    ],
)
def test_invalid_formal_configuration_fails_instead_of_falling_back_to_fake(
    environment: dict[str, str],
) -> None:
    with pytest.raises(InvestigationJudgmentFailure) as captured:
        configured_investigation_model(environment)

    assert captured.value.code is InvestigationJudgmentFailureCode.CONFIGURATION_ERROR


def test_formal_flash_freezes_bounded_provider_attempts_and_deadline() -> None:
    runtime = configured_investigation_model(
        {
            "AGENT_INVESTIGATION_MODEL_MODE": "deepseek-formal",
            "AGENT_INVESTIGATION_SHADOW_MODE": "disabled",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
            "DEEPSEEK_MODEL": "deepseek-v4-flash",
        },
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    )

    assert runtime.mode == "deepseek-v4-flash-formal-v1"
    assert isinstance(runtime.model, DeepSeekResponsesInvestigationModel)
    assert runtime.maximum_provider_attempts == 2
    assert runtime.call_deadline_seconds == 20


@pytest.mark.asyncio
async def test_formal_flash_exhausts_two_retryable_attempts_without_fake_fallback() -> None:
    requests = 0

    def supplier(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(429)

    runtime = configured_investigation_model(
        {
            "AGENT_INVESTIGATION_MODEL_MODE": "deepseek-formal",
            "AGENT_INVESTIGATION_SHADOW_MODE": "disabled",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
            "DEEPSEEK_MODEL": "deepseek-v4-flash",
        },
        transport=httpx.MockTransport(supplier),
    )

    with pytest.raises(InvestigationJudgmentFailure) as captured:
        await runtime.model.judge(
            InvestigationJudgmentInput(
                order_reference="SYNTHETIC-ORDER-127",
                delay_seconds=86_400,
                evidence_refs=(
                    "order:SYNTHETIC-ORDER-127",
                    "logistics:SYNTHETIC-ORDER-127",
                ),
            )
        )

    assert captured.value.code is InvestigationJudgmentFailureCode.MODEL_CALL_FAILED
    assert requests == runtime.maximum_provider_attempts == 2
