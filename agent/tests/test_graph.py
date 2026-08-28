import asyncio
import json

import httpx
import pytest

from baseline_agent.customer_communication_model import (
    CustomerCommunicationFailure,
    CustomerCommunicationFailureCode,
    StructuredCustomerCommunicationModel,
)
from baseline_agent.graph import (
    after_clarification,
    after_sibling_summary,
    await_clarification,
    graph,
    investigate_ticket,
    investigate_ticket_step,
    probe_spring,
    read_sibling_ticket_summary,
    request_clarification,
)
from baseline_agent.investigation_action_loop import (
    ActionDecision,
    ActionUsage,
    DeterministicActionModel,
    TerminalAction,
)
from baseline_agent.investigation_model import (
    InvestigationJudgment,
    InvestigationJudgmentFailure,
    InvestigationJudgmentFailureCode,
    InvestigationJudgmentInput,
    InvestigationReasonCode,
)
from baseline_agent.shadow_investigation import ShadowCandidate


@pytest.mark.asyncio
async def test_agent_reads_only_the_bounded_sibling_ticket_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers: dict[str, str] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "schemaVersion": "sibling-ticket-summary-v1",
                "tickets": [
                    {
                        "issueKind": "DUPLICATE_CHARGE",
                        "lifecycleState": "INVESTIGATING",
                        "pendingAction": "NONE",
                        "compensationFlowExists": False,
                    }
                ],
            }

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, _: str, *, headers: dict[str, str]) -> Response:
            captured_headers.update(headers)
            return Response()

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")

    result = await read_sibling_ticket_summary(
        {
            "requested_by": "spring",
            "ticket_id": "current-ticket",
            "generation_id": "current-generation",
        }
    )

    assert result["sibling_ticket_summary"]["tickets"][0] == {
        "issueKind": "DUPLICATE_CHARGE",
        "lifecycleState": "INVESTIGATING",
        "pendingAction": "NONE",
        "compensationFlowExists": False,
    }
    assert captured_headers["X-Agent-Operation"] == "READ_SIBLING_TICKET_SUMMARY"


@pytest.mark.asyncio
async def test_sibling_summary_retry_exhaustion_hands_off_instead_of_escaping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gets = 0
    posts: list[dict[str, object]] = []

    class HandoffResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"handlingMode": "HUMAN", "reasonCode": "TOOL_RETRY_EXHAUSTED"}

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, *_: object, **__: object) -> object:
            nonlocal gets
            gets += 1
            raise httpx.ReadTimeout("summary timeout")

        async def post(self, _: str, *, json: dict[str, object], **__: object) -> HandoffResponse:
            posts.append(json)
            return HandoffResponse()

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")
    monkeypatch.setenv("AGENT_TOOL_MAX_ATTEMPTS", "2")

    result = await read_sibling_ticket_summary(
        {
            "requested_by": "spring",
            "ticket_id": "current-ticket",
            "generation_id": "current-generation",
        }
    )

    assert gets == 2
    assert posts[0]["reasonCode"] == "TOOL_RETRY_EXHAUSTED"
    assert result["handoff"]["handlingMode"] == "HUMAN"
    assert after_sibling_summary(result) == "__end__"


def test_clarification_resume_refreshes_sibling_summary_before_investigation() -> None:
    assert after_clarification({"clarification_answer": {"answerDigest": "digest"}}) == (
        "read_sibling_ticket_summary"
    )


@pytest.mark.asyncio
async def test_langgraph_checkpoint_resume_keeps_decremented_budget_until_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability_calls: list[str] = []

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, **_: object) -> Response:
            return Response(_catalog_or_customer_context(url))

        async def post(self, url: str, **_: object) -> Response:
            if "/capabilities/" in url:
                capability_calls.append(url)
                return Response(_capability_result(url, _unique_facts()))
            return Response({"handlingMode": "HUMAN", "reasonCode": "TOOL_RETRY_EXHAUSTED"})

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")
    monkeypatch.setenv("AGENT_INVESTIGATION_MAX_ACTIONS", "2")
    monkeypatch.setenv("AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS", "2")
    initial = {
        "requested_by": "spring",
        "ticket_id": "ticket-checkpoint",
        "generation_id": "generation-checkpoint",
    }

    first = await investigate_ticket_step(initial)
    first_checkpoint = json.loads(json.dumps(first["investigation_progress"]))
    assert first_checkpoint["remainingActions"] == 1
    assert first_checkpoint["remainingProviderAttempts"] == 1

    second = await investigate_ticket_step({**initial, "investigation_progress": first_checkpoint})
    second_checkpoint = json.loads(json.dumps(second["investigation_progress"]))
    assert second_checkpoint["remainingActions"] == 0
    assert second_checkpoint["remainingProviderAttempts"] == 0
    assert second_checkpoint["providerAttempts"] == 2

    exhausted = await investigate_ticket_step(
        {**initial, "investigation_progress": second_checkpoint}
    )

    assert exhausted["handoff"]["reasonCode"] == "TOOL_RETRY_EXHAUSTED"
    assert exhausted["investigation_progress"] is None
    assert exhausted["investigation_run_evidence"]["failureClassification"] == "BUDGET_EXHAUSTED"
    assert exhausted["investigation_run_evidence"]["providerAttempts"] == 2
    assert len(capability_calls) == 2


