import os
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph


class BaselineState(TypedDict, total=False):
    requested_by: str
    spring_probe: dict[str, str]
    ticket_id: str
    generation_id: str
    facts: dict
    conclusion: dict
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


def fixed_fake_model(facts: dict) -> dict:
    if facts["delayHours"] >= 24 or facts["pendingActionCount"] != 0:
        raise ValueError("issue #14 fake model supports only the no-compensation policy tier")
    return {
        "compensationRequired": False,
        "reasonCode": "DELAY_UNDER_24_HOURS",
        "delayHours": facts["delayHours"],
        "orderReference": facts["orderReference"],
        "evidenceRefs": facts["evidenceRefs"],
    }


def select_work(state: BaselineState) -> str:
    return "investigate_ticket" if state.get("ticket_id") else "probe_spring"


builder = StateGraph(BaselineState)
builder.add_node("probe_spring", probe_spring)
builder.add_node("investigate_ticket", investigate_ticket)
builder.add_conditional_edges(START, select_work)
builder.add_edge("probe_spring", END)
builder.add_edge("investigate_ticket", END)
graph = builder.compile()
