import pytest

from baseline_agent.graph import await_clarification, fixed_fake_model, request_clarification, investigate_ticket, probe_spring


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
            return Response({
                "orderReference": "ORDER-DELAY-UNDER-24",
                "delayHours": 23,
                "delaySeconds": 23 * 60 * 60,
                "paid": True,
                "cancelled": False,
                "fullyRefunded": False,
                "existingCompensation": False,
                "pendingActionCount": 0,
                "policyVersion": "delay-policy-v1",
                "evidenceRefs": ["order:ORDER-DELAY-UNDER-24", "logistics:ORDER-DELAY-UNDER-24"],
            })

        async def post(
            self, url: str, *, headers: dict[str, str], json: dict
        ) -> Response:
            calls.append(("POST", url, json))
            assert headers["X-Agent-Operation"] == "SUBMIT_INVESTIGATION_CONCLUSION"
            assert headers["Idempotency-Key"] == "generation-14:submit-conclusion"
            return Response({"accepted": True, "lifecycleState": "RESOLVED"})

    monkeypatch.setattr("baseline_agent.graph.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "agent-token")

    result = await investigate_ticket({
        "requested_by": "spring",
        "ticket_id": "ticket-14",
        "generation_id": "generation-14",
    })

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
    suggestion = fixed_fake_model({
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
    })

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

    result = await request_clarification({
        "requested_by": "spring",
        "ticket_id": "ticket-16",
        "generation_id": "generation-16",
        "facts": {"matchStatus": "AMBIGUOUS"},
    })

    assert result["clarification"]["clarificationRequestId"] == "clarification-16"
    assert calls[0][1] == {"reasonCode": "ORDER_AMBIGUOUS"}


def test_clarification_interrupt_contains_only_public_controlled_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []
    monkeypatch.setattr("baseline_agent.graph.interrupt", lambda value: captured.append(value) or {"answerDigest": "digest"})

    result = await_clarification({
        "clarification": {
            "clarificationRequestId": "clarification-16",
            "promptCode": "ORDER_CONFIRMATION_CODE",
            "question": "请回复订单确认码（A 或 B），以便继续调查。",
        }
    })

    assert captured == [{
        "clarificationRequestId": "clarification-16",
        "promptCode": "ORDER_CONFIRMATION_CODE",
        "question": "请回复订单确认码（A 或 B），以便继续调查。",
    }]
    assert result == {"clarification_answer": {"answerDigest": "digest"}}