class _OfflineShadowModel:
    def __init__(self, result: InvestigationJudgment | Exception) -> None:
        self.result = result
        self.inputs: list[InvestigationJudgmentInput] = []

    async def judge(self, model_input: InvestigationJudgmentInput) -> InvestigationJudgment:
        self.inputs.append(model_input)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
async def test_confirmed_non_logistics_issue_starts_independently_then_hands_off_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[tuple[str, dict[str, object]]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"handlingMode": "HUMAN", "reasonCode": "UNSUPPORTED_SCENARIO"}

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, object], **_: object) -> Response:
            posts.append((url, json))
            return Response()

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")

    result = await investigate_ticket_step(
        {
            "requested_by": "spring",
            "ticket_id": "package-ticket",
            "generation_id": "package-generation",
            "issue_kind": "PACKAGE_NOT_RECEIVED",
        }
    )

    assert result["handoff"]["reasonCode"] == "UNSUPPORTED_SCENARIO"
    assert len(posts) == 1
    assert posts[0][0].endswith("/human-handoff")
    assert posts[0][1]["reasonCode"] == "UNSUPPORTED_SCENARIO"


class _HandoffAfterFactsModel(DeterministicActionModel):
    async def choose(self, facts: dict) -> ActionDecision:
        if "policyVersion" in facts:
            return ActionDecision.from_values(TerminalAction.HANDOFF, {}, ActionUsage())
        return await super().choose(facts)


def _customer_communication_context() -> dict[str, object]:
    return {
        "schemaVersion": "customer-communication-input-v1",
        "syntheticCustomerText": "包裹还没到，请帮我调查",
        "publicConversation": [
            {"author": "CUSTOMER", "body": "包裹还没到，请帮我调查"},
            {"author": "SUPPORT", "body": "我们正在调查"},
        ],
    }


def _catalog_or_customer_context(url: str) -> dict[str, object]:
    if url.endswith("/customer-communication-context"):
        return _customer_communication_context()
    if url.endswith("/sibling-summary"):
        return {
            "schemaVersion": "sibling-ticket-summary-v1",
            "tickets": [
                {
                    "issueKind": "DUPLICATE_CHARGE",
                    "lifecycleState": "INVESTIGATING",
                    "pendingAction": "NONE",
                    "compensationFlowExists": False,
                }
            ],
        }
    return _capability_catalog()


@pytest.mark.asyncio
@pytest.mark.parametrize("force_handoff", [False, True])
async def test_terminal_handoff_and_budget_failure_preserve_controlled_action_records(
    monkeypatch: pytest.MonkeyPatch, force_handoff: bool
) -> None:
    posts: list[str] = []

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, **__: object) -> Response:
            return Response(_catalog_or_customer_context(url))

        async def post(self, url: str, **_: object) -> Response:
            posts.append(url)
            if "/capabilities/" in url:
                return Response(_capability_result(url, _unique_facts()))
            if url.endswith("/conclusions"):
                raise AssertionError("handoff path must not submit a conclusion")
            return Response({"handlingMode": "HUMAN", "reasonCode": "UNSUPPORTED_SCENARIO"})

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")
    if force_handoff:
        monkeypatch.setattr(
            "baseline_agent.graph.investigation_action_model", _HandoffAfterFactsModel()
        )
    else:
        monkeypatch.setenv("AGENT_INVESTIGATION_MAX_ACTIONS", "2")

    result = await investigate_ticket(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-120",
            "generation_id": "generation-120",
        }
    )

    assert result["handoff"]["handlingMode"] == "HUMAN"
    assert not any(url.endswith("/conclusions") for url in posts)
    action_types = [record["actionType"] for record in result["investigation_actions"]]
    if force_handoff:
        assert action_types[-1] == "HANDOFF"
        assert result["investigation_run_evidence"] == {
            "outcome": "HANDOFF_SELECTED",
            "failureClassification": "",
            "providerAttempts": 6,
            "toolRounds": 5,
            "tokens": 0,
            "costMicros": 0,
            "modelCalls": [
                {
                    "callNumber": index + 1,
                    "selectedAction": action,
                    "providerAttempts": 1,
                    "tokens": 0,
                    "costMicros": 0,
                }
                for index, action in enumerate(action_types)
            ],
        }
    else:
        assert action_types == ["CONFIRM_ORDER", "READ_LOGISTICS"]
        assert result["investigation_run_evidence"] == {
            "outcome": "SAFE_HANDOFF",
            "failureClassification": "BUDGET_EXHAUSTED",
            "providerAttempts": 2,
            "toolRounds": 2,
            "modelCalls": [
                {
                    "callNumber": 1,
                    "selectedAction": "CONFIRM_ORDER",
                    "providerAttempts": 1,
                    "tokens": 0,
                    "costMicros": 0,
                },
                {
                    "callNumber": 2,
                    "selectedAction": "READ_LOGISTICS",
                    "providerAttempts": 1,
                    "tokens": 0,
                    "costMicros": 0,
                },
            ],
        }


