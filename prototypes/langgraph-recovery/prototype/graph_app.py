from __future__ import annotations

import operator
import sqlite3
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .model import stable_effect_key
from .stores import SpringAuthority


class InvestigationState(TypedDict, total=False):
    generation_id: str
    ticket_id: str
    steps: Annotated[list[str], operator.add]
    confirmation: str
    proposal: dict[str, Any]


def build_graph(checkpoint_path: Path, spring_db: Path):
    spring = SpringAuthority(spring_db)

    def investigate(state: InvestigationState) -> dict[str, Any]:
        return {"steps": ["investigation_facts_loaded"]}

    def wait_for_confirmation(state: InvestigationState) -> dict[str, Any]:
        answer = interrupt(
            {
                "kind": "investigation_confirmation",
                "generation_id": state["generation_id"],
                "question": "确认使用当前物流事实生成补偿提案？",
            }
        )
        return {"confirmation": str(answer), "steps": ["interrupt_resumed"]}

    def persist_proposal(state: InvestigationState) -> dict[str, Any]:
        payload = {"confirmation": state["confirmation"], "delay_hours": 52, "policy_version": "demo-v1"}
        result = spring.execute_business_tool(
            state["generation_id"],
            state["ticket_id"],
            stable_effect_key(state["generation_id"]),
            payload,
        )
        return {"proposal": result, "steps": ["proposal_persisted"]}

    builder = StateGraph(InvestigationState)
    builder.add_node("investigate", investigate)
    builder.add_node("wait_for_confirmation", wait_for_confirmation)
    builder.add_node("persist_proposal", persist_proposal)
    builder.add_edge(START, "investigate")
    builder.add_edge("investigate", "wait_for_confirmation")
    builder.add_edge("wait_for_confirmation", "persist_proposal")
    builder.add_edge("persist_proposal", END)

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
    saver = SqliteSaver(connection)
    return builder.compile(checkpointer=saver), connection


def build_server_graph():
    """Compiled without a checkpointer because Agent Server injects its own."""
    import os

    spring_db = Path(os.environ.get("PROTOTYPE_SPRING_DB", "scratch/server-spring.db"))
    spring = SpringAuthority(spring_db)

    def investigate(state: InvestigationState) -> dict[str, Any]:
        return {"steps": ["investigation_facts_loaded"]}

    def wait_for_confirmation(state: InvestigationState) -> dict[str, Any]:
        answer = interrupt({"kind": "investigation_confirmation", "generation_id": state["generation_id"]})
        return {"confirmation": str(answer), "steps": ["interrupt_resumed"]}

    def persist_proposal(state: InvestigationState) -> dict[str, Any]:
        result = spring.execute_business_tool(
            state["generation_id"],
            state["ticket_id"],
            stable_effect_key(state["generation_id"]),
            {"confirmation": state["confirmation"], "delay_hours": 52, "policy_version": "demo-v1"},
        )
        return {"proposal": result, "steps": ["proposal_persisted"]}

    builder = StateGraph(InvestigationState)
    builder.add_node("investigate", investigate)
    builder.add_node("wait_for_confirmation", wait_for_confirmation)
    builder.add_node("persist_proposal", persist_proposal)
    builder.add_edge(START, "investigate")
    builder.add_edge("investigate", "wait_for_confirmation")
    builder.add_edge("wait_for_confirmation", "persist_proposal")
    builder.add_edge("persist_proposal", END)
    return builder.compile()
