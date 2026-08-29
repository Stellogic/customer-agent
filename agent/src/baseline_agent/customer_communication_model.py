import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

CUSTOMER_REPLY_SCHEMA_VERSION = "customer-reply-v1"


class CustomerReplyIntent(StrEnum):
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    NO_COMPENSATION_RESOLUTION = "NO_COMPENSATION_RESOLUTION"
    COMPENSATION_REVIEW_PENDING = "COMPENSATION_REVIEW_PENDING"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"


class CustomerCommunicationFailureCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    MODEL_CALL_FAILED = "MODEL_CALL_FAILED"


class CustomerCommunicationFailure(Exception):
    def __init__(self, code: CustomerCommunicationFailureCode) -> None:
        self.code = code
        super().__init__("customer communication model could not produce a safe reply")


@dataclass(frozen=True)
class CustomerConversationMessage:
    author: str
    body: str


@dataclass(frozen=True)
class CustomerCommunicationInput:
    order_reference: str
    delay_seconds: int | None
    compensation_review_required: bool | None
    evidence_refs: tuple[str, ...]
    synthetic_customer_text: str = ""
    public_conversation: tuple[CustomerConversationMessage, ...] = ()


@dataclass(frozen=True)
class CustomerReplyEnvelope:
    schema_version: str
    body: str
    intent: CustomerReplyIntent
    evidence_refs: tuple[str, ...]
    escalation_required: bool
    referenced_order: str

    def as_request_value(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "body": self.body,
            "intent": self.intent.value,
            "evidenceRefs": list(self.evidence_refs),
            "escalationRequired": self.escalation_required,
            "referencedOrder": self.referenced_order,
        }


