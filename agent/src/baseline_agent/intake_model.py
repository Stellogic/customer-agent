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
    current_issues: tuple[IntakeIssue, ...] = ()
    current_pending_issue_kinds: tuple[str, ...] = ()
    current_remaining_order_references: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntakeIssue:
    kind: str
    summary: str


@dataclass(frozen=True)
class IntakeUnderstanding:
    intent: str
    status: str
    candidate_order_reference: str | None
    issues: tuple[IntakeIssue, ...]
    pending_issue_kinds: tuple[str, ...]
    assistant_message: str
    remaining_order_references: tuple[str, ...] = ()

    @property
    def issue_kind(self) -> str | None:
        return self.issues[0].kind if len(self.issues) == 1 else None

    @property
    def issue_summary(self) -> str | None:
        return self.issues[0].summary if len(self.issues) == 1 else None


class IntakeModel(Protocol):
    async def understand(self, model_input: IntakeModelInput) -> IntakeUnderstanding: ...


class FixedFakeIntakeModel:
    async def understand(self, model_input: IntakeModelInput) -> IntakeUnderstanding:
        message = model_input.customer_message.strip()
        current_issues = model_input.current_issues
        pending_issue_kinds = list(model_input.current_pending_issue_kinds)
        if not current_issues and model_input.current_issue_summary:
            current_issues = (IntakeIssue("LOGISTICS_DELAY", model_input.current_issue_summary),)
        if (
            _is_confirmation(message)
            and model_input.current_order_reference
            and current_issues
            and not pending_issue_kinds
        ):
            return IntakeUnderstanding(
                intent="CONFIRM",
                status="CONFIRMED",
                candidate_order_reference=model_input.current_order_reference,
                issues=current_issues,
                pending_issue_kinds=(),
                assistant_message="已确认，客服工单正在独立处理。",
                remaining_order_references=model_input.current_remaining_order_references,
            )

        candidate = _candidate_order(message, model_input.visible_orders)
        if candidate is None and model_input.current_order_reference:
            candidate = next(
                (
                    order
                    for order in model_input.visible_orders
                    if order.reference == model_input.current_order_reference
                ),
                None,
            )
        remaining_order_references = (
            model_input.current_remaining_order_references
            if model_input.current_order_reference
            else tuple(
                order.reference
                for order in _mentioned_orders(message, model_input.visible_orders)
                if candidate is None or order.reference != candidate.reference
            )
        )
        scoped_message = _message_for_candidate(message, candidate, model_input.visible_orders)
        issues = _merge_issues(current_issues, _recognized_issues(scoped_message))
        if pending_issue_kinds:
            pending_kind = pending_issue_kinds[0]
            if _confirms_pending_issue(pending_kind, message):
                issues = _merge_issues(
                    issues, (IntakeIssue(pending_kind, _issue_summary(pending_kind)),)
                )
                pending_issue_kinds.pop(0)
            elif _denies_pending_issue(pending_kind, message):
                issues = tuple(issue for issue in issues if issue.kind != pending_kind)
                pending_issue_kinds.pop(0)
            else:
                return IntakeUnderstanding(
                    intent="UNDERSTANDING",
                    status="NEEDS_CLARIFICATION",
                    candidate_order_reference=candidate.reference if candidate else None,
                    issues=issues,
                    pending_issue_kinds=tuple(pending_issue_kinds),
                    assistant_message="请先确认是否确实发生了两次扣款。",
                    remaining_order_references=remaining_order_references,
                )
        uncertain_issue_kinds = _uncertain_issue_kinds(scoped_message)
        if candidate is None:
            return IntakeUnderstanding(
                intent="UNDERSTANDING",
                status="NEEDS_CLARIFICATION",
                candidate_order_reference=None,
                issues=issues,
                pending_issue_kinds=tuple(pending_issue_kinds),
                assistant_message="你说的是不是某一笔订单的物流问题？请补充订单线索。",
                remaining_order_references=remaining_order_references,
            )
        if uncertain_issue_kinds:
            for kind in uncertain_issue_kinds:
                if kind not in pending_issue_kinds:
                    pending_issue_kinds.append(kind)
            return IntakeUnderstanding(
                intent="UNDERSTANDING",
                status="NEEDS_CLARIFICATION",
                candidate_order_reference=candidate.reference,
                issues=tuple(issue for issue in issues if issue.kind not in pending_issue_kinds),
                pending_issue_kinds=tuple(pending_issue_kinds),
                assistant_message="你提到疑似重复扣款，请确认是否确实发生了两次扣款。",
                remaining_order_references=remaining_order_references,
            )
        if pending_issue_kinds:
            return IntakeUnderstanding(
                intent="UNDERSTANDING",
                status="NEEDS_CLARIFICATION",
                candidate_order_reference=candidate.reference,
                issues=issues,
                pending_issue_kinds=tuple(pending_issue_kinds),
                assistant_message="还有一个不确定的问题需要逐项确认。",
                remaining_order_references=remaining_order_references,
            )
        if not issues:
            return IntakeUnderstanding(
                intent="UNDERSTANDING",
                status="NEEDS_CLARIFICATION",
                candidate_order_reference=candidate.reference,
                issues=(),
                pending_issue_kinds=(),
                assistant_message=f"你说的是不是订单 {candidate.reference} 的物流或支付问题？也可以直接纠正我的理解。",
                remaining_order_references=remaining_order_references,
            )
        if len(issues) == 1 and issues[0].kind == "LOGISTICS_DELAY":
            issues = (
                IntakeIssue(
                    "LOGISTICS_DELAY",
                    _customer_issue_summary(scoped_message, candidate.reference),
                ),
            )
        return IntakeUnderstanding(
            intent="UNDERSTANDING",
            status="READY_TO_CONFIRM",
            candidate_order_reference=candidate.reference,
            issues=issues,
            pending_issue_kinds=(),
            assistant_message=(
                f"我理解为订单 {candidate.reference} 有 {len(issues)} 个独立问题。"
                f"请确认；确认后将创建 {len(issues)} 张工单，也可以直接纠正我的理解。"
            ),
            remaining_order_references=remaining_order_references,
        )


