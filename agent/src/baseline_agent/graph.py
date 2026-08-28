import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypedDict, cast

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from baseline_agent.customer_communication_model import (
    CustomerCommunicationInput,
    CustomerCommunicationModel,
    CustomerConversationMessage,
    CustomerReplyIntent,
    validate_customer_reply_envelope,
)
from baseline_agent.customer_communication_model_runtime import (
    configured_customer_communication_model,
)
from baseline_agent.deepseek_customer_communication_model import (
    DeepSeekResponsesCustomerCommunicationModel,
)
from baseline_agent.deepseek_investigation_model import (
    DEEPSEEK_FLASH_MODEL,
    INVESTIGATION_JUDGMENT_PROMPT_VERSION,
    INVESTIGATION_JUDGMENT_SCHEMA_VERSION,
    DeepSeekResponsesInvestigationModel,
    InMemoryModelCallAuditSink,
    estimate_flash_cost_micros,
)
from baseline_agent.investigation_action_loop import (
    CAPABILITY_PARAMETER_NAMES,
    ActionBudget,
    ActionDecision,
    ActionLoop,
    ActionLoopContinuation,
    ActionLoopFailure,
    ActionLoopFailureCode,
    ActionLoopResult,
    ActionModelCallRecord,
    ActionRecord,
    InvestigationAction,
    InvestigationCapability,
    TerminalAction,
)
from baseline_agent.investigation_action_model_runtime import (
    configured_investigation_action_model,
)
from baseline_agent.investigation_model import (
    FixedFakeInvestigationModel,
    InvestigationJudgment,
    InvestigationJudgmentInput,
    InvestigationJudgmentModel,
    InvestigationReasonCode,
)
from baseline_agent.investigation_model_runtime import configured_investigation_model
from baseline_agent.shadow_investigation import (
    ShadowCandidate,
    compare_shadow_judgment,
    configured_shadow_candidate,
    failed_shadow_comparison,
    shadow_mode_enabled,
)


class BaselineState(TypedDict, total=False):
    requested_by: str
    spring_probe: dict[str, str]
    ticket_id: str
    generation_id: str
    issue_kind: str
    sibling_ticket_summary: dict[str, object]
    facts: dict
    conclusion: dict
    customer_reply: dict[str, object]
    clarification: dict
    clarification_answer: dict
    model_mode: str
    shadow_comparison: dict[str, str]
    handoff: dict
    investigation_actions: list[dict[str, object]]
    investigation_run_evidence: dict[str, object]
    investigation_judgment_evidence: dict[str, object]
    customer_communication_evidence: dict[str, object]
    investigation_progress: dict[str, object] | None


class CustomerCommunicationContextMessage(TypedDict):
    author: str
    body: str


class CustomerCommunicationContextValue(TypedDict):
    schemaVersion: str
    syntheticCustomerText: str
    publicConversation: list[CustomerCommunicationContextMessage]


REQUIRED_FACT_FIELDS = {
    "matchStatus",
    "orderReference",
    "delayHours",
    "delaySeconds",
    "paid",
    "cancelled",
    "fullyRefunded",
    "existingCompensation",
    "pendingActionCount",
    "policyVersion",
    "evidenceRefs",
}

_configured_investigation_model = configured_investigation_model(os.environ)
investigation_judgment_model: InvestigationJudgmentModel = _configured_investigation_model.model
investigation_model_mode = _configured_investigation_model.mode
_configured_action_model = configured_investigation_action_model(os.environ)
investigation_action_model = _configured_action_model.model
investigation_action_model_mode = _configured_action_model.mode
_configured_customer_communication_model = configured_customer_communication_model(os.environ)
customer_communication_model: CustomerCommunicationModel = (
    _configured_customer_communication_model.model
)
customer_communication_model_mode = _configured_customer_communication_model.mode
shadow_candidate_factory: Callable[[], ShadowCandidate | None] = configured_shadow_candidate


@dataclass(frozen=True)
class CapabilityField:
    name: str
    type: str


@dataclass(frozen=True)
class CapabilityContract:
    parameters: tuple[CapabilityField, ...]
    result_fields: tuple[CapabilityField, ...]


STRING = "STRING"
INTEGER = "INTEGER"
BOOLEAN = "BOOLEAN"
STRING_LIST = "STRING_LIST"


def _capability_parameters(
    capability: InvestigationCapability,
) -> tuple[CapabilityField, ...]:
    return tuple(CapabilityField(name, STRING) for name in CAPABILITY_PARAMETER_NAMES[capability])


CAPABILITY_CONTRACTS = {
    InvestigationCapability.CONFIRM_ORDER: CapabilityContract(
        _capability_parameters(InvestigationCapability.CONFIRM_ORDER),
        (
            CapabilityField("capability", STRING),
            CapabilityField("matchStatus", STRING),
            CapabilityField("orderReference", STRING),
            CapabilityField("evidenceRefs", STRING_LIST),
        ),
    ),
    InvestigationCapability.READ_LOGISTICS: CapabilityContract(
        _capability_parameters(InvestigationCapability.READ_LOGISTICS),
        (
            CapabilityField("capability", STRING),
            CapabilityField("delayHours", INTEGER),
            CapabilityField("delaySeconds", INTEGER),
            CapabilityField("evidenceRefs", STRING_LIST),
        ),
    ),
    InvestigationCapability.READ_PAYMENT_AND_REFUNDS: CapabilityContract(
        _capability_parameters(InvestigationCapability.READ_PAYMENT_AND_REFUNDS),
        (
            CapabilityField("capability", STRING),
            CapabilityField("paid", BOOLEAN),
            CapabilityField("cancelled", BOOLEAN),
            CapabilityField("fullyRefunded", BOOLEAN),
            CapabilityField("evidenceRefs", STRING_LIST),
        ),
    ),
    InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS: CapabilityContract(
        _capability_parameters(InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS),
        (
            CapabilityField("capability", STRING),
            CapabilityField("existingCompensation", BOOLEAN),
            CapabilityField("pendingActionCount", INTEGER),
            CapabilityField("evidenceRefs", STRING_LIST),
        ),
    ),
    InvestigationCapability.READ_APPLICABLE_POLICY: CapabilityContract(
        _capability_parameters(InvestigationCapability.READ_APPLICABLE_POLICY),
        (
            CapabilityField("capability", STRING),
            CapabilityField("policyVersion", STRING),
            CapabilityField("evidenceRefs", STRING_LIST),
        ),
    ),
}