@pytest.mark.asyncio
async def test_default_business_graph_never_constructs_or_calls_a_shadow_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    model_contexts: list[dict] = []

    class CapturingActionModel(DeterministicActionModel):
        async def choose(self, facts: dict) -> ActionDecision:
            model_contexts.append(facts)
            return await super().choose(facts)

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, **_: object) -> Response:
            calls.append(("GET", url))
            return Response(_catalog_or_customer_context(url))

        async def post(self, url: str, **_: object) -> Response:
            calls.append(("POST", url))
            if "/capabilities/" in url:
                return Response(_capability_result(url, _unique_facts()))
            return Response({"accepted": True})

    def forbidden_factory() -> ShadowCandidate:
        raise AssertionError("disabled shadow must not construct a provider")

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setattr("baseline_agent.graph.investigation_action_model", CapturingActionModel())
    monkeypatch.setattr("baseline_agent.graph.shadow_candidate_factory", forbidden_factory)
    monkeypatch.delenv("AGENT_INVESTIGATION_SHADOW_MODE", raising=False)
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")

    result = await graph.ainvoke(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-116",
            "generation_id": "generation-116",
        }
    )

    assert "shadow_comparison" not in result
    assert model_contexts
    assert all(
        context["siblingTickets"]
        == [
            {
                "issueKind": "DUPLICATE_CHARGE",
                "lifecycleState": "INVESTIGATING",
                "pendingAction": "NONE",
                "compensationFlowExists": False,
            }
        ]
        for context in model_contexts
    )
    assert [method for method, url in calls if not url.endswith("/public-reply-events")] == [
        "GET",
        "GET",
        "POST",
        "POST",
        "POST",
        "POST",
        "POST",
        "GET",
        "POST",
    ]


@pytest.mark.parametrize(
    ("candidate_result", "expected_outcome"),
    [
        (
            InvestigationJudgment(
                compensation_review_required=True,
                reason_code=InvestigationReasonCode.LOGISTICS_DELAY,
            ),
            "MATCH",
        ),
        (RuntimeError("raw offline supplier failure"), "FAILED"),
    ],
)
@pytest.mark.asyncio
async def test_enabled_offline_shadow_only_adds_a_minimal_checkpoint_comparison(
    monkeypatch: pytest.MonkeyPatch,
    candidate_result: InvestigationJudgment | Exception,
    expected_outcome: str,
) -> None:
    posts: list[tuple[str, str]] = []
    shadow_model = _OfflineShadowModel(candidate_result)

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, **_: object) -> Response:
            return Response(_catalog_or_customer_context(url))

        async def post(self, url: str, *, headers: dict[str, str], **_: object) -> Response:
            if "/capabilities/" in url:
                return Response(_capability_result(url, _unique_facts()))
            posts.append((url, headers["Idempotency-Key"]))
            return Response({"accepted": True})

    candidate = ShadowCandidate(
        model=shadow_model,
        model_name="offline-deepseek-v4-flash",
        prompt_version="investigation-judgment-v1",
        schema_version="investigation-judgment-v1",
    )
    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setattr("baseline_agent.graph.shadow_candidate_factory", lambda: candidate)
    monkeypatch.setenv("AGENT_INVESTIGATION_SHADOW_MODE", "deepseek")
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")
    graph_input = {
        "requested_by": "spring",
        "ticket_id": "ticket-116",
        "generation_id": "generation-116",
    }

    first = await graph.ainvoke(graph_input)
    duplicate = await graph.ainvoke(graph_input)

    comparison = first["shadow_comparison"]
    assert comparison["outcome"] == expected_outcome
    assert duplicate["shadow_comparison"]["comparison_id"] == comparison["comparison_id"]
    assert set(comparison) == {
        "comparison_id",
        "ticket_id",
        "generation_id",
        "model",
        "prompt_version",
        "schema_version",
        "outcome",
        "failure_classification",
        "latency_ms",
        "provider_attempts",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "contract_valid",
        "provider_http_status",
    }
    assert shadow_model.inputs == [
        InvestigationJudgmentInput(
            order_reference="ORDER-116",
            delay_seconds=80 * 60 * 60,
            evidence_refs=("order:ORDER-116", "logistics:ORDER-116"),
        ),
        InvestigationJudgmentInput(
            order_reference="ORDER-116",
            delay_seconds=80 * 60 * 60,
            evidence_refs=("order:ORDER-116", "logistics:ORDER-116"),
        ),
    ]
    assert [post for post in posts if post[0].endswith("/conclusions")] == [
        (
            "http://spring/internal/agent/tickets/ticket-116/generations/generation-116/conclusions",
            "generation-116:submit-conclusion",
        ),
        (
            "http://spring/internal/agent/tickets/ticket-116/generations/generation-116/conclusions",
            "generation-116:submit-conclusion",
        ),
    ]
    serialized = repr(comparison)
    assert "ORDER-116" not in serialized
    assert "raw offline supplier failure" not in serialized