class CustomerCommunicationModel(Protocol):
    async def compose(
        self,
        model_input: CustomerCommunicationInput,
        on_body_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> CustomerReplyEnvelope: ...


class CustomerCommunicationProvider(Protocol):
    async def generate(self, request: dict[str, object]) -> Mapping[str, object]: ...


class StructuredCustomerCommunicationModel:
    """Provider-neutral structured seam used with an offline programmable provider stub."""

    def __init__(self, provider: CustomerCommunicationProvider) -> None:
        self._provider = provider

    async def compose(
        self,
        model_input: CustomerCommunicationInput,
        on_body_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> CustomerReplyEnvelope:
        validate_customer_communication_input(model_input)
        try:
            raw = await self._provider.generate(
                customer_communication_provider_request(model_input)
            )
        except CustomerCommunicationFailure:
            raise
        except Exception:
            raise CustomerCommunicationFailure(
                CustomerCommunicationFailureCode.MODEL_CALL_FAILED
            ) from None
        envelope = parse_customer_reply_envelope(raw)
        validate_customer_reply_envelope(model_input, envelope)
        if on_body_delta is not None:
            await on_body_delta(envelope.body)
        return envelope


class FixedFakeCustomerCommunicationModel:
    async def compose(
        self,
        model_input: CustomerCommunicationInput,
        on_body_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> CustomerReplyEnvelope:
        validate_customer_communication_input(model_input)
        if customer_requested_human(model_input):
            intent = CustomerReplyIntent.HUMAN_HANDOFF
            escalation_required = True
        elif model_input.compensation_review_required is None:
            intent = CustomerReplyIntent.CLARIFICATION_REQUIRED
            escalation_required = False
        elif model_input.compensation_review_required:
            intent = CustomerReplyIntent.COMPENSATION_REVIEW_PENDING
            escalation_required = False
        else:
            intent = CustomerReplyIntent.NO_COMPENSATION_RESOLUTION
            escalation_required = False
        body = default_customer_reply_body(model_input.order_reference, intent)
        envelope = CustomerReplyEnvelope(
            schema_version=CUSTOMER_REPLY_SCHEMA_VERSION,
            body=body,
            intent=intent,
            evidence_refs=(
                model_input.evidence_refs
                if intent is CustomerReplyIntent.HUMAN_HANDOFF
                else ()
                if model_input.compensation_review_required is None
                else model_input.evidence_refs
            ),
            escalation_required=escalation_required,
            referenced_order=model_input.order_reference,
        )
        validate_customer_reply_envelope(model_input, envelope)
        if on_body_delta is not None:
            await on_body_delta(envelope.body)
        return envelope


def authorized_customer_reply_bodies(
    order_reference: str, intent: CustomerReplyIntent
) -> tuple[str, ...]:
    if intent is CustomerReplyIntent.CLARIFICATION_REQUIRED:
        return ("为确认需要调查的订单，请回复订单确认码（A 或 B）。",)
    if intent is CustomerReplyIntent.HUMAN_HANDOFF:
        return ("已按您的要求转由人工客服继续处理。",)
    if intent is CustomerReplyIntent.COMPENSATION_REVIEW_PENDING:
        return (
            f"订单 {order_reference} 的调查已完成，补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
            f"我们已核对订单 {order_reference} 的物流记录。补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
            f"经核验，订单 {order_reference} 的物流存在延迟。补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
            f"经核验，订单 {order_reference} 的物流出现延迟。补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
            f"调查结果显示，订单 {order_reference} 的物流存在延迟。补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
            f"调查结果显示，订单 {order_reference} 的物流出现延迟。补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
        )
    return (
        f"经核验，订单 {order_reference} 的本次物流延迟不足 24 小时，当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。",
        f"经核验，订单 {order_reference} 的物流延迟不足 24 小时，当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。",
        f"调查结果显示，订单 {order_reference} 的物流延迟不足 24 小时，当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。",
        f"经核验，订单 {order_reference} 的物流延迟未达到 24 小时，当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。",
        f"调查结果显示，订单 {order_reference} 的物流延迟未达到 24 小时，当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。",
    )


def validate_customer_communication_input(model_input: CustomerCommunicationInput) -> None:
    facts_complete = (
        isinstance(model_input.delay_seconds, int)
        and not isinstance(model_input.delay_seconds, bool)
        and model_input.delay_seconds >= 0
        and isinstance(model_input.compensation_review_required, bool)
    )
    facts_absent = (
        model_input.delay_seconds is None
        and model_input.compensation_review_required is None
        and model_input.evidence_refs == ()
    )
    expected_evidence = (
        f"order:{model_input.order_reference}",
        f"logistics:{model_input.order_reference}",
    )
    conversation_valid = all(
        isinstance(message, CustomerConversationMessage)
        and message.author in {"CUSTOMER", "SUPPORT", "AGENT"}
        and bool(message.body.strip())
        and len(message.body) <= 2_000
        for message in model_input.public_conversation
    )
    if (
        not model_input.order_reference
        or len(model_input.order_reference) > 200
        or not isinstance(model_input.synthetic_customer_text, str)
        or len(model_input.synthetic_customer_text) > 4_000
        or not conversation_valid
        or not (facts_absent or (facts_complete and model_input.evidence_refs == expected_evidence))
    ):
        raise CustomerCommunicationFailure(CustomerCommunicationFailureCode.INVALID_INPUT)


def validate_customer_reply_envelope(
    model_input: CustomerCommunicationInput, envelope: CustomerReplyEnvelope
) -> None:
    if envelope.intent is CustomerReplyIntent.HUMAN_HANDOFF:
        valid_intent = customer_requested_human(model_input)
        expected_evidence = model_input.evidence_refs
        expected_escalation = True
    elif model_input.compensation_review_required is None:
        valid_intent = envelope.intent in {
            CustomerReplyIntent.CLARIFICATION_REQUIRED,
        }
        expected_evidence: tuple[str, ...] = ()
        expected_escalation = False
    else:
        expected_intent = (
            CustomerReplyIntent.COMPENSATION_REVIEW_PENDING
            if model_input.compensation_review_required
            else CustomerReplyIntent.NO_COMPENSATION_RESOLUTION
        )
        valid_intent = envelope.intent is expected_intent
        expected_evidence = model_input.evidence_refs
        expected_escalation = False
    if (
        not isinstance(envelope, CustomerReplyEnvelope)
        or envelope.schema_version != CUSTOMER_REPLY_SCHEMA_VERSION
        or not envelope.body
        or len(envelope.body) > 1_000
        or not valid_intent
        or envelope.evidence_refs != expected_evidence
        or envelope.escalation_required is not expected_escalation
        or envelope.referenced_order != model_input.order_reference
        or re.fullmatch(
            authorized_customer_reply_pattern(model_input.order_reference, envelope.intent),
            envelope.body,
        )
        is None
    ):
        raise CustomerCommunicationFailure(CustomerCommunicationFailureCode.INVALID_OUTPUT)


def customer_communication_provider_request(
    model_input: CustomerCommunicationInput,
) -> dict[str, object]:
    return {
        "schemaVersion": "customer-communication-input-v1",
        "untrustedCustomerData": {
            "syntheticCustomerText": model_input.synthetic_customer_text,
            "publicConversation": [
                {"author": message.author, "body": message.body}
                for message in model_input.public_conversation
            ],
        },
        "authorizedInvestigation": {
            "orderReference": model_input.order_reference,
            "delaySeconds": model_input.delay_seconds,
            "compensationReviewRequired": model_input.compensation_review_required,
            "evidenceRefs": list(model_input.evidence_refs),
        },
    }


def customer_requested_human(model_input: CustomerCommunicationInput) -> bool:
    customer_text = "\n".join(
        [model_input.synthetic_customer_text]
        + [
            message.body
            for message in model_input.public_conversation
            if message.author == "CUSTOMER"
        ]
    )
    return "人工" in customer_text


def parse_customer_reply_envelope(raw: Mapping[str, object]) -> CustomerReplyEnvelope:
    if not isinstance(raw, Mapping) or set(raw) != {
        "schemaVersion",
        "body",
        "intent",
        "evidenceRefs",
        "escalationRequired",
        "referencedOrder",
    }:
        raise CustomerCommunicationFailure(CustomerCommunicationFailureCode.INVALID_OUTPUT)
    evidence = raw["evidenceRefs"]
    if (
        not isinstance(raw["schemaVersion"], str)
        or not isinstance(raw["body"], str)
        or not isinstance(raw["intent"], str)
        or not isinstance(evidence, list)
        or not all(isinstance(item, str) for item in evidence)
        or type(raw["escalationRequired"]) is not bool
        or not isinstance(raw["referencedOrder"], str)
    ):
        raise CustomerCommunicationFailure(CustomerCommunicationFailureCode.INVALID_OUTPUT)
    try:
        intent = CustomerReplyIntent(raw["intent"])
    except ValueError:
        raise CustomerCommunicationFailure(
            CustomerCommunicationFailureCode.INVALID_OUTPUT
        ) from None
    return CustomerReplyEnvelope(
        schema_version=raw["schemaVersion"],
        body=raw["body"],
        intent=intent,
        evidence_refs=tuple(evidence),
        escalation_required=raw["escalationRequired"],
        referenced_order=raw["referencedOrder"],
    )


def default_customer_reply_body(order_reference: str, intent: CustomerReplyIntent) -> str:
    if intent is CustomerReplyIntent.CLARIFICATION_REQUIRED:
        return "为确认需要调查的订单，请回复订单确认码（A 或 B）。"
    if intent is CustomerReplyIntent.HUMAN_HANDOFF:
        return "已按您的要求转由人工客服继续处理。"
    if intent is CustomerReplyIntent.COMPENSATION_REVIEW_PENDING:
        return (
            f"订单 {order_reference} 的调查已完成，补偿建议正在等待人工审批；"
            "审批完成前不会执行补偿或退款。"
        )
    return (
        f"经核验，订单 {order_reference} 的本次物流延迟不足 24 小时，"
        "当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。"
    )


def authorized_customer_reply_pattern(order_reference: str, intent: CustomerReplyIntent) -> str:
    return (
        "(?:"
        + "|".join(
            re.escape(body) for body in authorized_customer_reply_bodies(order_reference, intent)
        )
        + ")"
    )