async def probe_spring(state: BaselineState) -> BaselineState:
    if state.get("requested_by") != "spring":
        raise ValueError("baseline graph accepts only Spring-owned probes")
    headers = {"Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}"}
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.get(
            f"{os.environ['SPRING_INTERNAL_URL']}/internal/capabilities/agent/probe",
            headers=headers,
        )
        response.raise_for_status()
        return {"spring_probe": response.json()}


async def read_sibling_ticket_summary(state: BaselineState) -> BaselineState:
    if state.get("requested_by") != "spring":
        raise ValueError("sibling summary accepts only Spring-owned runs")
    ticket_id = state["ticket_id"]
    generation_id = state["generation_id"]
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.get(
            f"{os.environ['SPRING_INTERNAL_URL']}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/sibling-summary",
            headers={
                "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
                "X-Agent-Generation-Id": generation_id,
                "X-Agent-Operation": "READ_SIBLING_TICKET_SUMMARY",
            },
        )
        response.raise_for_status()
        summary = response.json()
    if not _valid_sibling_ticket_summary(summary):
        raise ValueError("invalid sibling ticket summary")
    return {"sibling_ticket_summary": summary}


def _valid_sibling_ticket_summary(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "tickets"}:
        return False
    tickets = value.get("tickets")
    if value.get("schemaVersion") != "sibling-ticket-summary-v1" or not isinstance(tickets, list):
        return False
    expected = {
        "issueKind": str,
        "lifecycleState": str,
        "pendingAction": str,
        "compensationFlowExists": bool,
    }
    return all(
        isinstance(ticket, dict)
        and set(ticket) == set(expected)
        and all(isinstance(ticket.get(name), value_type) for name, value_type in expected.items())
        for ticket in tickets
    )