def _unique_facts() -> dict:
    return {
        "matchStatus": "UNIQUE",
        "orderReference": "ORDER-116",
        "delayHours": 80,
        "delaySeconds": 80 * 60 * 60,
        "paid": True,
        "cancelled": False,
        "fullyRefunded": False,
        "existingCompensation": False,
        "pendingActionCount": 0,
        "policyVersion": "delay-policy-v1",
        "evidenceRefs": ["order:ORDER-116", "logistics:ORDER-116"],
    }


def _capability_catalog() -> dict:
    result_fields = {
        "CONFIRM_ORDER": (
            ("capability", "STRING"),
            ("matchStatus", "STRING"),
            ("orderReference", "STRING"),
            ("evidenceRefs", "STRING_LIST"),
        ),
        "READ_LOGISTICS": (
            ("capability", "STRING"),
            ("delayHours", "INTEGER"),
            ("delaySeconds", "INTEGER"),
            ("evidenceRefs", "STRING_LIST"),
        ),
        "READ_PAYMENT_AND_REFUNDS": (
            ("capability", "STRING"),
            ("paid", "BOOLEAN"),
            ("cancelled", "BOOLEAN"),
            ("fullyRefunded", "BOOLEAN"),
            ("evidenceRefs", "STRING_LIST"),
        ),
        "READ_COMPENSATION_AND_PENDING_ACTIONS": (
            ("capability", "STRING"),
            ("existingCompensation", "BOOLEAN"),
            ("pendingActionCount", "INTEGER"),
            ("evidenceRefs", "STRING_LIST"),
        ),
        "READ_APPLICABLE_POLICY": (
            ("capability", "STRING"),
            ("policyVersion", "STRING"),
            ("evidenceRefs", "STRING_LIST"),
        ),
    }
    definitions = []
    for name, results in result_fields.items():
        parameters = (
            []
            if name == "CONFIRM_ORDER"
            else [{"name": "orderReference", "type": "STRING", "required": True}]
        )
        definitions.append(
            {
                "name": name,
                "parameters": parameters,
                "resultFields": [
                    {"name": field, "type": field_type, "required": True}
                    for field, field_type in results
                ],
            }
        )
    return {
        "schemaVersion": "investigation-capability-catalog-v1",
        "capabilities": definitions,
    }


def _capability_result(url: str, facts: dict) -> dict:
    capability = url.rsplit("/", 1)[-1]
    if capability == "CONFIRM_ORDER":
        return {
            "capability": capability,
            "matchStatus": facts.get("matchStatus"),
            "orderReference": facts.get("orderReference"),
            "evidenceRefs": []
            if facts.get("matchStatus") == "AMBIGUOUS"
            else [f"order:{facts.get('orderReference')}"],
        }
    fields = {
        "READ_LOGISTICS": ("delayHours", "delaySeconds"),
        "READ_PAYMENT_AND_REFUNDS": ("paid", "cancelled", "fullyRefunded"),
        "READ_COMPENSATION_AND_PENDING_ACTIONS": (
            "existingCompensation",
            "pendingActionCount",
        ),
        "READ_APPLICABLE_POLICY": ("policyVersion",),
    }[capability]
    evidence_refs = {
        "READ_LOGISTICS": [f"logistics:{facts.get('orderReference')}"],
        "READ_PAYMENT_AND_REFUNDS": [f"payment:{facts.get('orderReference')}"],
        "READ_COMPENSATION_AND_PENDING_ACTIONS": [
            f"compensation:{facts.get('orderReference')}",
            f"order-actions:{facts.get('orderReference')}",
        ],
        "READ_APPLICABLE_POLICY": [f"policy:{facts.get('policyVersion')}"],
    }[capability]
    return {
        "capability": capability,
        **{field: facts.get(field) for field in fields},
        "evidenceRefs": evidence_refs,
    }


