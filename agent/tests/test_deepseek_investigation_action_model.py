import json

import httpx
import pytest

from baseline_agent.deepseek_investigation_action_model import (
    DeepSeekActionConfig,
    DeepSeekResponsesInvestigationActionModel,
)
from baseline_agent.investigation_action_loop import (
    ActionLoopFailure,
    InvestigationCapability,
    TerminalAction,
)


def _completed_action(action: str, order_reference: str | None) -> dict:
    return {
        "id": "response-128",
        "status": "completed",
        "model": "deepseek-v4-flash-202608",
        "system_fingerprint": "synthetic-fingerprint",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"action": action, "orderReference": order_reference}),
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 30,
            "output_tokens": 10,
            "total_tokens": 40,
        },
    }


@pytest.mark.asyncio
async def test_flash_selects_one_strict_action_from_minimal_normalized_facts() -> None:
    captured: list[httpx.Request] = []

    def supplier(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_completed_action("READ_LOGISTICS", "ORDER-128"),
        )

    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(supplier),
    )
    decision = await model.choose(
        {
            "matchStatus": "UNIQUE",
            "orderReference": "ORDER-128",
            "evidenceRefs": ["order:ORDER-128"],
        }
    )

    assert decision.action.kind is InvestigationCapability.READ_LOGISTICS
    assert decision.action.parameter_map == {"orderReference": "ORDER-128"}
    assert decision.usage.tokens == 40
    assert decision.usage.provider_attempts == 1
    assert 0 < decision.usage.cost_micros < 100_000
    assert len(captured) == 1
    body = json.loads(captured[0].content)
    assert set(body) == {
        "model",
        "instructions",
        "input",
        "max_output_tokens",
        "reasoning",
        "stream",
        "text",
    }
    assert body["model"] == "deepseek-v4-flash"
    assert body["reasoning"] == {"effort": "none"}
    assert body["text"]["format"]["strict"] is True
    sent = json.loads(body["input"])
    assert sent == {
        "syntheticInvestigationFacts": {
            "evidenceRefs": ["order:ORDER-128"],
            "matchStatus": "UNIQUE",
            "orderReference": "ORDER-128",
        }
    }
    assert "synthetic-test-key" not in captured[0].content.decode()


@pytest.mark.asyncio
async def test_flash_allows_terminal_action_without_order_parameter() -> None:
    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=_completed_action("SUBMIT_CONCLUSION", None))
        ),
    )

    decision = await model.choose(
        {
            "matchStatus": "UNIQUE",
            "orderReference": "ORDER-128",
            "delaySeconds": 90_000,
            "paid": True,
            "existingCompensation": False,
            "policyVersion": "delay-policy-v1",
        }
    )

    assert decision.action.kind is TerminalAction.SUBMIT_CONCLUSION
    assert decision.action.parameter_map == {}


@pytest.mark.asyncio
async def test_flash_allows_only_clarification_for_an_ambiguous_match() -> None:
    captured: list[httpx.Request] = []

    def supplier(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_completed_action("HANDOFF", None))

    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(supplier),
    )

    with pytest.raises(ActionLoopFailure):
        await model.choose({"matchStatus": "AMBIGUOUS", "orderReference": "ORDER-128"})

    body = json.loads(captured[0].content)
    allowed = body["text"]["format"]["schema"]["properties"]["action"]["enum"]
    assert allowed == ["REQUEST_CLARIFICATION"]


@pytest.mark.asyncio
async def test_flash_rejects_a_capability_after_its_facts_are_already_known() -> None:
    captured: list[httpx.Request] = []

    def supplier(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_completed_action("READ_LOGISTICS", "ORDER-128"),
        )

    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(supplier),
    )

    with pytest.raises(ActionLoopFailure):
        await model.choose(
            {
                "matchStatus": "UNIQUE",
                "orderReference": "ORDER-128",
                "delayHours": 25,
                "delaySeconds": 90_000,
            }
        )

    body = json.loads(captured[0].content)
    allowed = body["text"]["format"]["schema"]["properties"]["action"]["enum"]
    assert "READ_LOGISTICS" not in allowed
    assert "READ_PAYMENT_AND_REFUNDS" in allowed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        _completed_action("READ_LOGISTICS", None),
        _completed_action("SUBMIT_CONCLUSION", "ORDER-128"),
        _completed_action("DELETE_TICKET", None),
        {"status": "completed", "output": []},
    ],
)
async def test_invalid_or_unauthorized_output_fails_closed(payload: dict) -> None:
    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ActionLoopFailure):
        await model.choose({})


@pytest.mark.asyncio
async def test_retryable_supplier_error_has_two_attempt_bound_and_no_model_fallback() -> None:
    requests = 0

    def supplier(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(429)

    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(
            api_key="synthetic-test-key",
            max_attempts=2,
            retry_base_delay_seconds=0,
        ),
        transport=httpx.MockTransport(supplier),
    )

    with pytest.raises(ActionLoopFailure) as captured:
        await model.choose({})

    assert requests == 2
    assert captured.value.code.value == "MODEL_CALL_FAILED"
    assert captured.value.provider_attempts == 2