async def investigate_ticket_step(state: BaselineState) -> BaselineState:
    if state.get("requested_by") != "spring":
        raise ValueError("ticket investigation accepts only Spring-owned runs")
    ticket_id = state["ticket_id"]
    generation_id = state["generation_id"]
    base_url = os.environ["SPRING_INTERNAL_URL"]
    authorization = f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}"
    scope_headers = {
        "Authorization": authorization,
        "X-Agent-Generation-Id": generation_id,
    }
    issue_kind = state.get("issue_kind", "LOGISTICS_DELAY")
    if issue_kind not in {
        "LOGISTICS_DELAY",
        "PACKAGE_NOT_RECEIVED",
        "DUPLICATE_CHARGE",
    }:
        raise ValueError("ticket investigation requires a supported issue kind")
    clarification_answer = state.get("clarification_answer", {})
    capability_request_scope = clarification_answer.get("clarificationRequestId", "initial")
    if not isinstance(capability_request_scope, str):
        capability_request_scope = "invalid-resume"
    async with httpx.AsyncClient(timeout=5.0) as client:
        if issue_kind != "LOGISTICS_DELAY":
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "UNSUPPORTED_SCENARIO",
                [],
            )
        try:
            loop_result = await _advance_investigation_action_loop(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                capability_request_scope,
                state.get("investigation_progress"),
                state.get("sibling_ticket_summary", {}).get("tickets", []),
            )
        except ActionLoopFailure as error:
            failed_action_records = _checkpoint_action_records(error.records)
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                _action_loop_handoff_reason(error.code),
                [],
                failed_action_records,
                _failed_run_evidence(error),
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 409:
                raise
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "TOOL_RETRY_EXHAUSTED",
                [],
            )
        if isinstance(loop_result, ActionLoopContinuation):
            return {
                "model_mode": _combined_model_mode(),
                "investigation_progress": loop_result.checkpoint,
            }
        facts = _normalize_loop_facts(loop_result.facts)
        action_records = _checkpoint_action_records(loop_result.records)
        if loop_result.terminal_action is TerminalAction.HANDOFF:
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "UNSUPPORTED_SCENARIO",
                _controlled_summary_facts(facts),
                action_records,
                _completed_run_evidence(
                    loop_result, "HANDOFF_SELECTED", state.get("investigation_run_evidence")
                ),
            )
        if loop_result.terminal_action is TerminalAction.REQUEST_CLARIFICATION:
            if _clarification_facts_reason(facts) is not None:
                return await _human_handoff(
                    client,
                    base_url,
                    ticket_id,
                    generation_id,
                    scope_headers,
                    "INVALID_TOOL_RESPONSE",
                    _controlled_summary_facts(facts),
                    action_records,
                )
            return {
                "facts": facts,
                "model_mode": _combined_model_mode(),
                "investigation_progress": None,
                "investigation_actions": action_records,
                "investigation_run_evidence": _completed_run_evidence(
                    loop_result,
                    "CLARIFICATION_SELECTED",
                    state.get("investigation_run_evidence"),
                ),
            }
        unsafe_reason = _unsafe_facts_reason(facts)
        if unsafe_reason is not None:
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                unsafe_reason,
                _controlled_summary_facts(facts),
                action_records,
                _completed_run_evidence(
                    loop_result, "SAFE_HANDOFF", state.get("investigation_run_evidence")
                ),
            )
        assert isinstance(facts, dict)
        if loop_result.terminal_action is not TerminalAction.SUBMIT_CONCLUSION:
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "INVALID_TOOL_RESPONSE",
                _controlled_summary_facts(facts),
                action_records,
                _completed_run_evidence(
                    loop_result, "SAFE_HANDOFF", state.get("investigation_run_evidence")
                ),
            )
        judgment_audit_offset = _judgment_audit_offset()
        try:
            judgment = await investigation_judgment_model.judge(
                InvestigationJudgmentInput(
                    order_reference=facts["orderReference"],
                    delay_seconds=facts["delaySeconds"],
                    evidence_refs=tuple(facts["evidenceRefs"]),
                )
            )
        except Exception:
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "INVALID_MODEL_OUTPUT",
                _controlled_summary_facts(facts),
                action_records,
                _completed_run_evidence(
                    loop_result, "SAFE_HANDOFF", state.get("investigation_run_evidence")
                ),
                _judgment_call_evidence(judgment_audit_offset, "MODEL_CALL_FAILED"),
            )
        judgment_evidence = _judgment_call_evidence(judgment_audit_offset, "")
        communication_context = await _read_customer_communication_context(
            client, base_url, ticket_id, generation_id, scope_headers
        )
        if communication_context is None:
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "INVALID_TOOL_RESPONSE",
                _controlled_summary_facts(facts),
                action_records,
                _completed_run_evidence(
                    loop_result, "SAFE_HANDOFF", state.get("investigation_run_evidence")
                ),
                judgment_evidence,
            )
        conclusion = _build_conclusion(facts, judgment)
        communication_input = CustomerCommunicationInput(
            order_reference=facts["orderReference"],
            delay_seconds=facts["delaySeconds"],
            compensation_review_required=judgment.compensation_review_required,
            evidence_refs=tuple(facts["evidenceRefs"]),
            synthetic_customer_text=communication_context["syntheticCustomerText"],
            public_conversation=tuple(
                CustomerConversationMessage(message["author"], message["body"])
                for message in communication_context["publicConversation"]
            ),
        )
        communication_audit_offset = _communication_audit_offset()
        try:
            customer_reply = await customer_communication_model.compose(communication_input)
            validate_customer_reply_envelope(communication_input, customer_reply)
        except Exception:
            communication_evidence = _communication_call_evidence(
                communication_audit_offset, "MODEL_CALL_FAILED"
            )
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "INVALID_MODEL_OUTPUT",
                _controlled_summary_facts(facts),
                action_records,
                _completed_run_evidence(
                    loop_result, "SAFE_HANDOFF", state.get("investigation_run_evidence")
                ),
                judgment_evidence,
                communication_evidence,
            )
        if customer_reply.intent is CustomerReplyIntent.HUMAN_HANDOFF:
            communication_evidence = _communication_call_evidence(communication_audit_offset, "")
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "CUSTOMER_REQUESTED_HUMAN",
                _controlled_summary_facts(facts),
                action_records,
                _completed_run_evidence(
                    loop_result, "SAFE_HANDOFF", state.get("investigation_run_evidence")
                ),
                judgment_evidence,
                communication_evidence,
            )
        completion = {**conclusion, "customerReply": customer_reply.as_request_value()}
        try:
            conclusion_response = await _request_with_retries(
                lambda: client.post(
                    f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/conclusions",
                    headers={
                        **scope_headers,
                        "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                        "Idempotency-Key": f"{generation_id}:submit-conclusion",
                    },
                    json=completion,
                )
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 422:
                return await _human_handoff(
                    client,
                    base_url,
                    ticket_id,
                    generation_id,
                    scope_headers,
                    "FACT_CONFLICT",
                    _controlled_summary_facts(facts),
                    action_records,
                    _completed_run_evidence(
                        loop_result, "SAFE_HANDOFF", state.get("investigation_run_evidence")
                    ),
                    judgment_evidence,
                )
            raise
        if conclusion_response is None:
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "TOOL_RETRY_EXHAUSTED",
                _controlled_summary_facts(facts),
                action_records,
                _completed_run_evidence(
                    loop_result, "SAFE_HANDOFF", state.get("investigation_run_evidence")
                ),
                judgment_evidence,
            )
        return {
            "facts": facts,
            "conclusion": conclusion,
            "customer_reply": customer_reply.as_request_value(),
            "model_mode": _combined_model_mode(),
            "investigation_progress": None,
            "investigation_actions": action_records,
            "investigation_run_evidence": _completed_run_evidence(
                loop_result,
                "CONCLUSION_SUBMITTED",
                state.get("investigation_run_evidence"),
            ),
            "investigation_judgment_evidence": judgment_evidence,
            "customer_communication_evidence": _communication_call_evidence(
                communication_audit_offset,
                "",
                state.get("customer_communication_evidence"),
            ),
        }


async def investigate_ticket(state: BaselineState) -> BaselineState:
    current = state
    while True:
        result = await investigate_ticket_step(current)
        if result.get("investigation_progress") is None:
            return result
        current = cast(BaselineState, {**current, **result})


