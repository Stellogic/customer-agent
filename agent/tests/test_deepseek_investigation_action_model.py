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
        {
            "actionType": "READ_ORDER_RULES",
            "evidenceReferences": ["order-rule:ORDER-128"],
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
        {"evidenceReference": "order-rule:ORDER-128", "applicability": ["ORDER_RULE"]},
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
    assert body["max_output_tokens"] == 128
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
            "orderRuleSummary": "ADDRESS_CHANGE_AND_CANCEL_RULES_V1",
            "evidenceCatalog": _evidence_catalog(),
        }
    )

    assert decision.action.kind is TerminalAction.SUBMIT_CONCLUSION
    assert decision.action.parameter_map == {}
    assert [claim.evidence_reference for claim in decision.evidence_claims] == [
        item["evidenceReference"] for item in _evidence_payload()
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [None, "包裹显示签收但没有收到，应该如何核实"])
async def test_final_decision_can_choose_knowledge_without_promoting_customer_text_to_facts(
    query,
) -> None:
    captured: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        response = _completed_action("SUBMIT_CONCLUSION")
        response["output"][0]["content"][0]["text"] = json.dumps(
            {
                "action": "SUBMIT_CONCLUSION",
                "evidence": _evidence_payload(),
                "knowledgeQuery": query,
            }
        )
        return httpx.Response(200, json=response)

    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(respond),
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
            "orderRuleSummary": "ADDRESS_CHANGE_AND_CANCEL_RULES_V1",
            "evidenceCatalog": _evidence_catalog(),
            "customerQuestion": "包裹显示签收但没有收到，怎么办？",
            "issueKind": "LOGISTICS_DELAY",
        }
    )

    assert decision.knowledge_query == query
    assert decision.action.parameter_map == {}
    assert len(captured) == 1
    assert captured[0]["max_output_tokens"] == 1024
    model_input = json.loads(captured[0]["input"])
    assert "customerQuestion" not in model_input["syntheticInvestigationFacts"]
    assert model_input["syntheticInvestigationFacts"]["issueKind"] == "LOGISTICS_DELAY"
    assert model_input["customerQuestion"] == "包裹显示签收但没有收到，怎么办？"
    assert "knowledgeQuery" in captured[0]["text"]["format"]["schema"]["required"]


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
            "orderRuleSummary": "ADDRESS_CHANGE_AND_CANCEL_RULES_V1",
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


def _program_completed_facts() -> dict:
    return {
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
        "evidenceCatalog": _evidence_catalog()[:-1],
        "requiredFacts": {
            "policyVersion": "evidence-sufficiency-v1",
            "riskScenario": "LOGISTICS_DELAY",
            "facts": [
                {
                    "factType": "ORDER",
                    "capability": "CONFIRM_ORDER",
                    "resultField": "orderReference",
                    "evidenceIndex": 0,
                    "applicability": "ORDER_IDENTITY",
                }
            ],
        },
        "requiredFactsComplete": True,
        "issueKind": "LOGISTICS_DELAY",
        "customerQuestion": "物流延迟了，接下来怎么办？",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "query"),
    [
        ("SUBMIT_CONCLUSION", "物流延迟后如何处理"),
        ("READ_ORDER_RULES", None),
        ("HANDOFF", None),
    ],
)
async def test_program_required_facts_leave_optional_investigation_to_model(action, query) -> None:
    captured: list[dict] = []

    def supplier(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        payload = _completed_action(action)
        payload["output"][0]["content"][0]["text"] = json.dumps(
            {"action": action, "evidence": [], "knowledgeQuery": query}
        )
        return httpx.Response(200, json=payload)

    audit = InMemoryModelCallAuditSink()
    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(supplier),
        audit_sink=audit,
    )
    decision = await model.choose(_program_completed_facts())

    assert decision.action.kind.value == action
    assert decision.evidence_claims == ()
    assert decision.knowledge_query == query
    schema = captured[0]["text"]["format"]["schema"]
    assert set(schema["properties"]["action"]["enum"]) == {
        "READ_ORDER_RULES",
        "SUBMIT_CONCLUSION",
        "HANDOFF",
    }
    assert schema["properties"]["evidence"]["minItems"] == 0
    assert set(schema["required"]) == {"action", "evidence", "knowledgeQuery"}
    assert captured[0]["max_output_tokens"] == 1024
    assert audit.records[0].actual_response_shape_valid
    assert audit.records[0].total_tokens == 40


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "evidence", "query"),
    [
        ("READ_LOGISTICS", [], None),
        ("READ_ORDER_RULES", _evidence_payload()[:1], None),
        ("HANDOFF", [], "物流政策"),
        (
            "SUBMIT_CONCLUSION",
            [{"evidenceReference": "invented", "applicability": ["ORDER_IDENTITY"]}],
            None,
        ),
    ],
)
async def test_program_path_rejects_read_facts_and_misplaced_submission_fields(
    action, evidence, query
) -> None:
    payload = _completed_action(action)
    payload["output"][0]["content"][0]["text"] = json.dumps(
        {"action": action, "evidence": evidence, "knowledgeQuery": query}
    )
    audit = InMemoryModelCallAuditSink()
    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        audit_sink=audit,
    )
    with pytest.raises(ActionLoopFailure):
        await model.choose(_program_completed_facts())
    assert len(audit.records) == 1
    assert audit.records[0].failure_classification is DeepSeekFailureClassification.SCHEMA_MISMATCH


