import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from baseline_agent.customer_knowledge_answer import (
    CustomerKnowledgeAnswer,
    parse_customer_knowledge_answer,
    validate_customer_knowledge_citations,
)
from baseline_agent.knowledge_retrieval import KnowledgeRetrievalResult

CUSTOMER_REPLY_SCHEMA_VERSION = "customer-reply-v1"
CUSTOMER_KNOWLEDGE_REPLY_SCHEMA_VERSION = "customer-reply-v2"


class CustomerReplyIntent(StrEnum):
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    NO_COMPENSATION_RESOLUTION = "NO_COMPENSATION_RESOLUTION"
    COMPENSATION_REVIEW_PENDING = "COMPENSATION_REVIEW_PENDING"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"


class CustomerCommunicationFailureCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    MODEL_CALL_FAILED = "MODEL_CALL_FAILED"
    PUBLICATION_FAILED = "PUBLICATION_FAILED"


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
    risk_scenario: str | None = None
    logistics_status: str | None = None
    knowledge: KnowledgeRetrievalResult | None = None


@dataclass(frozen=True)
class CustomerReplyEnvelope:
    schema_version: str
    body: str
    intent: CustomerReplyIntent
    evidence_refs: tuple[str, ...]
    escalation_required: bool
    referenced_order: str
    knowledge: CustomerKnowledgeAnswer | None = None

    def as_request_value(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "body": self.body,
            "intent": self.intent.value,
            "evidenceRefs": list(self.evidence_refs),
            "escalationRequired": self.escalation_required,
            "referencedOrder": self.referenced_order,
            **(
                {"knowledge": self.knowledge.as_request_value()}
                if self.knowledge is not None
                else {}
            ),
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
        f"经核验，订单 {order_reference} 的本次物流延迟不足 24 小时，当前不符合补偿条件。本次核验结论已给出，后续处理以页面状态为准；如仍需帮助，请继续回复。",
        f"经核验，订单 {order_reference} 的物流延迟不足 24 小时，当前不符合补偿条件。本次核验结论已给出，后续处理以页面状态为准；如仍需帮助，请继续回复。",
        f"调查结果显示，订单 {order_reference} 的物流延迟不足 24 小时，当前不符合补偿条件。本次核验结论已给出，后续处理以页面状态为准；如仍需帮助，请继续回复。",
        f"经核验，订单 {order_reference} 的物流延迟未达到 24 小时，当前不符合补偿条件。本次核验结论已给出，后续处理以页面状态为准；如仍需帮助，请继续回复。",
        f"调查结果显示，订单 {order_reference} 的物流延迟未达到 24 小时，当前不符合补偿条件。本次核验结论已给出，后续处理以页面状态为准；如仍需帮助，请继续回复。",
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
        and len(message.body) <= (3_000 if message.author == "AGENT" else 2_000)
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


_MONEY_PATTERN = re.compile(
    r"(?:[¥￥$]|USD|CNY|RMB)\s*(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟萬]+)"
    r"|(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟萬]+)\s*"
    r"(?:元|块钱|美元|人民币|USD|CNY|RMB)",
    re.IGNORECASE,
)
_RESPONSE_TIME_PROMISE_PATTERN = re.compile(
    r"(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟萬]+)\s*"
    r"(?:秒|分钟|小时|天|工作日)(?:之内|以内|内).{0,8}(?:回复|联系|处理|解决)"
)
_ORDER_REFERENCE_PATTERN = re.compile(r"ORDER-[A-Z0-9-]+", re.IGNORECASE)
_SENSITIVE_LEAK_PATTERN = re.compile(
    r"(系统提示词|prompt|reasoning|checkpoint|thread_id|api[_\s-]?key|bearer\s+[a-z0-9._-]+)",
    re.IGNORECASE,
)
_PERSON_NAME_CLAIM_PATTERN = re.compile(r"(?:由|被)\s*[\u4e00-\u9fff]{2,4}\s*签收")
_PREMATURE_TICKET_STATUS_PATTERN = re.compile(
    r"工单(?:已经|已)(?:自动)?(?:解决|关闭|结案)|已自动(?:解决|关闭|结案)|关闭等待期"
    r"|(?:五|5)\s*分钟(?:后|内).{0,8}(?:解决|关闭|结案)"
)
_DIRECT_COMPENSATION_PROMISE_PATTERN = re.compile(
    r"(?<!不)(?:已|已经|将|会|承诺|同意)(?:为您)?(?:办理|执行|发放)?(?:补偿|退款)"
    r"|可以获得(?:补偿|退款)|(?:补偿|退款)(?:已完成|将执行|已发放)"
)


def is_authorized_body_prefix(body: str, order_reference: str, *, complete: bool) -> bool:
    return customer_reply_body_policy_violation(body, order_reference, complete=complete) is None


def customer_reply_body_policy_violation(
    body: str, order_reference: str, *, complete: bool
) -> str | None:
    """Return a fixed body-policy code without exposing the rejected body."""
    if not body or not order_reference or len(body) > 1_000:
        return "REQUIRED_OR_LENGTH"
    if _MONEY_PATTERN.search(body) is not None:
        return "MONEY"
    if _RESPONSE_TIME_PROMISE_PATTERN.search(body) is not None:
        return "RESPONSE_TIME_PROMISE"
    if _SENSITIVE_LEAK_PATTERN.search(body) is not None:
        return "SENSITIVE_LEAK"
    if _PERSON_NAME_CLAIM_PATTERN.search(body) is not None:
        return "PERSON_NAME_CLAIM"
    if _PREMATURE_TICKET_STATUS_PATTERN.search(body) is not None:
        return "PREMATURE_TICKET_STATUS"
    for match in _ORDER_REFERENCE_PATTERN.finditer(body):
        if match.group(0).upper() != order_reference.upper():
            if (
                not complete
                and match.end() == len(body)
                and order_reference.upper().startswith(match.group(0).upper())
            ):
                continue
            return "ORDER_REFERENCE_SCOPE"
    if complete:
        upper_body = body.upper()
        upper_order = order_reference.upper()
        for size in range(3, len(upper_order)):
            if upper_body.endswith(upper_order[:size]):
                start = len(upper_body) - size
                if start == 0 or not upper_body[start - 1].isalnum():
                    return "ORDER_REFERENCE_SCOPE"
        if not _has_only_allowed_compensation_language(
            body, _infer_intent_from_compensation_language(body)
        ):
            return "COMPENSATION_LANGUAGE"
    return None


def validate_customer_reply_envelope(
    model_input: CustomerCommunicationInput, envelope: CustomerReplyEnvelope
) -> None:
    if customer_reply_policy_violation(model_input, envelope) is not None:
        raise CustomerCommunicationFailure(CustomerCommunicationFailureCode.INVALID_OUTPUT)


def customer_reply_policy_violation(
    model_input: CustomerCommunicationInput, envelope: CustomerReplyEnvelope
) -> tuple[str, str] | None:
    """Return a bounded policy code and JSON path without exposing reply values."""
    expected_schema = (
        CUSTOMER_KNOWLEDGE_REPLY_SCHEMA_VERSION
        if model_input.knowledge is not None
        else CUSTOMER_REPLY_SCHEMA_VERSION
    )
    if (model_input.knowledge is None) != (envelope.knowledge is None):
        return ("KNOWLEDGE_PRESENCE", "$.knowledge")
    if model_input.knowledge is not None and envelope.knowledge is not None:
        try:
            validate_customer_knowledge_citations(envelope.knowledge, model_input.knowledge)
        except ValueError:
            return ("KNOWLEDGE_CITATIONS", "$.knowledge.citations")
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
    if not isinstance(envelope, CustomerReplyEnvelope):
        return ("ENVELOPE_TYPE", "$")
    if envelope.schema_version != expected_schema:
        return ("SCHEMA_VERSION", "$.schemaVersion")
    if not envelope.body:
        return ("BODY_REQUIRED", "$.body")
    if len(envelope.body) > 1_000:
        return ("BODY_LENGTH", "$.body")
    if not valid_intent:
        return ("INTENT", "$.intent")
    if envelope.evidence_refs != expected_evidence:
        return ("EVIDENCE_REFS", "$.evidenceRefs")
    if envelope.escalation_required is not expected_escalation:
        return ("ESCALATION", "$.escalationRequired")
    if envelope.referenced_order != model_input.order_reference:
        return ("REFERENCED_ORDER", "$.referencedOrder")
    if envelope.intent in {
        CustomerReplyIntent.CLARIFICATION_REQUIRED,
        CustomerReplyIntent.HUMAN_HANDOFF,
    }:
        # Keep clarification / handoff bodies on the frozen safe templates.
        if (
            re.fullmatch(
                authorized_customer_reply_pattern(model_input.order_reference, envelope.intent),
                envelope.body,
            )
            is None
        ):
            return ("BODY_TEMPLATE", "$.body")
        return None
    body_violation = customer_reply_body_policy_violation(
        envelope.body, model_input.order_reference, complete=True
    )
    if body_violation is not None:
        return (f"BODY_{body_violation}", "$.body")
    if not _has_grounded_investigation_narrative(model_input, envelope.body):
        return ("GROUNDED_NARRATIVE", "$.body")
    return None


def _infer_intent_from_compensation_language(body: str) -> CustomerReplyIntent:
    if "补偿建议正在等待人工审批" in body:
        return CustomerReplyIntent.COMPENSATION_REVIEW_PENDING
    return CustomerReplyIntent.NO_COMPENSATION_RESOLUTION


def _has_only_allowed_compensation_language(body: str, intent: CustomerReplyIntent) -> bool:
    remaining = body
    if intent is CustomerReplyIntent.COMPENSATION_REVIEW_PENDING:
        pending = "补偿建议正在等待人工审批"
        no_execution = "审批完成前不会执行补偿或退款"
        if pending not in remaining or no_execution not in remaining:
            return False
        remaining = remaining.replace(pending, "").replace(no_execution, "")
        return "补偿" not in remaining and "退款" not in remaining
    if intent is CustomerReplyIntent.NO_COMPENSATION_RESOLUTION:
        # Intent and Spring facts carry the decision. Keep natural denial wording while
        # rejecting concrete compensation/refund actions and positive promises.
        return _DIRECT_COMPENSATION_PROMISE_PATTERN.search(remaining) is None
    return False


def _has_grounded_investigation_narrative(
    model_input: CustomerCommunicationInput, body: str
) -> bool:
    if _PERSON_NAME_CLAIM_PATTERN.search(body) is not None:
        return False
    if model_input.delay_seconds is not None:
        claimed_hours = [int(match.group(1)) for match in re.finditer(r"(\d+)\s*小时", body)]
        authority_hours = model_input.delay_seconds // 3600
        for hours in claimed_hours:
            matches_authority = hours == authority_hours
            mentions_threshold = authority_hours < 24 and hours == 24
            if not matches_authority and not mentions_threshold:
                return False
    return True


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
        **(
            {
                "untrustedKnowledge": [
                    {
                        "articleId": source.article_id,
                        "version": source.version,
                        "chunkId": source.chunk_id,
                        "snippet": source.snippet,
                    }
                    for source in model_input.knowledge.sources
                ],
            }
            if model_input.knowledge is not None
            else {}
        ),
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
    if not isinstance(raw, Mapping):
        raise CustomerCommunicationFailure(CustomerCommunicationFailureCode.INVALID_OUTPUT)
    expected = {
        "schemaVersion",
        "body",
        "intent",
        "evidenceRefs",
        "escalationRequired",
        "referencedOrder",
    }
    knowledge = None
    if raw.get("schemaVersion") == CUSTOMER_KNOWLEDGE_REPLY_SCHEMA_VERSION:
        expected.add("knowledge")
        try:
            knowledge = parse_customer_knowledge_answer(raw.get("knowledge"))
        except (ValueError, TypeError):
            raise CustomerCommunicationFailure(
                CustomerCommunicationFailureCode.INVALID_OUTPUT
            ) from None
    if set(raw) != expected:
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
        knowledge=knowledge,
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
        "当前不符合补偿条件。本次核验结论已给出，后续处理以页面状态为准；如仍需帮助，请继续回复。"
    )


def authorized_customer_reply_pattern(order_reference: str, intent: CustomerReplyIntent) -> str:
    return (
        "(?:"
        + "|".join(
            re.escape(body) for body in authorized_customer_reply_bodies(order_reference, intent)
        )
        + ")"
    )
