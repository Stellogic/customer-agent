import json

import httpx
import pytest

from baseline_agent.deepseek_investigation_action_model import (
    DeepSeekActionConfig,
    DeepSeekResponsesInvestigationActionModel,
)
from baseline_agent.deepseek_investigation_model import (
    DeepSeekFailureClassification,
    InMemoryModelCallAuditSink,
)
from baseline_agent.investigation_action_loop import (
    ActionLoopFailure,
    InvestigationCapability,
    TerminalAction,
)


def _completed_action(action: str) -> dict:
    structured: dict[str, object] = {"action": action}
    if action == "SUBMIT_CONCLUSION":
        structured["evidence"] = _evidence_payload()
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
                        "text": json.dumps(structured),
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


def _evidence_catalog() -> list[dict[str, object]]:
    return [
        {"actionType": "CONFIRM_ORDER", "evidenceReferences": ["order:ORDER-128"]},
        {"actionType": "READ_LOGISTICS", "evidenceReferences": ["logistics:ORDER-128"]},
        {
            "actionType": "READ_PAYMENT_AND_REFUNDS",
            "evidenceReferences": ["payment:ORDER-128"],
        },
        {
            "actionType": "READ_COMPENSATION_AND_PENDING_ACTIONS",
            "evidenceReferences": ["compensation:ORDER-128", "actions:ORDER-128"],
        },
        {
            "actionType": "READ_APPLICABLE_POLICY",
            "evidenceReferences": ["policy:delay-policy-v1"],
        },
    ]


def _evidence_payload() -> list[dict[str, object]]:
    return [
        {"evidenceReference": "order:ORDER-128", "applicability": ["ORDER_IDENTITY"]},
        {"evidenceReference": "logistics:ORDER-128", "applicability": ["DELAY_DURATION"]},
        {"evidenceReference": "payment:ORDER-128", "applicability": ["ORDER_ELIGIBILITY"]},
        {
            "evidenceReference": "compensation:ORDER-128",
            "applicability": ["EXISTING_COMPENSATION"],
        },
        {"evidenceReference": "actions:ORDER-128", "applicability": ["PENDING_ACTIONS"]},
        {"evidenceReference": "policy:delay-policy-v1", "applicability": ["POLICY_BASIS"]},
    ]


@pytest.mark.asyncio
async def test_flash_selects_one_strict_action_from_minimal_normalized_facts() -> None:
    captured: list[httpx.Request] = []

    def supplier(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_completed_action("READ_LOGISTICS"),
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
async def test_fact_action_derives_authoritative_reference_without_supplier_echo() -> None:
    payload = _completed_action("READ_LOGISTICS")
    payload["output"][0]["content"][0]["text"] = json.dumps({"action": "READ_LOGISTICS"})
    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
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


@pytest.mark.asyncio
async def test_flash_allows_terminal_action_without_order_parameter() -> None:
    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=_completed_action("SUBMIT_CONCLUSION"))
        ),
    )

    decision = await model.choose(
        {
            "matchStatus": "UNIQUE",
            "orderReference": "ORDER-128",
            "delayHours": 25,
            "delaySeconds": 90_000,
            "paid": True,
            "cancelled": False,
            "fullyRefunded": False,
            "existingCompensation": False,
            "pendingActionCount": 0,
            "policyVersion": "delay-policy-v1",
            "evidenceCatalog": _evidence_catalog(),
        }
    )

    assert decision.action.kind is TerminalAction.SUBMIT_CONCLUSION
    assert decision.action.parameter_map == {}
    assert [claim.evidence_reference for claim in decision.evidence_claims] == [
        item["evidenceReference"] for item in _evidence_payload()
    ]


@pytest.mark.asyncio
async def test_flash_allows_only_clarification_for_an_ambiguous_match() -> None:
    captured: list[httpx.Request] = []

    def supplier(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_completed_action("HANDOFF"))

    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(supplier),
    )

    with pytest.raises(ActionLoopFailure):
        await model.choose({"matchStatus": "AMBIGUOUS", "orderReference": "ORDER-128"})

    body = json.loads(captured[0].content)
    allowed = body["text"]["format"]["schema"]["properties"]["action"]["enum"]
    assert allowed == ["REQUEST_CLARIFICATION"]
    assert set(body["text"]["format"]["schema"]["properties"]) == {"action"}


@pytest.mark.asyncio
async def test_flash_schema_requires_handoff_for_known_fact_conflict() -> None:
    captured: list[httpx.Request] = []

    def supplier(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_completed_action("HANDOFF"))

    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(supplier),
    )

    decision = await model.choose(
        {
            "matchStatus": "UNIQUE",
            "orderReference": "ORDER-128",
            "delayHours": 25,
            "delaySeconds": 90_001,
            "paid": True,
            "cancelled": False,
            "fullyRefunded": False,
            "existingCompensation": False,
            "pendingActionCount": 0,
            "policyVersion": "delay-policy-v1",
        }
    )

    assert decision.action.kind is TerminalAction.HANDOFF
    body = json.loads(captured[0].content)
    allowed = body["text"]["format"]["schema"]["properties"]["action"]["enum"]
    assert allowed == ["HANDOFF"]


@pytest.mark.asyncio
async def test_flash_rejects_a_capability_after_its_facts_are_already_known() -> None:
    captured: list[httpx.Request] = []

    def supplier(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_completed_action("READ_LOGISTICS"),
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
        _completed_action("READ_LOGISTICS"),
        _completed_action("SUBMIT_CONCLUSION"),
        _completed_action("DELETE_TICKET"),
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
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"status": "incomplete", "model": "deepseek-v4-flash-202608"},
            DeepSeekFailureClassification.PROVIDER_INCOMPLETE,
        ),
        (
            {
                "status": "incomplete",
                "model": "deepseek-v4-flash-202608",
                "incomplete_details": {"reason": "max_output_tokens"},
            },
            DeepSeekFailureClassification.OUTPUT_TRUNCATED,
        ),
        (
            {
                **_completed_action("CONFIRM_ORDER"),
                "output": [{"type": "message", "content": [{"type": "refusal"}]}],
            },
            DeepSeekFailureClassification.MODEL_REFUSAL,
        ),
        (
            {
                **_completed_action("CONFIRM_ORDER"),
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": " "}],
                    }
                ],
            },
            DeepSeekFailureClassification.EMPTY_OUTPUT,
        ),
        (
            {
                **_completed_action("CONFIRM_ORDER"),
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "{"}],
                    }
                ],
            },
            DeepSeekFailureClassification.INVALID_JSON,
        ),
        (
            _completed_action("DELETE_TICKET"),
            DeepSeekFailureClassification.SCHEMA_MISMATCH,
        ),
    ],
)
async def test_flash_preserves_sanitized_output_failure_classification(
    payload: dict, expected: DeepSeekFailureClassification
) -> None:
    audit = InMemoryModelCallAuditSink()
    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        audit_sink=audit,
    )

    with pytest.raises(ActionLoopFailure) as captured:
        await model.choose({})

    assert audit.records[0].failure_classification is expected
    assert captured.value.failure_classification == expected.value


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
