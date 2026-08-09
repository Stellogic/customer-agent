import os
from collections.abc import Awaitable, Callable
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt


class BaselineState(TypedDict, total=False):
    requested_by: str
    spring_probe: dict[str, str]
    ticket_id: str
    generation_id: str
    facts: dict
    conclusion: dict
    clarification: dict
    clarification_answer: dict
    model_mode: str
    handoff: dict


REQUIRED_FACT_FIELDS = {
    "matchStatus", "orderReference", "delayHours", "delaySeconds", "paid", "cancelled",
    "fullyRefunded", "existingCompensation", "pendingActionCount", "policyVersion", "evidenceRefs",
}


async def probe_spring(state: BaselineState) -> BaselineState:
    if state.get("requested_by") != "spring":
        raise ValueError("baseline graph accepts only Spring-owned probes")
    headers = {"Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}"}
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.get(
            f"{os.environ['SPRING_INTERNAL_URL']}/internal/capabilities/agent/probe",
            headers=headers,
        )
        response.raise_for_status()
        return {"spring_probe": response.json()}


async def investigate_ticket(state: BaselineState) -> BaselineState:
    if state.get("requested_by") != "spring":
        raise ValueError("ticket investigation accepts only Spring-owned runs")
    ticket_id = state["ticket_id"]
    generation_id = state["generation_id"]
    base_url = os.environ["SPRING_INTERNAL_URL"]
    authorization = f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}"
    scope_headers = {
        "Authorization": authorization,
        "X-Agent-Generation-Id": generation_id,
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        facts_response = await _request_with_retries(
            lambda: client.get(
                    f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/facts",
                    headers={**scope_headers, "X-Agent-Operation": "READ_INVESTIGATION_FACTS"},
            )
        )
        if facts_response is None:
            return await _human_handoff(
                client, base_url, ticket_id, generation_id, scope_headers,
                "TOOL_RETRY_EXHAUSTED", [],
            )
        try:
            facts = facts_response.json()
        except ValueError:
            facts = "INVALID_JSON_RESPONSE"
        unsafe_reason = _unsafe_facts_reason(facts)
        if unsafe_reason is not None:
            return await _human_handoff(
                client, base_url, ticket_id, generation_id, scope_headers,
                unsafe_reason, _controlled_summary_facts(facts),
            )
        if facts.get("matchStatus") == "AMBIGUOUS":
            return {"facts": facts, "model_mode": "fixed-fake-model-v1"}
        conclusion = fixed_fake_model(facts)
        try:
            conclusion_response = await _request_with_retries(
                lambda: client.post(
                    f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/conclusions",
                    headers={
                        **scope_headers,
                        "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                        "Idempotency-Key": f"{generation_id}:submit-conclusion",
                    },
                    json=conclusion,
                )
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 422:
                return await _human_handoff(
                    client, base_url, ticket_id, generation_id, scope_headers,
                    "FACT_CONFLICT", _controlled_summary_facts(facts),
                )
            raise
        if conclusion_response is None:
            return await _human_handoff(
                client, base_url, ticket_id, generation_id, scope_headers,
                "TOOL_RETRY_EXHAUSTED", _controlled_summary_facts(facts),
            )
        return {"facts": facts, "conclusion": conclusion, "model_mode": "fixed-fake-model-v1"}


def _tool_attempt_budget() -> int:
    try:
        configured = int(os.getenv("AGENT_TOOL_MAX_ATTEMPTS", "3"))
    except ValueError:
        return 3
    return min(max(configured, 1), 5)


async def _request_with_retries(
    request: Callable[[], Awaitable[httpx.Response]],
) -> httpx.Response | None:
    for _ in range(_tool_attempt_budget()):
        try:
            response = await request()
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.TimeoutException):
            continue
        except httpx.HTTPStatusError as error:
            if error.response.status_code >= 500:
                continue
            raise
    return None


def _unsafe_facts_reason(facts: object) -> str | None:
    if not isinstance(facts, dict):
        return "INVALID_TOOL_RESPONSE"
    present = set(facts)
    if facts.get("matchStatus") == "AMBIGUOUS":
        if not REQUIRED_FACT_FIELDS.issubset(present):
            return "REQUIRED_FACT_MISSING"
        if present != REQUIRED_FACT_FIELDS:
            return "INVALID_TOOL_RESPONSE"
        nullable_fields = (
            "delayHours", "delaySeconds", "paid", "cancelled", "fullyRefunded",
            "existingCompensation", "pendingActionCount", "policyVersion",
        )
        valid_ambiguity = isinstance(facts["orderReference"], str) \
            and all(facts[name] is None for name in nullable_fields) \
            and facts["evidenceRefs"] == []
        return None if valid_ambiguity else "INVALID_TOOL_RESPONSE"
    typed_values = {
        "orderReference": str,
        "delayHours": int,
        "delaySeconds": int,
        "paid": bool,
        "cancelled": bool,
        "fullyRefunded": bool,
        "existingCompensation": bool,
        "pendingActionCount": int,
        "policyVersion": str,
        "evidenceRefs": list,
        "matchStatus": str,
    }
    for name in present & REQUIRED_FACT_FIELDS:
        expected = typed_values[name]
        value = facts[name]
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            return "INVALID_TOOL_RESPONSE"
    if not REQUIRED_FACT_FIELDS.issubset(present):
        return "REQUIRED_FACT_MISSING"
    if present != REQUIRED_FACT_FIELDS:
        return "INVALID_TOOL_RESPONSE"
    if facts["matchStatus"] != "UNIQUE":
        return "INVALID_TOOL_RESPONSE"
    evidence = facts["evidenceRefs"]
    if not all(isinstance(item, str) for item in evidence):
        return "INVALID_TOOL_RESPONSE"
    expected_evidence = [
        f"order:{facts['orderReference']}",
        f"logistics:{facts['orderReference']}",
    ]
    if evidence != expected_evidence:
        return "INVALID_TOOL_RESPONSE"
    if facts["delaySeconds"] != facts["delayHours"] * 60 * 60:
        return "FACT_CONFLICT"
    if (
        not facts["paid"] or facts["cancelled"] or facts["fullyRefunded"]
        or facts["existingCompensation"] or facts["pendingActionCount"] != 0
        or facts["policyVersion"] != "delay-policy-v1"
    ):
        return "UNSUPPORTED_SCENARIO"
    return None


def _controlled_summary_facts(facts: object) -> list[dict[str, str]]:
    if not isinstance(facts, dict):
        return []
    evidence = facts.get("evidenceRefs")
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        return []
    order_reference = facts.get("orderReference")
    if not isinstance(order_reference, str):
        return []
    if evidence != [f"order:{order_reference}", f"logistics:{order_reference}"]:
        return []
    allowed = [{"type": "ORDER", "value": order_reference, "evidenceReference": evidence[0]}]
    if isinstance(facts.get("delaySeconds"), int) and not isinstance(facts.get("delaySeconds"), bool):
        allowed.append({
            "type": "LOGISTICS_DELAY_SECONDS",
            "value": str(facts["delaySeconds"]),
            "evidenceReference": evidence[1],
        })
    return allowed


async def _human_handoff(
    client: httpx.AsyncClient,
    base_url: str,
    ticket_id: str,
    generation_id: str,
    scope_headers: dict[str, str],
    reason_code: str,
    facts: list[dict[str, str]],
) -> BaselineState:
    response = await client.post(
        f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/human-handoff",
        headers={
            **scope_headers,
            "X-Agent-Operation": "REQUEST_HUMAN_HANDOFF",
            "Idempotency-Key": f"{generation_id}:human-handoff:{reason_code}",
        },
        json={
            "reasonCode": reason_code,
            "summary": {"conclusionCode": "INVESTIGATION_COULD_NOT_CONTINUE", "facts": facts},
        },
    )
    response.raise_for_status()
    return {"handoff": response.json(), "model_mode": "fixed-fake-model-v1"}


async def request_clarification(state: BaselineState) -> BaselineState:
    if state.get("requested_by") != "spring" or state.get("facts", {}).get("matchStatus") != "AMBIGUOUS":
        raise ValueError("clarification requires a Spring-owned ambiguous investigation")
    ticket_id = state["ticket_id"]
    generation_id = state["generation_id"]
    headers = {
        "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
        "X-Agent-Generation-Id": generation_id,
        "X-Agent-Operation": "CREATE_CUSTOMER_CLARIFICATION",
        "Idempotency-Key": f"{generation_id}:order-disambiguation",
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            f"{os.environ['SPRING_INTERNAL_URL']}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/clarifications",
            headers=headers,
            json={"reasonCode": "ORDER_AMBIGUOUS"},
        )
        response.raise_for_status()
        return {"clarification": response.json()}


def await_clarification(state: BaselineState) -> BaselineState:
    clarification = state["clarification"]
    public_interrupt = {
        "clarificationRequestId": clarification["clarificationRequestId"],
        "promptCode": clarification["promptCode"],
        "question": clarification["question"],
    }
    return {"clarification_answer": interrupt(public_interrupt)}


def fixed_fake_model(facts: dict) -> dict:
    if facts["delaySeconds"] >= 24 * 60 * 60:
        return {
            "compensationRequired": True,
            "reasonCode": "LOGISTICS_DELAY",
            "delayHours": facts["delayHours"],
            "delaySeconds": facts["delaySeconds"],
            "orderReference": facts["orderReference"],
            "evidenceRefs": facts["evidenceRefs"],
            # Intentionally wrong: Spring owns the authoritative method and amount.
            "suggestedMethod": "COUPON",
            "suggestedAmount": "999999.99",
        }
    return {
        "compensationRequired": False,
        "reasonCode": "DELAY_UNDER_24_HOURS",
        "delayHours": facts["delayHours"],
        "delaySeconds": facts["delaySeconds"],
        "orderReference": facts["orderReference"],
        "evidenceRefs": facts["evidenceRefs"],
    }


def select_work(state: BaselineState) -> str:
    return "investigate_ticket" if state.get("ticket_id") else "probe_spring"


def after_investigation(state: BaselineState) -> str:
    return "request_clarification" if state.get("facts", {}).get("matchStatus") == "AMBIGUOUS" else END


builder = StateGraph(BaselineState)
builder.add_node("probe_spring", probe_spring)
builder.add_node("investigate_ticket", investigate_ticket)
builder.add_node("request_clarification", request_clarification)
builder.add_node("await_clarification", await_clarification)
builder.add_conditional_edges(START, select_work)
builder.add_edge("probe_spring", END)
builder.add_conditional_edges("investigate_ticket", after_investigation)
builder.add_edge("request_clarification", "await_clarification")
builder.add_edge("await_clarification", "investigate_ticket")
graph = builder.compile()
