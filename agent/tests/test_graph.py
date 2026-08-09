import pytest

from baseline_agent.graph import investigate_ticket, probe_spring


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
        "orderReference": "ORDER-DELAY-UNDER-24",
        "evidenceRefs": ["order:ORDER-DELAY-UNDER-24", "logistics:ORDER-DELAY-UNDER-24"],
    }
    assert result["model_mode"] == "fixed-fake-model-v1"
    assert [call[0] for call in calls] == ["GET", "POST"]
