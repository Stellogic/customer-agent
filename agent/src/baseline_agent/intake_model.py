from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VisibleOrder:
    reference: str
    summary: str


@dataclass(frozen=True)
class IntakeModelInput:
    customer_message: str
    visible_orders: tuple[VisibleOrder, ...]
    current_order_reference: str | None = None
    current_issue_summary: str | None = None


@dataclass(frozen=True)
class IntakeUnderstanding:
    intent: str
    status: str
    candidate_order_reference: str | None
    issue_kind: str | None
    issue_summary: str | None
    assistant_message: str


class IntakeModel(Protocol):
    async def understand(self, model_input: IntakeModelInput) -> IntakeUnderstanding: ...


class FixedFakeIntakeModel:
    async def understand(self, model_input: IntakeModelInput) -> IntakeUnderstanding:
        message = model_input.customer_message.strip()
        if _is_confirmation(message) and model_input.current_order_reference:
            return IntakeUnderstanding(
                intent="CONFIRM",
                status="CONFIRMED",
                candidate_order_reference=model_input.current_order_reference,
                issue_kind="LOGISTICS_DELAY",
                issue_summary=model_input.current_issue_summary,
                assistant_message="已确认，客服工单正在独立处理。",
            )

        candidate = _candidate_order(message, model_input.visible_orders)
        logistics = any(
            term in message for term in ("物流", "快递", "包裹", "配送", "延迟", "没动")
        )
        if candidate is None:
            return IntakeUnderstanding(
                intent="UNDERSTANDING",
                status="NEEDS_CLARIFICATION",
                candidate_order_reference=None,
                issue_kind="LOGISTICS_DELAY" if logistics else None,
                issue_summary=message if logistics else None,
                assistant_message="你说的是不是某一笔订单的物流问题？请补充订单线索。",
            )
        if not logistics:
            return IntakeUnderstanding(
                intent="UNDERSTANDING",
                status="NEEDS_CLARIFICATION",
                candidate_order_reference=candidate.reference,
                issue_kind=None,
                issue_summary=None,
                assistant_message=(
                    f"你说的是不是订单 {candidate.reference} 的物流延迟问题？"
                    "也可以直接纠正我的理解。"
                ),
            )
        return IntakeUnderstanding(
            intent="UNDERSTANDING",
            status="READY_TO_CONFIRM",
            candidate_order_reference=candidate.reference,
            issue_kind="LOGISTICS_DELAY",
            issue_summary=_customer_issue_summary(message, candidate.reference),
            assistant_message=(
                f"我理解为订单 {candidate.reference} 的物流延迟问题。"
                "请确认是否正确，或直接告诉我需要修改的地方。"
            ),
        )


def _candidate_order(message: str, orders: tuple[VisibleOrder, ...]) -> VisibleOrder | None:
    mentioned = [order for order in orders if order.reference.lower() in message.lower()]
    if mentioned:
        longest_reference_length = max(len(order.reference) for order in mentioned)
        longest = [order for order in mentioned if len(order.reference) == longest_reference_length]
        if len(longest) == 1:
            return longest[0]
    if len(orders) == 1:
        return orders[0]
    return None


def _is_confirmation(message: str) -> bool:
    normalized = "".join(message.lower().split()).translate(str.maketrans("", "", "。！!，,"))
    return normalized in {
        "可以",
        "确认",
        "是的",
        "对",
        "没错",
        "就按这个处理",
        "可以就按这个处理",
        "确认提交",
    }


def _customer_issue_summary(message: str, order_reference: str) -> str:
    for prefix in (
        f"订单 {order_reference} 的物流延迟问题：",
        f"订单 {order_reference}：",
    ):
        if message.startswith(prefix):
            return message.removeprefix(prefix).strip()
    return message