@pytest.mark.parametrize(
    ("facts_payload", "expected_reason"),
    [
        (
            {
                "matchStatus": "UNIQUE",
                "orderReference": "ORDER-1",
                "delayHours": 2,
                "delaySeconds": 1,
                "paid": True,
                "cancelled": False,
                "fullyRefunded": False,
                "existingCompensation": False,
                "pendingActionCount": 0,
                "policyVersion": "delay-policy-v1",
                "evidenceRefs": ["order:ORDER-1", "logistics:ORDER-1"],
            },
            "FACT_CONFLICT",
        ),
        ({"orderReference": ["raw", "payload"], "delayHours": "bad"}, "INVALID_TOOL_RESPONSE"),
        ({"orderReference": "ORDER-1", "delayHours": 2}, "INVALID_TOOL_RESPONSE"),
        (
            {
                "matchStatus": "UNIQUE",
                "orderReference": "ORDER-1",
                "delayHours": 2,
                "delaySeconds": 7200,
                "paid": False,
                "cancelled": False,
                "fullyRefunded": False,
                "existingCompensation": False,
                "pendingActionCount": 0,
                "policyVersion": "delay-policy-v1",
                "evidenceRefs": ["order:ORDER-1", "logistics:ORDER-1"],
            },
            "UNSUPPORTED_SCENARIO",
        ),
    ],
)
@pytest.mark.asyncio
async def test_unsafe_investigation_uses_controlled_handoff_without_leaking_raw_payload(
    monkeypatch: pytest.MonkeyPatch,
    facts_payload: dict,
    expected_reason: str,
) -> None:
    posts: list[tuple[str, dict, dict[str, str]]] = []

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload
            self.status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, **__: object) -> Response:
            return Response(_catalog_or_customer_context(url))

        async def post(self, url: str, *, headers: dict[str, str], json: dict) -> Response:
            if "/capabilities/" in url:
                return Response(_capability_result(url, facts_payload))
            posts.append((url, json, headers))
            return Response({"handlingMode": "HUMAN", "reasonCode": expected_reason})

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")

    result = await investigate_ticket(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-19",
            "generation_id": "generation-19",
        }
    )

    assert result["handoff"]["reasonCode"] == expected_reason
    handoffs = [post for post in posts if post[0].endswith("/human-handoff")]
    assert len(handoffs) == 1
    url, body, headers = handoffs[0]
    assert url.endswith("/human-handoff")
    assert headers["X-Agent-Operation"] == "REQUEST_HUMAN_HANDOFF"
    assert headers["Idempotency-Key"] == f"generation-19:human-handoff:{expected_reason}"
    serialized = repr(body)
    assert "raw" not in serialized
    assert "payload" not in serialized
    assert set(body) == {"reasonCode", "summary"}


@pytest.mark.asyncio
async def test_transient_fact_tool_errors_retry_to_budget_then_handoff_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    posts: list[dict] = []

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"handlingMode": "HUMAN", "reasonCode": "TOOL_RETRY_EXHAUSTED"}

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, *_: object, **__: object) -> Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectError("secret upstream stack and payload")

        async def post(self, _url: str, *, headers: dict[str, str], json: dict) -> Response:
            if not _url.endswith("/public-reply-events"):
                posts.append(json)
            return Response()

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")
    monkeypatch.setenv("AGENT_TOOL_MAX_ATTEMPTS", "3")

    result = await investigate_ticket(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-19",
            "generation_id": "generation-19",
        }
    )

    assert attempts == 3
    assert result["handoff"]["reasonCode"] == "TOOL_RETRY_EXHAUSTED"
    assert posts == [
        {
            "reasonCode": "TOOL_RETRY_EXHAUSTED",
            "summary": {"conclusionCode": "INVESTIGATION_COULD_NOT_CONTINUE", "facts": []},
        }
    ]


