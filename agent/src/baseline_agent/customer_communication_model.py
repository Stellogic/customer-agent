from collections.abc import Mapping
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
    async def compose(self, model_input: CustomerCommunicationInput) -> CustomerReplyEnvelope: ...


class CustomerCommunicationProvider(Protocol):
    async def generate(self, request: dict[str, object]) -> Mapping[str, object]: ...


class StructuredCustomerCommunicationModel:
    """Provider-neutral structured seam used with an offline programmable provider stub."""

    def __init__(self, provider: CustomerCommunicationProvider) -> None:
        self._provider = provider

    async def compose(self, model_input: CustomerCommunicationInput) -> CustomerReplyEnvelope:
        validate_customer_communication_input(model_input)
        try:
            raw = await self._provider.generate(_provider_request(model_input))
        except CustomerCommunicationFailure:
            raise
        except Exception:
            raise CustomerCommunicationFailure(
                CustomerCommunicationFailureCode.MODEL_CALL_FAILED
            ) from None
        envelope = _parse_provider_envelope(raw)
        validate_customer_reply_envelope(model_input, envelope)
        return envelope


class FixedFakeCustomerCommunicationModel:
    async def compose(self, model_input: CustomerCommunicationInput) -> CustomerReplyEnvelope:
        validate_customer_communication_input(model_input)
        if model_input.compensation_review_required is None:
            if "人工" in model_input.synthetic_customer_text:
                body = "为确保处理安全，此工单已转由客服继续调查。客服将在此工单中与您联系。"
                intent = CustomerReplyIntent.HUMAN_HANDOFF
                escalation_required = True
            else:
                body = "为继续调查，请提供当前工单所需的订单确认信息。"
                intent = CustomerReplyIntent.CLARIFICATION_REQUIRED
                escalation_required = False
        elif model_input.compensation_review_required:
            body = (
                f"订单 {model_input.order_reference} 的调查已完成，补偿建议正在等待人工审批；"
                "审批完成前不会执行补偿或退款。"
            )
            intent = CustomerReplyIntent.COMPENSATION_REVIEW_PENDING
            escalation_required = False
        else:
            body = (
                f"经核验，订单 {model_input.order_reference} 的本次物流延迟不足 24 小时，"
                "当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。"
            )
            intent = CustomerReplyIntent.NO_COMPENSATION_RESOLUTION
            escalation_required = False
        envelope = CustomerReplyEnvelope(
            schema_version=CUSTOMER_REPLY_SCHEMA_VERSION,
            body=body,
            intent=intent,
            evidence_refs=(
                ()
                if model_input.compensation_review_required is None
                else model_input.evidence_refs
            ),
            escalation_required=escalation_required,
            referenced_order=model_input.order_reference,
        )
        validate_customer_reply_envelope(model_input, envelope)
        return envelope


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
    conversation_valid = len(model_input.public_conversation) <= 20 and all(
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
    if model_input.compensation_review_required is None:
        valid_intent = envelope.intent in {
            CustomerReplyIntent.CLARIFICATION_REQUIRED,
            CustomerReplyIntent.HUMAN_HANDOFF,
        }
        expected_evidence: tuple[str, ...] = ()
        expected_escalation = envelope.intent is CustomerReplyIntent.HUMAN_HANDOFF
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
    ):
        raise CustomerCommunicationFailure(CustomerCommunicationFailureCode.INVALID_OUTPUT)


def _provider_request(model_input: CustomerCommunicationInput) -> dict[str, object]:
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


def _parse_provider_envelope(raw: Mapping[str, object]) -> CustomerReplyEnvelope:
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