def _recognized_issues(message: str) -> tuple[IntakeIssue, ...]:
    issues: list[IntakeIssue] = []
    if any(term in message for term in ("未收到", "没收到", "丢件")):
        issues.append(IntakeIssue("PACKAGE_NOT_RECEIVED", "包裹未收到"))
    elif any(term in message for term in ("物流", "快递", "包裹", "配送", "延迟", "没动")):
        issues.append(IntakeIssue("LOGISTICS_DELAY", "物流延迟"))
    if not _denies_duplicate_charge(message) and any(
        term in message for term in ("确实重复扣款", "重复扣款", "扣了两次")
    ):
        issues.append(IntakeIssue("DUPLICATE_CHARGE", "重复扣款"))
    return tuple(issues)


def _merge_issues(
    current: tuple[IntakeIssue, ...], recognized: tuple[IntakeIssue, ...]
) -> tuple[IntakeIssue, ...]:
    merged = list(current)
    known_kinds = {issue.kind for issue in current}
    for issue in recognized:
        if issue.kind not in known_kinds:
            merged.append(issue)
            known_kinds.add(issue.kind)
    return tuple(merged)


def _candidate_order(message: str, orders: tuple[VisibleOrder, ...]) -> VisibleOrder | None:
    mentioned = _mentioned_orders(message, orders)
    if mentioned:
        return mentioned[0]
    if len(orders) == 1:
        return orders[0]
    return None


def _mentioned_orders(message: str, orders: tuple[VisibleOrder, ...]) -> tuple[VisibleOrder, ...]:
    lowered = message.lower()
    mentioned = [
        (lowered.index(order.reference.lower()), -len(order.reference), order)
        for order in orders
        if order.reference.lower() in lowered
    ]
    ordered = sorted(mentioned, key=lambda value: (value[0], value[1]))
    selected: list[VisibleOrder] = []
    positions: set[int] = set()
    for position, _, order in ordered:
        if position not in positions:
            selected.append(order)
            positions.add(position)
    return tuple(selected)


def _message_for_candidate(
    message: str, candidate: VisibleOrder | None, orders: tuple[VisibleOrder, ...]
) -> str:
    if candidate is None:
        return message
    mentioned = _mentioned_orders(message, orders)
    if len(mentioned) <= 1:
        return message
    lowered = message.lower()
    start = lowered.index(candidate.reference.lower())
    later_positions = [
        lowered.index(order.reference.lower())
        for order in mentioned
        if lowered.index(order.reference.lower()) > start
    ]
    end = min(later_positions) if later_positions else len(message)
    return message[start:end].strip(" ，,；;。")


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


def _confirms_pending_issue(kind: str, message: str) -> bool:
    if _denies_pending_issue(kind, message):
        return False
    kind_terms = {
        "DUPLICATE_CHARGE": ("确实重复扣款", "扣了两次"),
        "PACKAGE_NOT_RECEIVED": ("确实没收到", "至今没收到", "仍未收到"),
        "LOGISTICS_DELAY": ("确实延迟", "仍然没动", "没有进展"),
    }
    return _is_confirmation(message) or any(term in message for term in kind_terms[kind])


def _denies_pending_issue(kind: str, message: str) -> bool:
    kind_terms = {
        "DUPLICATE_CHARGE": ("没有重复扣款", "并非重复扣款", "不是重复扣款", "只扣了一次"),
        "PACKAGE_NOT_RECEIVED": ("已经收到", "后来收到了", "包裹已到"),
        "LOGISTICS_DELAY": ("没有延迟", "物流正常", "已经恢复"),
    }
    normalized = "".join(message.split())
    return any(term in normalized for term in kind_terms[kind])


def _denies_duplicate_charge(message: str) -> bool:
    return _denies_pending_issue("DUPLICATE_CHARGE", message)


def _uncertain_issue_kinds(message: str) -> tuple[str, ...]:
    uncertain: list[str] = []
    if any(term in message for term in ("好像没收到", "可能没收到", "疑似丢件")):
        uncertain.append("PACKAGE_NOT_RECEIVED")
    if any(term in message for term in ("可能延迟", "好像延迟", "疑似延迟")):
        uncertain.append("LOGISTICS_DELAY")
    if any(term in message for term in ("疑似重复扣款", "可能重复扣款", "好像重复扣款")):
        uncertain.append("DUPLICATE_CHARGE")
    return tuple(uncertain)


def _issue_summary(kind: str) -> str:
    return {
        "PACKAGE_NOT_RECEIVED": "包裹未收到",
        "LOGISTICS_DELAY": "物流延迟",
        "DUPLICATE_CHARGE": "重复扣款",
    }[kind]


def _customer_issue_summary(message: str, order_reference: str) -> str:
    for prefix in (
        f"订单 {order_reference} 的物流延迟问题：",
        f"订单 {order_reference}：",
    ):
        if message.startswith(prefix):
            return message.removeprefix(prefix).strip()
    return message