async def _read_customer_communication_context(
    client: httpx.AsyncClient,
    base_url: str,
    ticket_id: str,
    generation_id: str,
    scope_headers: dict[str, str],
) -> CustomerCommunicationContextValue | None:
    response = await _request_with_retries(
        lambda: client.get(
            f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/customer-communication-context",
            headers={
                **scope_headers,
                "X-Agent-Operation": "READ_CUSTOMER_COMMUNICATION_CONTEXT",
            },
        )
    )
    if response is None:
        return None
    try:
        context = response.json()
    except ValueError:
        return None
    if not isinstance(context, dict) or set(context) != {
        "schemaVersion",
        "syntheticCustomerText",
        "publicConversation",
    }:
        return None
    conversation = context["publicConversation"]
    if (
        context["schemaVersion"] != "customer-communication-input-v1"
        or not isinstance(context["syntheticCustomerText"], str)
        or len(context["syntheticCustomerText"]) > 4_000
        or not isinstance(conversation, list)
        or len(conversation) > 20
        or not all(
            isinstance(message, dict)
            and set(message) == {"author", "body"}
            and message["author"] in {"CUSTOMER", "SUPPORT", "AGENT"}
            and isinstance(message["body"], str)
            and bool(message["body"].strip())
            and len(message["body"]) <= 2_000
            for message in conversation
        )
    ):
        return None
    return CustomerCommunicationContextValue(
        schemaVersion=context["schemaVersion"],
        syntheticCustomerText=context["syntheticCustomerText"],
        publicConversation=[
            CustomerCommunicationContextMessage(author=message["author"], body=message["body"])
            for message in conversation
        ],
    )


async def _advance_investigation_action_loop(
    client: httpx.AsyncClient,
    base_url: str,
    ticket_id: str,
    generation_id: str,
    scope_headers: dict[str, str],
    request_scope: str,
    checkpoint: dict[str, object] | None,
    sibling_tickets: object,
):
    capability_headers = {
        **scope_headers,
        "X-Agent-Operation": "USE_INVESTIGATION_CAPABILITY",
    }
    if checkpoint is None:
        catalog_response = await _request_with_retries(
            lambda: client.get(
                f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/capabilities",
                headers=capability_headers,
            )
        )
        if catalog_response is None:
            raise ActionLoopFailure(ActionLoopFailureCode.TOOL_FAILURE)
        try:
            catalog = catalog_response.json()
        except ValueError as error:
            raise ActionLoopFailure(ActionLoopFailureCode.TOOL_FAILURE) from error
        if not _valid_capability_catalog(catalog):
            raise ActionLoopFailure(ActionLoopFailureCode.TOOL_FAILURE)

    async def execute(action: InvestigationAction) -> dict:
        capability = InvestigationCapability(action.kind.value)
        result = await _invoke_investigation_capability(
            client,
            base_url,
            ticket_id,
            generation_id,
            capability_headers,
            capability,
            action.parameter_map,
            request_scope,
        )
        if result is None:
            raise ActionLoopFailure(ActionLoopFailureCode.TOOL_FAILURE)
        if not _valid_capability_result(capability, result):
            raise ActionLoopFailure(ActionLoopFailureCode.INVALID_TOOL_RESPONSE)
        assert isinstance(result, dict)
        if not _valid_capability_evidence(capability, result, action.parameter_map):
            raise ActionLoopFailure(ActionLoopFailureCode.INVALID_TOOL_RESPONSE)
        return result

    async def choose(facts: dict) -> ActionDecision:
        model_context = dict(facts)
        model_context["siblingTickets"] = sibling_tickets
        return await investigation_action_model.choose(model_context)

    return await ActionLoop(choose, ActionBudget.configured()).advance(checkpoint, execute)


def _combined_model_mode() -> str:
    modes = []
    if investigation_action_model_mode != "deterministic-action-model-v1":
        modes.append(investigation_action_model_mode)
    modes.append(investigation_model_mode)
    if customer_communication_model_mode != "fixed-fake-customer-communication-v1":
        modes.append(customer_communication_model_mode)
    return "+".join(modes)


def _action_loop_handoff_reason(code: ActionLoopFailureCode) -> str:
    if code is ActionLoopFailureCode.INVALID_TOOL_RESPONSE:
        return "INVALID_TOOL_RESPONSE"
    if code in {
        ActionLoopFailureCode.MODEL_CALL_FAILED,
        ActionLoopFailureCode.UNKNOWN_ACTION,
    }:
        return "INVALID_MODEL_OUTPUT"
    return "TOOL_RETRY_EXHAUSTED"


def _normalize_loop_facts(collected: dict) -> dict:
    facts = {name: collected.get(name) for name in REQUIRED_FACT_FIELDS}
    if facts.get("matchStatus") == "AMBIGUOUS":
        facts["evidenceRefs"] = []
        return facts
    order_reference = facts.get("orderReference")
    facts["evidenceRefs"] = [
        f"order:{order_reference}",
        f"logistics:{order_reference}",
    ]
    return facts


def _checkpoint_action_records(records: tuple[ActionRecord, ...]) -> list[dict[str, object]]:
    return [
        {
            "actionType": record.action_type,
            "evidenceReferences": list(record.evidence_references),
            "resultCode": record.result_code,
        }
        for record in records
    ]