@pytest.mark.parametrize("failure_mode", ["retry_exhausted", "fact_conflict"])
@pytest.mark.asyncio
async def test_conclusion_tool_retry_exhaustion_uses_the_same_stable_handoff_identity(
    monkeypatch: pytest.MonkeyPatch, failure_mode: str
) -> None:
    conclusion_attempts = 0
    handoff_keys: list[str] = []
    facts = {
        "matchStatus": "UNIQUE",
        "orderReference": "ORDER-1",
        "delayHours": 2,
        "delaySeconds": 7200,
        "paid": True,
        "cancelled": False,
        "fullyRefunded": False,
        "existingCompensation": False,
        "pendingActionCount": 0,
        "policyVersion": "delay-policy-v1",
        "evidenceRefs": ["order:ORDER-1", "logistics:ORDER-1"],
    }

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, **__: object) -> Response:
            return Response(_catalog_or_customer_context(url))

        async def post(self, url: str, *, headers: dict[str, str], json: dict) -> Response:
            nonlocal conclusion_attempts
            if "/capabilities/" in url:
                return Response(_capability_result(url, facts))
            if url.endswith("/conclusions"):
                conclusion_attempts += 1
                if failure_mode == "fact_conflict":
                    request = httpx.Request("POST", url)
                    response = httpx.Response(422, request=request)
                    raise httpx.HTTPStatusError("fact conflict", request=request, response=response)
                raise httpx.ConnectError("temporary conclusion failure")
            if url.endswith("/public-reply-events"):
                return Response({"accepted": True})
            handoff_keys.append(headers["Idempotency-Key"])
            reason = "FACT_CONFLICT" if failure_mode == "fact_conflict" else "TOOL_RETRY_EXHAUSTED"
            return Response({"handlingMode": "HUMAN", "reasonCode": reason})

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")
    monkeypatch.setenv("AGENT_TOOL_MAX_ATTEMPTS", "3")

    first = await investigate_ticket(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-19",
            "generation_id": "generation-19",
        }
    )
    replay = await investigate_ticket(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-19",
            "generation_id": "generation-19",
        }
    )

    expected_attempts = 2 if failure_mode == "fact_conflict" else 6
    expected_reason = "FACT_CONFLICT" if failure_mode == "fact_conflict" else "TOOL_RETRY_EXHAUSTED"
    assert conclusion_attempts == expected_attempts
    assert first["handoff"]["reasonCode"] == replay["handoff"]["reasonCode"] == expected_reason
    assert first["investigation_actions"][-1]["actionType"] == "SUBMIT_CONCLUSION"
    assert replay["investigation_actions"] == first["investigation_actions"]
    assert handoff_keys == [
        f"generation-19:human-handoff:{expected_reason}",
        f"generation-19:human-handoff:{expected_reason}",
    ]


@pytest.mark.asyncio
async def test_concurrent_unsafe_tool_results_share_one_handoff_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff_keys: list[str] = []
    facts = {
        "matchStatus": "UNIQUE",
        "orderReference": "ORDER-1",
        "delayHours": 2,
        "delaySeconds": 7200,
        "paid": False,
        "cancelled": False,
        "fullyRefunded": False,
        "existingCompensation": False,
        "pendingActionCount": 0,
        "policyVersion": "delay-policy-v1",
        "evidenceRefs": ["order:ORDER-1", "logistics:ORDER-1"],
    }

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, **__: object) -> Response:
            await asyncio.sleep(0)
            return Response(_catalog_or_customer_context(url))

        async def post(self, url: str, *, headers: dict[str, str], json: dict) -> Response:
            if "/capabilities/" in url:
                return Response(_capability_result(url, facts))
            if url.endswith("/human-handoff"):
                handoff_keys.append(headers["Idempotency-Key"])
            return Response({"handlingMode": "HUMAN", "reasonCode": json["reasonCode"]})

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")
    state = {"requested_by": "spring", "ticket_id": "ticket-19", "generation_id": "generation-19"}

    results = await asyncio.gather(investigate_ticket(state), investigate_ticket(state))

    assert [result["handoff"]["reasonCode"] for result in results] == [
        "UNSUPPORTED_SCENARIO",
        "UNSUPPORTED_SCENARIO",
    ]
    assert handoff_keys == [
        "generation-19:human-handoff:UNSUPPORTED_SCENARIO",
        "generation-19:human-handoff:UNSUPPORTED_SCENARIO",
    ]


@pytest.mark.asyncio
async def test_non_spring_callers_cannot_start_the_baseline_graph() -> None:
    with pytest.raises(ValueError, match="Spring-owned"):
        await probe_spring({"requested_by": "browser"})


