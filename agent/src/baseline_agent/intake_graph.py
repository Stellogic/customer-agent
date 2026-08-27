from __future__ import annotations

import os
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from baseline_agent.intake_model import IntakeModelInput, VisibleOrder
from baseline_agent.intake_model_runtime import configured_intake_model


class IntakeState(TypedDict, total=False):
    requested_by: str
    customer_message: str
    visible_orders: list[dict[str, str]]
    current_order_reference: str
    current_issue_summary: str
    intake_understanding: dict[str, object]
    model_mode: str


intake_model, intake_model_mode = configured_intake_model(os.environ)


async def understand_intake(state: IntakeState) -> IntakeState:
    if state.get("requested_by") != "spring":
        raise ValueError("intake graph accepts only Spring-owned requests")
    orders = tuple(
        VisibleOrder(order["reference"], order["summary"])
        for order in state.get("visible_orders", [])
    )
    result = await intake_model.understand(
        IntakeModelInput(
            customer_message=state["customer_message"],
            visible_orders=orders,
            current_order_reference=state.get("current_order_reference") or None,
            current_issue_summary=state.get("current_issue_summary") or None,
        )
    )
    return {
        "model_mode": intake_model_mode,
        "intake_understanding": {
            "intent": result.intent,
            "status": result.status,
            "candidate_order_reference": result.candidate_order_reference,
            "issue_kind": result.issue_kind,
            "issue_summary": result.issue_summary,
            "assistant_message": result.assistant_message,
        },
    }


builder = StateGraph(IntakeState)
builder.add_node("understand_intake", understand_intake)
builder.add_edge(START, "understand_intake")
builder.add_edge("understand_intake", END)
graph = builder.compile()