def _failed_run_evidence(error: ActionLoopFailure) -> dict[str, object]:
    evidence: dict[str, object] = {
        "outcome": "SAFE_HANDOFF",
        "failureClassification": error.failure_classification or error.code.value,
        "providerAttempts": error.provider_attempts,
        "toolRounds": len(error.records),
        "modelCalls": _model_call_evidence(error.model_calls),
    }
    tokens = sum(call.tokens for call in error.model_calls)
    cost_micros = sum(call.cost_micros for call in error.model_calls)
    if tokens or cost_micros:
        evidence["tokens"] = tokens
        evidence["costMicros"] = cost_micros
    return evidence


def _completed_run_evidence(
    result: ActionLoopResult, outcome: str, prior: object = None
) -> dict[str, object]:
    tool_rounds = sum(
        record.action_type in {capability.value for capability in InvestigationCapability}
        for record in result.records
    )
    previous = prior if isinstance(prior, dict) else {}
    previous_calls = previous.get("modelCalls")
    previous_calls = previous_calls if isinstance(previous_calls, list) else []
    return {
        "outcome": outcome,
        "failureClassification": "",
        "providerAttempts": _evidence_int(previous.get("providerAttempts"))
        + result.provider_attempts,
        "toolRounds": _evidence_int(previous.get("toolRounds")) + tool_rounds,
        "tokens": _evidence_int(previous.get("tokens")) + result.tokens,
        "costMicros": _evidence_int(previous.get("costMicros")) + result.cost_micros,
        "modelCalls": [*previous_calls, *_model_call_evidence(result.model_calls)],
    }


def _model_call_evidence(
    calls: tuple[ActionModelCallRecord, ...],
) -> list[dict[str, object]]:
    return [
        {
            "callNumber": call.call_number,
            "selectedAction": call.selected_action,
            "providerAttempts": call.provider_attempts,
            "tokens": call.tokens,
            "costMicros": call.cost_micros,
        }
        for call in calls
    ]


def _judgment_audit_offset() -> int | None:
    if not isinstance(investigation_judgment_model, DeepSeekResponsesInvestigationModel):
        return None
    sink = investigation_judgment_model.audit_sink
    return len(sink.records) if isinstance(sink, InMemoryModelCallAuditSink) else None


def _judgment_call_evidence(offset: int | None, failure: str) -> dict[str, object]:
    if offset is None or not isinstance(
        investigation_judgment_model, DeepSeekResponsesInvestigationModel
    ):
        return {
            "logicalCalls": 0,
            "providerAttempts": 0,
            "tokens": 0,
            "costMicros": 0,
            "failureClassification": failure,
        }
    sink = investigation_judgment_model.audit_sink
    if not isinstance(sink, InMemoryModelCallAuditSink):
        raise RuntimeError("formal judgment audit sink is not readable")
    records = sink.records[offset:]
    input_tokens = sum(record.input_tokens or 0 for record in records)
    output_tokens = sum(record.output_tokens or 0 for record in records)
    classifications = {
        record.failure_classification.value
        for record in records
        if record.failure_classification is not None
    }
    return {
        "logicalCalls": 1 if records else 0,
        "providerAttempts": len(records),
        "tokens": sum(record.total_tokens or 0 for record in records),
        "costMicros": estimate_flash_cost_micros(input_tokens, output_tokens),
        "failureClassification": failure or (sorted(classifications)[0] if classifications else ""),
    }


def _communication_audit_offset() -> int | None:
    if not isinstance(customer_communication_model, DeepSeekResponsesCustomerCommunicationModel):
        return None
    sink = customer_communication_model.audit_sink
    return len(sink.records) if isinstance(sink, InMemoryModelCallAuditSink) else None


def _communication_call_evidence(
    offset: int | None,
    failure: str,
    previous: dict[str, object] | None = None,
) -> dict[str, object]:
    if offset is None or not isinstance(
        customer_communication_model, DeepSeekResponsesCustomerCommunicationModel
    ):
        current = {
            "logicalCalls": 0,
            "providerAttempts": 0,
            "tokens": 0,
            "costMicros": 0,
            "durationMs": 0,
            "failureClassification": failure,
        }
        return _merge_communication_evidence(previous, current)
    sink = customer_communication_model.audit_sink
    if not isinstance(sink, InMemoryModelCallAuditSink):
        raise RuntimeError("formal communication audit sink is not readable")
    records = sink.records[offset:]
    input_tokens = sum(record.input_tokens or 0 for record in records)
    output_tokens = sum(record.output_tokens or 0 for record in records)
    classifications = {
        record.failure_classification.value
        for record in records
        if record.failure_classification is not None
    }
    current = {
        "logicalCalls": 1 if records else 0,
        "providerAttempts": len(records),
        "tokens": sum(record.total_tokens or 0 for record in records),
        "costMicros": estimate_flash_cost_micros(input_tokens, output_tokens),
        "durationMs": sum(record.duration_ms for record in records),
        "failureClassification": failure or (sorted(classifications)[0] if classifications else ""),
    }
    return _merge_communication_evidence(previous, current)


def _merge_communication_evidence(
    previous: dict[str, object] | None, current: dict[str, object]
) -> dict[str, object]:
    if not previous:
        return current
    failure = str(current["failureClassification"] or previous.get("failureClassification", ""))
    return {
        "logicalCalls": _evidence_int(previous.get("logicalCalls"))
        + _evidence_int(current.get("logicalCalls")),
        "providerAttempts": _evidence_int(previous.get("providerAttempts"))
        + _evidence_int(current.get("providerAttempts")),
        "tokens": _evidence_int(previous.get("tokens")) + _evidence_int(current.get("tokens")),
        "costMicros": _evidence_int(previous.get("costMicros"))
        + _evidence_int(current.get("costMicros")),
        "durationMs": _evidence_int(previous.get("durationMs"))
        + _evidence_int(current.get("durationMs")),
        "failureClassification": failure,
    }