@pytest.mark.asyncio
async def test_agent_collects_scoped_facts_and_submits_no_compensation_conclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict | None]] = []
    provider_requests: list[dict[str, object]] = []
    facts = {
        "matchStatus": "UNIQUE",
        "orderReference": "ORDER-DELAY-UNDER-24",
        "delayHours": 23,
        "delaySeconds": 23 * 60 * 60,
        "paid": True,
        "cancelled": False,
        "fullyRefunded": False,
        "existingCompensation": False,
        "pendingActionCount": 0,
        "policyVersion": "delay-policy-v1",
    }

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, *, headers: dict[str, str]) -> Response:
            calls.append(("GET", url, None))
            if url.endswith("/customer-communication-context"):
                assert headers["X-Agent-Operation"] == "READ_CUSTOMER_COMMUNICATION_CONTEXT"
            else:
                assert headers["X-Agent-Operation"] == "USE_INVESTIGATION_CAPABILITY"
            return Response(_catalog_or_customer_context(url))

        async def post(self, url: str, *, headers: dict[str, str], json: dict) -> Response:
            calls.append(("POST", url, json))
            if "/capabilities/" in url:
                assert headers["X-Agent-Operation"] == "USE_INVESTIGATION_CAPABILITY"
                return Response(_capability_result(url, facts))
            assert headers["X-Agent-Operation"] == "SUBMIT_INVESTIGATION_CONCLUSION"
            assert headers["Idempotency-Key"] == "generation-14:submit-conclusion"
            return Response({"accepted": True, "lifecycleState": "RESOLVED"})

    class ProviderStub:
        async def generate(self, request: dict[str, object]) -> dict[str, object]:
            provider_requests.append(request)
            return {
                "schemaVersion": "customer-reply-v1",
                "body": (
                    "经核验，订单 ORDER-DELAY-UNDER-24 的本次物流延迟不足 24 小时，"
                    "当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。"
                ),
                "intent": "NO_COMPENSATION_RESOLUTION",
                "evidenceRefs": [
                    "order:ORDER-DELAY-UNDER-24",
                    "logistics:ORDER-DELAY-UNDER-24",
                ],
                "escalationRequired": False,
                "referencedOrder": "ORDER-DELAY-UNDER-24",
            }

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setattr(
        "baseline_agent.graph.customer_communication_model",
        StructuredCustomerCommunicationModel(ProviderStub()),
    )
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")

    result = await investigate_ticket(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-14",
            "generation_id": "generation-14",
        }
    )

    assert result["conclusion"] == {
        "compensationRequired": False,
        "reasonCode": "DELAY_UNDER_24_HOURS",
        "delayHours": 23,
        "delaySeconds": 23 * 60 * 60,
        "orderReference": "ORDER-DELAY-UNDER-24",
        "evidenceRefs": ["order:ORDER-DELAY-UNDER-24", "logistics:ORDER-DELAY-UNDER-24"],
    }
    assert result["model_mode"] == "fixed-fake-model-v1"
    assert result["customer_reply"] == {
        "schemaVersion": "customer-reply-v1",
        "body": (
            "经核验，订单 ORDER-DELAY-UNDER-24 的本次物流延迟不足 24 小时，"
            "当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。"
        ),
        "intent": "NO_COMPENSATION_RESOLUTION",
        "evidenceRefs": [
            "order:ORDER-DELAY-UNDER-24",
            "logistics:ORDER-DELAY-UNDER-24",
        ],
        "escalationRequired": False,
        "referencedOrder": "ORDER-DELAY-UNDER-24",
    }
    submitted = next(call[2] for call in calls if call[1].endswith("/conclusions"))
    assert submitted == {**result["conclusion"], "customerReply": result["customer_reply"]}
    assert provider_requests[0]["untrustedCustomerData"] == {
        "syntheticCustomerText": "包裹还没到，请帮我调查",
        "publicConversation": [
            {"author": "CUSTOMER", "body": "包裹还没到，请帮我调查"},
            {"author": "SUPPORT", "body": "我们正在调查"},
        ],
    }
    stream_calls = [call for call in calls if call[1].endswith("/public-reply-events")]
    assert [call[2]["type"] for call in stream_calls] == [
        "LOADING",
        "PROGRESS",
        "PROGRESS",
        "PROGRESS",
        "PROGRESS",
        "STREAM_STARTED",
        "CONTENT_DELTA",
        "CONTENT_DELTA",
        "COMPLETED",
    ]
    assert [call[2]["stage"] for call in stream_calls if call[2]["type"] == "PROGRESS"] == [
        "UNDERSTANDING",
        "VERIFYING_FACTS",
        "QUERYING_RULES",
        "COMPOSING_REPLY",
    ]
    assert (
        "".join(call[2]["delta"] for call in stream_calls if call[2]["type"] == "CONTENT_DELTA")
        == result["customer_reply"]["body"]
    )
    assert [call[0] for call in calls if not call[1].endswith("/public-reply-events")] == [
        "GET",
        "POST",
        "POST",
        "POST",
        "POST",
        "POST",
        "GET",
        "POST",
    ]


@pytest.mark.asyncio
async def test_customer_communication_failure_hands_off_without_submitting_or_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[str] = []

    class FailedCommunicationModel:
        async def compose(self, _model_input):
            raise CustomerCommunicationFailure(CustomerCommunicationFailureCode.MODEL_CALL_FAILED)

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, **__: object) -> Response:
            return Response(_catalog_or_customer_context(url))

        async def post(self, url: str, *, json: dict, **_: object) -> Response:
            posts.append(url)
            if "/capabilities/" in url:
                return Response(_capability_result(url, _unique_facts()))
            if url.endswith("/conclusions"):
                raise AssertionError("unsafe communication must not submit a conclusion")
            return Response({"handlingMode": "HUMAN", "reasonCode": json["reasonCode"]})

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setattr(
        "baseline_agent.graph.customer_communication_model", FailedCommunicationModel()
    )
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")

    result = await investigate_ticket(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-122",
            "generation_id": "generation-122",
        }
    )

    assert result["handoff"]["reasonCode"] == "INVALID_MODEL_OUTPUT"
    assert not any(url.endswith("/conclusions") for url in posts)


