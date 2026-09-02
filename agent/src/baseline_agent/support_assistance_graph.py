"""独立HUMAN辅助图; 仅服务身份可调用, 不复活Agent generation。"""

import os
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from baseline_agent.support_assistance_model import generate_support_answer


class SupportAssistanceState(TypedDict, total=False):
    requested_by: str
    kind: str
    query: str
    context: dict[str, Any]
    knowledge: dict[str, Any]
    support_assistance: dict[str, Any]


async def assist(state: SupportAssistanceState) -> SupportAssistanceState:
    if state.get("requested_by") != "spring" or state.get("kind") not in {
        "summary",
        "knowledge",
        "policy",
        "draft",
    }:
        raise ValueError("invalid Spring assistance request")
    result = await generate_support_answer(
        {
            "kind": state["kind"],
            "query": state["query"],
            "context": state["context"],
            "knowledge": state["knowledge"],
        },
        os.environ,
    )
    return {"support_assistance": result}


builder = StateGraph(SupportAssistanceState)
builder.add_node("assist", assist)
builder.add_edge(START, "assist")
builder.add_edge("assist", END)
graph = builder.compile()
