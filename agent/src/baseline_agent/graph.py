import os
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
        facts_response = await client.get(
            f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/facts",
            headers={**scope_headers, "X-Agent-Operation": "READ_INVESTIGATION_FACTS"},
        )
        facts_response.raise_for_status()
        facts = facts_response.json()
        if facts.get("matchStatus") == "AMBIGUOUS":
            return {"facts": facts, "model_mode": "fixed-fake-model-v1"}
        conclusion = fixed_fake_model(facts)
        conclusion_response = await client.post(
            f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/conclusions",
            headers={
                **scope_headers,
                "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                "Idempotency-Key": f"{generation_id}:submit-conclusion",
            },
            json=conclusion,
        )
        conclusion_response.raise_for_status()
        return {"facts": facts, "conclusion": conclusion, "model_mode": "fixed-fake-model-v1"}


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
