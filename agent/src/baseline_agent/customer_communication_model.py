from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

CUSTOMER_REPLY_SCHEMA_VERSION = "customer-reply-v1"


class CustomerReplyIntent(StrEnum):
    NO_COMPENSATION_RESOLUTION = "NO_COMPENSATION_RESOLUTION"
    COMPENSATION_REVIEW_PENDING = "COMPENSATION_REVIEW_PENDING"


class CustomerCommunicationFailureCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    MODEL_CALL_FAILED = "MODEL_CALL_FAILED"


class CustomerCommunicationFailure(Exception):
    def __init__(self, code: CustomerCommunicationFailureCode) -> None:
        self.code = code
        super().__init__("customer communication model could not produce a safe reply")


@dataclass(frozen=True)
class CustomerCommunicationInput:
    order_reference: str
    delay_seconds: int
    compensation_review_required: bool
    evidence_refs: tuple[str, ...]


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


class FixedFakeCustomerCommunicationModel:
    async def compose(self, model_input: CustomerCommunicationInput) -> CustomerReplyEnvelope:
        validate_customer_communication_input(model_input)
        if model_input.compensation_review_required:
            body = (
                f"订单 {model_input.order_reference} 的调查已完成，补偿建议正在等待人工审批；"
                "审批完成前不会执行补偿或退款。"
            )
            intent = CustomerReplyIntent.COMPENSATION_REVIEW_PENDING
        else:
            body = (
                f"经核验，订单 {model_input.order_reference} 的本次物流延迟不足 24 小时，"
                "当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。"
            )
            intent = CustomerReplyIntent.NO_COMPENSATION_RESOLUTION
        envelope = CustomerReplyEnvelope(
            schema_version=CUSTOMER_REPLY_SCHEMA_VERSION,
            body=body,
            intent=intent,
            evidence_refs=model_input.evidence_refs,
            escalation_required=False,
            referenced_order=model_input.order_reference,
        )
        validate_customer_reply_envelope(model_input, envelope)
        return envelope


def validate_customer_communication_input(model_input: CustomerCommunicationInput) -> None:
    expected_evidence = (
        f"order:{model_input.order_reference}",
        f"logistics:{model_input.order_reference}",
    )
    if (
        not model_input.order_reference
        or not isinstance(model_input.delay_seconds, int)
        or isinstance(model_input.delay_seconds, bool)
        or model_input.delay_seconds < 0
        or model_input.evidence_refs != expected_evidence
    ):
        raise CustomerCommunicationFailure(CustomerCommunicationFailureCode.INVALID_INPUT)


def validate_customer_reply_envelope(
    model_input: CustomerCommunicationInput, envelope: CustomerReplyEnvelope
) -> None:
    expected_intent = (
        CustomerReplyIntent.COMPENSATION_REVIEW_PENDING
        if model_input.compensation_review_required
        else CustomerReplyIntent.NO_COMPENSATION_RESOLUTION
    )
    if (
        not isinstance(envelope, CustomerReplyEnvelope)
        or envelope.schema_version != CUSTOMER_REPLY_SCHEMA_VERSION
        or not envelope.body
        or len(envelope.body) > 1_000
        or envelope.intent is not expected_intent
        or envelope.evidence_refs != model_input.evidence_refs
        or envelope.escalation_required is not False
        or envelope.referenced_order != model_input.order_reference
    ):
        raise CustomerCommunicationFailure(CustomerCommunicationFailureCode.INVALID_OUTPUT)
