import os
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph


class BaselineState(TypedDict, total=False):
    requested_by: str
    spring_probe: dict[str, str]


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


builder = StateGraph(BaselineState)
builder.add_node("probe_spring", probe_spring)
builder.add_edge(START, "probe_spring")
builder.add_edge("probe_spring", END)
graph = builder.compile()

