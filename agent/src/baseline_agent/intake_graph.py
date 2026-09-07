from __future__ import annotations

import os
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

from baseline_agent.core_validation_budget import CoreBudgetStopped
from baseline_agent.deepseek_intake_model import DeepSeekIntakeModel
from baseline_agent.deepseek_investigation_model import (
    InMemoryModelCallAuditSink,
    ModelCallAttemptRecord,
)
from baseline_agent.intake_model import IntakeIssue, IntakeModelInput, VisibleOrder
from baseline_agent.intake_model_runtime import configured_intake_model
from baseline_agent.model_call_evidence import model_call_evidence, serialize_model_attempt


class IntakeState(TypedDict, total=False):
    requested_by: str
    customer_message: str
    visible_orders: list[dict[str, str]]
    current_order_reference: str
    current_issue_summary: str
    current_issues: list[dict[str, str]]
    current_pending_issue_kinds: list[str]
    current_remaining_order_references: list[str]
    intake_understanding: dict[str, object]
    intake_call_evidence: dict[str, object]
    intake_failure: dict[str, str]
    model_mode: str


intake_model, intake_model_mode = configured_intake_model(os.environ)


async def understand_intake(state: IntakeState) -> IntakeState:
    if state.get("requested_by") != "spring":
        raise ValueError("intake graph accepts only Spring-owned requests")
    orders = tuple(
        VisibleOrder(order["reference"], order["summary"])
        for order in state.get("visible_orders", [])
    )
    audit = intake_model.audit_sink if isinstance(intake_model, DeepSeekIntakeModel) else None
    task_records = (
        audit.current_task_records() if isinstance(audit, InMemoryModelCallAuditSink) else []
    )
    offset = len(task_records)
    model_input = IntakeModelInput(
        customer_message=state["customer_message"],
        visible_orders=orders,
        current_order_reference=state.get("current_order_reference") or None,
        current_issue_summary=state.get("current_issue_summary") or None,
        current_issues=tuple(
            IntakeIssue(issue["kind"], issue["summary"])
            for issue in state.get("current_issues", [])
        ),
        current_pending_issue_kinds=tuple(state.get("current_pending_issue_kinds", [])),
        current_remaining_order_references=tuple(
            state.get("current_remaining_order_references", [])
        ),
    )
    try:
        result = await intake_model.understand(model_input)
    except CoreBudgetStopped as error:
        records = task_records[offset:]
        evidence = _intake_call_evidence(records)
        if not records:
            # 本地预算在发送前拒绝;这里明确知道没有供应商调用,不能把缺失 usage 当零。
            evidence.update(
                inputTokens=0, outputTokens=0, tokens=0, costMicros=0, usageComplete=True
            )
        evidence["failureClassification"] = str(error)
        return {
            "model_mode": intake_model_mode,
            "intake_failure": {"code": str(error)},
            "intake_call_evidence": evidence,
        }
    except (ValueError, KeyError, TypeError, httpx.HTTPError):
        records = task_records[offset:]
        failure = next(
            (record.failure_classification for record in records if record.failure_classification),
            None,
        )
        if failure is None:
            raise
        return {
            "model_mode": intake_model_mode,
            "intake_failure": {"code": failure.value},
            "intake_call_evidence": _intake_call_evidence(records),
        }
    completed: IntakeState = {
        "model_mode": intake_model_mode,
        "intake_understanding": {
            "intent": result.intent,
            "status": result.status,
            "candidate_order_reference": result.candidate_order_reference,
            "issues": [{"kind": issue.kind, "summary": issue.summary} for issue in result.issues],
            "pending_issue_kinds": list(result.pending_issue_kinds),
            "remaining_order_references": list(result.remaining_order_references),
            "assistant_message": result.assistant_message,
        },
    }
    if isinstance(audit, InMemoryModelCallAuditSink):
        completed["intake_call_evidence"] = _intake_call_evidence(task_records[offset:])
    return completed


def _intake_call_evidence(records: list[ModelCallAttemptRecord]) -> dict[str, object]:
    return model_call_evidence(
        [serialize_model_attempt(record) for record in records],
        schema_version="intake-call-evidence-v1",
    )


builder = StateGraph(IntakeState)
builder.add_node("understand_intake", understand_intake)
builder.add_edge(START, "understand_intake")
builder.add_edge("understand_intake", END)
graph = builder.compile()
