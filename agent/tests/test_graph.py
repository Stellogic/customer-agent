import asyncio

import httpx
import pytest

from baseline_agent.graph import (
    await_clarification,
    fixed_fake_model,
    investigate_ticket,
    probe_spring,
    request_clarification,
)


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
        (
            {
                "matchStatus": "AMBIGUOUS",
                "orderReference": "ORDER-1",
                "delayHours": None,
                "delaySeconds": None,
                "paid": None,
                "cancelled": None,
                "fullyRefunded": None,
                "existingCompensation": None,
                "pendingActionCount": None,
                "policyVersion": None,
                "evidenceRefs": [],
                "rawPayload": "must-not-pass",
            },
            "INVALID_TOOL_RESPONSE",
        ),
        ({"orderReference": "ORDER-1", "delayHours": 2}, "REQUIRED_FACT_MISSING"),
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
            return Response(facts_payload)

        async def post(self, url: str, *, headers: dict[str, str], json: dict) -> Response:
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


@pytest.mark.asyncio
async def test_conclusion_tool_retry_exhaustion_uses_the_same_stable_handoff_identity(
    monkeypatch: pytest.MonkeyPatch,
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
            return Response(facts)

        async def post(self, url: str, *, headers: dict[str, str], json: dict) -> Response:
            nonlocal conclusion_attempts
            if url.endswith("/conclusions"):
                conclusion_attempts += 1
                raise httpx.ConnectError("temporary conclusion failure")
            handoff_keys.append(headers["Idempotency-Key"])
            return Response({"handlingMode": "HUMAN", "reasonCode": "TOOL_RETRY_EXHAUSTED"})

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

    assert conclusion_attempts == 6
    assert (
        first["handoff"]["reasonCode"] == replay["handoff"]["reasonCode"] == "TOOL_RETRY_EXHAUSTED"
    )
    assert handoff_keys == [
        "generation-19:human-handoff:TOOL_RETRY_EXHAUSTED",
        "generation-19:human-handoff:TOOL_RETRY_EXHAUSTED",
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
            return Response(facts)

        async def post(self, _url: str, *, headers: dict[str, str], json: dict) -> Response:
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
            assert headers["X-Agent-Operation"] == "READ_INVESTIGATION_FACTS"
            return Response(
                {
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
                    "evidenceRefs": [
                        "order:ORDER-DELAY-UNDER-24",
                        "logistics:ORDER-DELAY-UNDER-24",
                    ],
                }
            )

        async def post(self, url: str, *, headers: dict[str, str], json: dict) -> Response:
            calls.append(("POST", url, json))
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
    assert [call[0] for call in calls] == ["GET", "POST"]


def test_agent_submits_a_structured_but_non_authoritative_compensation_suggestion() -> None:
    suggestion = fixed_fake_model(
        {
            "orderReference": "ORDER-DELAY-001",
            "delayHours": 80,
            "delaySeconds": 80 * 60 * 60,
            "paid": True,
            "cancelled": False,
            "fullyRefunded": False,
            "existingCompensation": False,
            "pendingActionCount": 0,
            "policyVersion": "delay-policy-v1",
            "evidenceRefs": ["order:ORDER-DELAY-001", "logistics:ORDER-DELAY-001"],
        }
    )

    assert suggestion == {
        "compensationRequired": True,
        "reasonCode": "LOGISTICS_DELAY",
        "delayHours": 80,
        "delaySeconds": 80 * 60 * 60,
        "orderReference": "ORDER-DELAY-001",
        "evidenceRefs": ["order:ORDER-DELAY-001", "logistics:ORDER-DELAY-001"],
        "suggestedMethod": "COUPON",
        "suggestedAmount": "999999.99",
    }


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
    assert result == {"clarification_answer": {"answerDigest": "digest"}}