@pytest.mark.asyncio
async def test_program_path_keeps_clarification_for_ambiguous_order() -> None:
    captured: list[dict] = []

    def supplier(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=_completed_action("REQUEST_CLARIFICATION"))

    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(supplier),
    )
    decision = await model.choose(
        {
            "matchStatus": "AMBIGUOUS",
            "requiredFacts": _program_completed_facts()["requiredFacts"],
            "requiredFactsComplete": False,
        }
    )

    assert decision.action.kind is TerminalAction.REQUEST_CLARIFICATION
    schema = captured[0]["text"]["format"]["schema"]
    assert schema["properties"]["action"]["enum"] == ["REQUEST_CLARIFICATION"]
    assert schema["required"] == ["action"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("actions", "attempts", "action", "allowed"),
    [
        (1, 2, "SUBMIT_CONCLUSION", True),
        (2, 1, "SUBMIT_CONCLUSION", True),
        (1, 2, "READ_ORDER_RULES", False),
        (2, 1, "READ_ORDER_RULES", False),
        (2, 2, "READ_ORDER_RULES", True),
    ],
)
async def test_optional_read_reserves_an_action_and_provider_attempt_for_submission(
    actions: int, attempts: int, action: str, allowed: bool
) -> None:
    captured: list[dict] = []

    def supplier(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        payload = _completed_action(action)
        payload["output"][0]["content"][0]["text"] = json.dumps(
            {"action": action, "evidence": [], "knowledgeQuery": None}
        )
        return httpx.Response(200, json=payload)

    audit = InMemoryModelCallAuditSink()
    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(supplier),
        audit_sink=audit,
    )
    facts = {
        **_program_completed_facts(),
        "actionBudget": {"remainingActions": actions, "remainingProviderAttempts": attempts},
    }
    if allowed:
        decision = await model.choose(facts)
        assert decision.action.kind.value == action
    else:
        with pytest.raises(ActionLoopFailure) as failure:
            await model.choose(facts)
        assert failure.value.failure_classification == "SCHEMA_MISMATCH"

    assert len(captured) == 1
    offered = captured[0]["text"]["format"]["schema"]["properties"]["action"]["enum"]
    assert ("READ_ORDER_RULES" in offered) == (actions >= 2 and attempts >= 2)
    assert "SUBMIT_CONCLUSION" in offered
    assert "HANDOFF" in offered
    assert len(audit.records) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [False, True])
async def test_pro_action_prices_known_usage_on_success_and_parse_failure(malformed: bool) -> None:
    def supplier(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["model"] == "deepseek-v4-pro"
        payload = {**_completed_action("CONFIRM_ORDER"), "model": "deepseek-v4-pro-0813"}
        if malformed:
            payload["output"] = []
        return httpx.Response(200, json=payload)

    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", model="deepseek-v4-pro"),
        transport=httpx.MockTransport(supplier),
    )
    if malformed:
        with pytest.raises(ActionLoopFailure) as failure:
            await model.choose({})
        assert failure.value.tokens == 40
        assert failure.value.cost_micros == 80
    else:
        decision = await model.choose({})
        assert decision.action.kind is InvestigationCapability.CONFIRM_ORDER
        assert decision.usage.tokens == 40
        assert decision.usage.cost_micros == 80
    record = model.audit_sink.records[0]
    assert record.request_model == "deepseek-v4-pro"
    assert record.response_model == "deepseek-v4-pro-0813"


@pytest.mark.asyncio
async def test_pro_action_rejects_flash_response_instead_of_misidentifying_model() -> None:
    model = DeepSeekResponsesInvestigationActionModel(
        DeepSeekActionConfig(api_key="synthetic-test-key", model="deepseek-v4-pro"),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=_completed_action("CONFIRM_ORDER"))
        ),
    )
    with pytest.raises(ActionLoopFailure) as failure:
        await model.choose({})
    assert failure.value.failure_classification == "SCHEMA_MISMATCH"