@pytest.mark.asyncio
async def test_formal_investigation_model_failure_hands_off_without_fake_or_conclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[str] = []
    model_calls = 0

    class FailedFormalModel:
        async def judge(self, _model_input):
            nonlocal model_calls
            model_calls += 1
            raise InvestigationJudgmentFailure(InvestigationJudgmentFailureCode.MODEL_CALL_FAILED)

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, **__: object) -> Response:
            return Response(_catalog_or_customer_context(url))

        async def post(self, url: str, *, json: dict, **_: object) -> Response:
            posts.append(url)
            if "/capabilities/" in url:
                return Response(_capability_result(url, _unique_facts()))
            if url.endswith("/conclusions"):
                raise AssertionError("failed formal model must not submit a conclusion")
            return Response({"handlingMode": "HUMAN", "reasonCode": json["reasonCode"]})

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setattr("baseline_agent.graph.investigation_judgment_model", FailedFormalModel())
    monkeypatch.setattr(
        "baseline_agent.graph.investigation_model_mode",
        "deepseek-v4-flash-formal-v1",
    )
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")

    result = await investigate_ticket(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-127",
            "generation_id": "generation-127",
        }
    )

    assert model_calls == 1
    assert result["handoff"]["reasonCode"] == "INVALID_MODEL_OUTPUT"
    assert result["model_mode"] == "deepseek-v4-flash-formal-v1"
    assert not any(url.endswith("/conclusions") for url in posts)


@pytest.mark.asyncio
async def test_ambiguous_order_creates_a_controlled_request_before_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "clarificationRequestId": "clarification-16",
                "promptCode": "ORDER_CONFIRMATION_CODE",
                "question": "请回复订单确认码（A 或 B），以便继续调查。",
            }

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict) -> Response:
            calls.append((url, json))
            assert headers["X-Agent-Operation"] == "CREATE_CUSTOMER_CLARIFICATION"
            return Response()

        async def get(self, url: str, *, headers: dict[str, str]) -> Response:
            assert url.endswith("/customer-communication-context")
            assert headers["X-Agent-Operation"] == "READ_CUSTOMER_COMMUNICATION_CONTEXT"
            response = Response()
            response.json = lambda: {
                "schemaVersion": "customer-communication-input-v1",
                "syntheticCustomerText": "两个订单都可能，请问需要哪个？",
                "publicConversation": [],
            }
            return response

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")

    result = await request_clarification(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-16",
            "generation_id": "generation-16",
            "facts": {"matchStatus": "AMBIGUOUS", "orderReference": "ORDER-PENDING"},
        }
    )

    assert result["clarification"]["clarificationRequestId"] == "clarification-16"
    assert calls[0][1]["reasonCode"] == "ORDER_AMBIGUOUS"
    assert calls[0][1]["customerReply"]["intent"] == "CLARIFICATION_REQUIRED"


@pytest.mark.asyncio
async def test_ambiguous_order_customer_human_request_uses_handoff_instead_of_clarification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[tuple[str, dict]] = []

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, _url: str, *, headers: dict[str, str]) -> Response:
            assert headers["X-Agent-Operation"] == "READ_CUSTOMER_COMMUNICATION_CONTEXT"
            return Response(
                {
                    "schemaVersion": "customer-communication-input-v1",
                    "syntheticCustomerText": "请直接转人工客服",
                    "publicConversation": [],
                }
            )

        async def post(self, url: str, *, headers: dict[str, str], json: dict) -> Response:
            posts.append((url, json))
            assert headers["X-Agent-Operation"] == "REQUEST_HUMAN_HANDOFF"
            return Response({"reasonCode": "CUSTOMER_REQUESTED_HUMAN"})

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")

    result = await request_clarification(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-16",
            "generation_id": "generation-16",
            "facts": {"matchStatus": "AMBIGUOUS", "orderReference": "ORDER-PENDING"},
        }
    )

    assert result["handoff"]["reasonCode"] == "CUSTOMER_REQUESTED_HUMAN"
    assert posts[0][0].endswith("/human-handoff")
    assert posts[0][1]["reasonCode"] == "CUSTOMER_REQUESTED_HUMAN"


def test_clarification_interrupt_and_checkpoint_contain_only_recovery_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict] = []
    monkeypatch.setattr(
        "baseline_agent.graph.interrupt",
        lambda value: captured.append(value) or {"answerDigest": "digest"},
    )

    result = await_clarification(
        {
            "clarification": {
                "clarificationRequestId": "clarification-16",
                "promptCode": "ORDER_CONFIRMATION_CODE",
                "question": "请回复订单确认码（A 或 B），以便继续调查。",
            }
        }
    )

    assert captured == [
        {
            "clarificationRequestId": "clarification-16",
            "promptCode": "ORDER_CONFIRMATION_CODE",
            "question": "请回复订单确认码（A 或 B），以便继续调查。",
        }
    ]
    assert result == {"clarification_answer": {"clarificationRequestId": "clarification-16"}}
    assert "digest" not in repr(result)
