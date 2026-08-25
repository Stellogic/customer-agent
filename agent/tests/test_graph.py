import asyncio

import httpx
import pytest

from baseline_agent.graph import (
    await_clarification,
    graph,
    investigate_ticket,
    probe_spring,
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
    InvestigationJudgmentInput,
    InvestigationReasonCode,
)
from baseline_agent.shadow_investigation import ShadowCandidate


class _OfflineShadowModel:
    def __init__(self, result: InvestigationJudgment | Exception) -> None:
        self.result = result
        self.inputs: list[InvestigationJudgmentInput] = []

    async def judge(self, model_input: InvestigationJudgmentInput) -> InvestigationJudgment:
        self.inputs.append(model_input)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _HandoffAfterFactsModel(DeterministicActionModel):
    async def choose(self, facts: dict) -> ActionDecision:
        if "policyVersion" in facts:
            return ActionDecision.from_values(TerminalAction.HANDOFF, {}, ActionUsage())
        return await super().choose(facts)


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

        async def get(self, *_: object, **__: object) -> Response:
            return Response(_capability_catalog())

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
    else:
        assert action_types == ["CONFIRM_ORDER", "READ_LOGISTICS"]


@pytest.mark.asyncio
async def test_default_business_graph_never_constructs_or_calls_a_shadow_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

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
            return Response(_capability_catalog())

        async def post(self, url: str, **_: object) -> Response:
            calls.append(("POST", url))
            if "/capabilities/" in url:
                return Response(_capability_result(url, _unique_facts()))
            return Response({"accepted": True})

    def forbidden_factory() -> ShadowCandidate:
        raise AssertionError("disabled shadow must not construct a provider")

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
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
    assert [method for method, _ in calls] == [
        "GET",
        "POST",
        "POST",
        "POST",
        "POST",
        "POST",
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

        async def get(self, _url: str, **_: object) -> Response:
            return Response(_capability_catalog())

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
    assert posts == [
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

        async def get(self, *_: object, **__: object) -> Response:
            return Response(_capability_catalog())

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
    assert len(posts) == 1
    url, body, headers = posts[0]
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

        async def get(self, *_: object, **__: object) -> Response:
            return Response(_capability_catalog())

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

        async def get(self, *_: object, **__: object) -> Response:
            await asyncio.sleep(0)
            return Response(_capability_catalog())

        async def post(self, url: str, *, headers: dict[str, str], json: dict) -> Response:
            if "/capabilities/" in url:
                return Response(_capability_result(url, facts))
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
            assert headers["X-Agent-Operation"] == "USE_INVESTIGATION_CAPABILITY"
            return Response(_capability_catalog())

        async def post(self, url: str, *, headers: dict[str, str], json: dict) -> Response:
            calls.append(("POST", url, json))
            if "/capabilities/" in url:
                assert headers["X-Agent-Operation"] == "USE_INVESTIGATION_CAPABILITY"
                return Response(_capability_result(url, facts))
            assert headers["X-Agent-Operation"] == "SUBMIT_INVESTIGATION_CONCLUSION"
            assert headers["Idempotency-Key"] == "generation-14:submit-conclusion"
            return Response({"accepted": True, "lifecycleState": "RESOLVED"})

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
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
    assert [call[0] for call in calls] == ["GET", "POST", "POST", "POST", "POST", "POST", "POST"]


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

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")

    result = await request_clarification(
        {
            "requested_by": "spring",
            "ticket_id": "ticket-16",
            "generation_id": "generation-16",
            "facts": {"matchStatus": "AMBIGUOUS"},
        }
    )

    assert result["clarification"]["clarificationRequestId"] == "clarification-16"
    assert calls[0][1] == {"reasonCode": "ORDER_AMBIGUOUS"}


def test_clarification_interrupt_contains_only_public_controlled_fields(
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
    assert result == {
        "clarification_answer": {
            "answerDigest": "digest",
            "clarificationRequestId": "clarification-16",
        }
    }