def _evidence_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _valid_capability_evidence(
    capability: InvestigationCapability, result: dict, parameters: dict[str, str]
) -> bool:
    if capability is InvestigationCapability.CONFIRM_ORDER:
        if result["matchStatus"] == "AMBIGUOUS":
            return result["evidenceRefs"] == [] and isinstance(result["orderReference"], str)
        reference = result["orderReference"]
        return result["matchStatus"] == "UNIQUE" and result["evidenceRefs"] == [
            f"order:{reference}"
        ]
    reference = parameters["orderReference"]
    if capability is InvestigationCapability.READ_LOGISTICS:
        expected = [f"logistics:{reference}"]
    elif capability is InvestigationCapability.READ_PAYMENT_AND_REFUNDS:
        expected = [f"payment:{reference}"]
    elif capability is InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS:
        expected = [
            f"compensation:{reference}",
            f"order-actions:{reference}",
        ]
    else:
        expected = [f"policy:{result['policyVersion']}"]
    return result["evidenceRefs"] == expected


async def _invoke_investigation_capability(
    client: httpx.AsyncClient,
    base_url: str,
    ticket_id: str,
    generation_id: str,
    headers: dict[str, str],
    capability: InvestigationCapability,
    parameters: dict[str, str],
    request_scope: str,
) -> object | None:
    response = await _request_with_retries(
        lambda: client.post(
            f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/capabilities/{capability.value}",
            headers={
                **headers,
                "Idempotency-Key": (
                    f"{generation_id}:investigation:{request_scope}:capability:{capability.value}"
                ),
            },
            json=parameters,
        )
    )
    if response is None:
        return None
    try:
        return response.json()
    except ValueError:
        return "INVALID_CAPABILITY_RESULT"


def _valid_capability_catalog(catalog: object) -> bool:
    if not isinstance(catalog, dict) or set(catalog) != {"schemaVersion", "capabilities"}:
        return False
    if catalog["schemaVersion"] != "investigation-capability-catalog-v1":
        return False
    definitions = catalog["capabilities"]
    if not isinstance(definitions, list) or len(definitions) != len(CAPABILITY_CONTRACTS):
        return False
    declared: dict[str, CapabilityContract] = {}
    for definition in definitions:
        if not isinstance(definition, dict) or set(definition) != {
            "name",
            "parameters",
            "resultFields",
        }:
            return False
        name = definition.get("name")
        parameters = definition.get("parameters")
        result_fields = definition.get("resultFields")
        if (
            not isinstance(name, str)
            or not isinstance(parameters, list)
            or not isinstance(result_fields, list)
        ):
            return False
        parsed_parameters = _parse_capability_fields(parameters)
        parsed_results = _parse_capability_fields(result_fields)
        if parsed_parameters is None or parsed_results is None or name in declared:
            return False
        declared[name] = CapabilityContract(parsed_parameters, parsed_results)
    return declared == {
        capability.value: contract for capability, contract in CAPABILITY_CONTRACTS.items()
    }


def _parse_capability_fields(fields: list) -> tuple[CapabilityField, ...] | None:
    parsed: list[CapabilityField] = []
    for field in fields:
        if (
            not isinstance(field, dict)
            or set(field) != {"name", "type", "required"}
            or not isinstance(field.get("name"), str)
            or field.get("type") not in {STRING, INTEGER, BOOLEAN, STRING_LIST}
            or field.get("required") is not True
        ):
            return None
        parsed.append(CapabilityField(field["name"], field["type"]))
    return tuple(parsed)


def _valid_capability_result(capability: InvestigationCapability, result: object) -> bool:
    if not isinstance(result, dict):
        return False
    contract = CAPABILITY_CONTRACTS[capability]
    if set(result) != {field.name for field in contract.result_fields}:
        return False
    if result.get("capability") != capability.value:
        return False
    for field in contract.result_fields:
        value = result[field.name]
        if field.type == STRING and not isinstance(value, str):
            return False
        if field.type == INTEGER and (not isinstance(value, int) or isinstance(value, bool)):
            return False
        if field.type == BOOLEAN and not isinstance(value, bool):
            return False
        if field.type == STRING_LIST and (
            not isinstance(value, list) or not all(isinstance(item, str) for item in value)
        ):
            return False
    return True


async def shadow_investigation(state: BaselineState) -> BaselineState:
    ticket_id = state["ticket_id"]
    generation_id = state["generation_id"]
    try:
        candidate = shadow_candidate_factory()
    except Exception:
        candidate = ShadowCandidate(
            model=FixedFakeInvestigationModel(),
            model_name=DEEPSEEK_FLASH_MODEL,
            prompt_version=INVESTIGATION_JUDGMENT_PROMPT_VERSION,
            schema_version=INVESTIGATION_JUDGMENT_SCHEMA_VERSION,
        )
        record = failed_shadow_comparison(
            ticket_id=ticket_id,
            generation_id=generation_id,
            candidate=candidate,
        )
        return {"shadow_comparison": record.as_checkpoint_value()}
    if candidate is None:
        return {}
    facts = state["facts"]
    conclusion = state["conclusion"]
    model_input = InvestigationJudgmentInput(
        order_reference=facts["orderReference"],
        delay_seconds=facts["delaySeconds"],
        evidence_refs=tuple(facts["evidenceRefs"]),
    )
    baseline = InvestigationJudgment(
        compensation_review_required=conclusion["compensationRequired"],
        reason_code=InvestigationReasonCode(conclusion["reasonCode"]),
    )
    record = await compare_shadow_judgment(
        ticket_id=ticket_id,
        generation_id=generation_id,
        model_input=model_input,
        baseline=baseline,
        candidate=candidate,
    )
    return {"shadow_comparison": record.as_checkpoint_value()}


def _tool_attempt_budget() -> int:
    try:
        configured = int(os.getenv("AGENT_TOOL_MAX_ATTEMPTS", "3"))
    except ValueError:
        return 3
    return min(max(configured, 1), 5)


async def _request_with_retries(
    request: Callable[[], Awaitable[httpx.Response]],
) -> httpx.Response | None:
    for _ in range(_tool_attempt_budget()):
        try:
            response = await request()
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.TimeoutException):
            continue
        except httpx.HTTPStatusError as error:
            if error.response.status_code >= 500:
                continue
            raise
    return None


def _unsafe_facts_reason(facts: object) -> str | None:
    if not isinstance(facts, dict):
        return "INVALID_TOOL_RESPONSE"
    present = set(facts)
    if facts.get("matchStatus") == "AMBIGUOUS":
        return _clarification_facts_reason(facts)
    typed_values = {
        "orderReference": str,
        "delayHours": int,
        "delaySeconds": int,
        "paid": bool,
        "cancelled": bool,
        "fullyRefunded": bool,
        "existingCompensation": bool,
        "pendingActionCount": int,
        "policyVersion": str,
        "evidenceRefs": list,
        "matchStatus": str,
    }
    for name in present & REQUIRED_FACT_FIELDS:
        expected = typed_values[name]
        value = facts[name]
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            return "INVALID_TOOL_RESPONSE"
    if not REQUIRED_FACT_FIELDS.issubset(present):
        return "REQUIRED_FACT_MISSING"
    if present != REQUIRED_FACT_FIELDS:
        return "INVALID_TOOL_RESPONSE"
    if facts["matchStatus"] != "UNIQUE":
        return "INVALID_TOOL_RESPONSE"
    evidence = facts["evidenceRefs"]
    if not all(isinstance(item, str) for item in evidence):
        return "INVALID_TOOL_RESPONSE"
    expected_evidence = [
        f"order:{facts['orderReference']}",
        f"logistics:{facts['orderReference']}",
    ]
    if evidence != expected_evidence:
        return "INVALID_TOOL_RESPONSE"
    if facts["delaySeconds"] != facts["delayHours"] * 60 * 60:
        return "FACT_CONFLICT"
    if (
        not facts["paid"]
        or facts["cancelled"]
        or facts["fullyRefunded"]
        or facts["existingCompensation"]
        or facts["pendingActionCount"] != 0
        or facts["policyVersion"] != "delay-policy-v1"
    ):
        return "UNSUPPORTED_SCENARIO"
    return None


def _clarification_facts_reason(facts: object) -> str | None:
    if not isinstance(facts, dict):
        return "INVALID_TOOL_RESPONSE"
    present = set(facts)
    if not REQUIRED_FACT_FIELDS.issubset(present):
        return "REQUIRED_FACT_MISSING"
    if present != REQUIRED_FACT_FIELDS:
        return "INVALID_TOOL_RESPONSE"
    nullable_fields = (
        "delayHours",
        "delaySeconds",
        "paid",
        "cancelled",
        "fullyRefunded",
        "existingCompensation",
        "pendingActionCount",
        "policyVersion",
    )
    valid_ambiguity = (
        facts.get("matchStatus") == "AMBIGUOUS"
        and isinstance(facts.get("orderReference"), str)
        and bool(facts["orderReference"])
        and all(facts[name] is None for name in nullable_fields)
        and facts["evidenceRefs"] == []
    )
    return None if valid_ambiguity else "INVALID_TOOL_RESPONSE"


def _controlled_summary_facts(facts: object) -> list[dict[str, str]]:
    if not isinstance(facts, dict):
        return []
    evidence = facts.get("evidenceRefs")
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        return []
    order_reference = facts.get("orderReference")
    if not isinstance(order_reference, str):
        return []
    if evidence != [f"order:{order_reference}", f"logistics:{order_reference}"]:
        return []
    allowed = [{"type": "ORDER", "value": order_reference, "evidenceReference": evidence[0]}]
    if isinstance(facts.get("delaySeconds"), int) and not isinstance(
        facts.get("delaySeconds"), bool
    ):
        allowed.append(
            {
                "type": "LOGISTICS_DELAY_SECONDS",
                "value": str(facts["delaySeconds"]),
                "evidenceReference": evidence[1],
            }
        )
    return allowed


async def _human_handoff(
    client: httpx.AsyncClient,
    base_url: str,
    ticket_id: str,
    generation_id: str,
    scope_headers: dict[str, str],
    reason_code: str,
    facts: list[dict[str, str]],
    action_records: list[dict[str, object]] | None = None,
    run_evidence: dict[str, object] | None = None,
    judgment_evidence: dict[str, object] | None = None,
    communication_evidence: dict[str, object] | None = None,
) -> BaselineState:
    response = await client.post(
        f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/human-handoff",
        headers={
            **scope_headers,
            "X-Agent-Operation": "REQUEST_HUMAN_HANDOFF",
            "Idempotency-Key": f"{generation_id}:human-handoff:{reason_code}",
        },
        json={
            "reasonCode": reason_code,
            "summary": {"conclusionCode": "INVESTIGATION_COULD_NOT_CONTINUE", "facts": facts},
        },
    )
    response.raise_for_status()
    result: BaselineState = {
        "handoff": response.json(),
        "model_mode": _combined_model_mode(),
        "investigation_progress": None,
        "investigation_actions": action_records or [],
    }
    if run_evidence is not None:
        result["investigation_run_evidence"] = run_evidence
    if judgment_evidence is not None:
        result["investigation_judgment_evidence"] = judgment_evidence
    if communication_evidence is not None:
        result["customer_communication_evidence"] = communication_evidence
    return result


async def request_clarification(state: BaselineState) -> BaselineState:
    if (
        state.get("requested_by") != "spring"
        or state.get("facts", {}).get("matchStatus") != "AMBIGUOUS"
    ):
        raise ValueError("clarification requires a Spring-owned ambiguous investigation")
    ticket_id = state["ticket_id"]
    generation_id = state["generation_id"]
    headers = {
        "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
        "X-Agent-Generation-Id": generation_id,
        "X-Agent-Operation": "CREATE_CUSTOMER_CLARIFICATION",
        "Idempotency-Key": f"{generation_id}:order-disambiguation",
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        base_url = os.environ["SPRING_INTERNAL_URL"]
        scope_headers = {
            "Authorization": headers["Authorization"],
            "X-Agent-Generation-Id": generation_id,
        }
        context = await _read_customer_communication_context(
            client,
            base_url,
            ticket_id,
            generation_id,
            scope_headers,
        )
        if context is None:
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "INVALID_TOOL_RESPONSE",
                [],
            )
        model_input = CustomerCommunicationInput(
            order_reference=state["facts"]["orderReference"],
            delay_seconds=None,
            compensation_review_required=None,
            evidence_refs=(),
            synthetic_customer_text=context["syntheticCustomerText"],
            public_conversation=tuple(
                CustomerConversationMessage(message["author"], message["body"])
                for message in context["publicConversation"]
            ),
        )
        communication_audit_offset = _communication_audit_offset()
        try:
            customer_reply = await customer_communication_model.compose(model_input)
            validate_customer_reply_envelope(model_input, customer_reply)
        except Exception:
            communication_evidence = _communication_call_evidence(
                communication_audit_offset, "MODEL_CALL_FAILED"
            )
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "INVALID_MODEL_OUTPUT",
                [],
                communication_evidence=communication_evidence,
            )
        if customer_reply.intent is CustomerReplyIntent.HUMAN_HANDOFF:
            communication_evidence = _communication_call_evidence(communication_audit_offset, "")
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "CUSTOMER_REQUESTED_HUMAN",
                [],
                communication_evidence=communication_evidence,
            )
        if customer_reply.intent is not CustomerReplyIntent.CLARIFICATION_REQUIRED:
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "INVALID_MODEL_OUTPUT",
                [],
            )
        try:
            response = await client.post(
                f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/clarifications",
                headers=headers,
                json={
                    "reasonCode": "ORDER_AMBIGUOUS",
                    "customerReply": customer_reply.as_request_value(),
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError:
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                "INVALID_MODEL_OUTPUT",
                [],
            )
        return {
            "clarification": response.json(),
            "customer_reply": customer_reply.as_request_value(),
            "customer_communication_evidence": _communication_call_evidence(
                communication_audit_offset,
                "",
                state.get("customer_communication_evidence"),
            ),
        }


def await_clarification(state: BaselineState) -> BaselineState:
    clarification = state["clarification"]
    public_interrupt = {
        "clarificationRequestId": clarification["clarificationRequestId"],
        "promptCode": clarification["promptCode"],
        "question": clarification["question"],
    }
    interrupt(public_interrupt)
    return {
        "clarification_answer": {
            "clarificationRequestId": clarification["clarificationRequestId"],
        }
    }


def _build_conclusion(facts: dict, judgment: InvestigationJudgment) -> dict:
    return {
        "compensationRequired": judgment.compensation_review_required,
        "reasonCode": judgment.reason_code.value,
        "delayHours": facts["delayHours"],
        "delaySeconds": facts["delaySeconds"],
        "orderReference": facts["orderReference"],
        "evidenceRefs": facts["evidenceRefs"],
    }


def select_work(state: BaselineState) -> str:
    return "read_sibling_ticket_summary" if state.get("ticket_id") else "probe_spring"


def after_investigation(state: BaselineState) -> str:
    if state.get("investigation_progress") is not None:
        return "investigate_ticket"
    if state.get("facts", {}).get("matchStatus") == "AMBIGUOUS":
        return "request_clarification"
    if state.get("conclusion") and shadow_mode_enabled():
        return "shadow_investigation"
    return END


builder = StateGraph(BaselineState)
builder.add_node("probe_spring", probe_spring)
builder.add_node("read_sibling_ticket_summary", read_sibling_ticket_summary)
builder.add_node("investigate_ticket", investigate_ticket_step)
builder.add_node("shadow_investigation", shadow_investigation)
builder.add_node("request_clarification", request_clarification)
builder.add_node("await_clarification", await_clarification)
builder.add_conditional_edges(START, select_work)
builder.add_edge("probe_spring", END)
builder.add_edge("read_sibling_ticket_summary", "investigate_ticket")
builder.add_conditional_edges("investigate_ticket", after_investigation)
builder.add_edge("shadow_investigation", END)
builder.add_edge("request_clarification", "await_clarification")
builder.add_edge("await_clarification", "investigate_ticket")
graph = builder.compile()
