import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from baseline_agent.deepseek_investigation_model import (
    DEEPSEEK_FLASH_MODEL,
    INVESTIGATION_JUDGMENT_PROMPT_VERSION,
    INVESTIGATION_JUDGMENT_SCHEMA_VERSION,
)
from baseline_agent.investigation_action_loop import (
    ActionBudget,
    ActionDecision,
    ActionLoop,
    ActionLoopFailure,
    ActionLoopFailureCode,
    DeterministicActionModel,
    InvestigationAction,
)
from baseline_agent.investigation_model import (
    FixedFakeInvestigationModel,
    InvestigationJudgment,
    InvestigationJudgmentInput,
    InvestigationJudgmentModel,
    InvestigationReasonCode,
)
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
    facts: dict
    conclusion: dict
    clarification: dict
    clarification_answer: dict
    model_mode: str
    shadow_comparison: dict[str, str]
    handoff: dict
    investigation_actions: list[dict[str, object]]


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

investigation_judgment_model: InvestigationJudgmentModel = FixedFakeInvestigationModel()
investigation_action_model = DeterministicActionModel()
shadow_candidate_factory: Callable[[], ShadowCandidate | None] = configured_shadow_candidate


class InvestigationCapability(StrEnum):
    CONFIRM_ORDER = "CONFIRM_ORDER"
    READ_LOGISTICS = "READ_LOGISTICS"
    READ_PAYMENT_AND_REFUNDS = "READ_PAYMENT_AND_REFUNDS"
    READ_COMPENSATION_AND_PENDING_ACTIONS = "READ_COMPENSATION_AND_PENDING_ACTIONS"
    READ_APPLICABLE_POLICY = "READ_APPLICABLE_POLICY"


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
ORDER_REFERENCE = (CapabilityField("orderReference", STRING),)
CAPABILITY_CONTRACTS = {
    InvestigationCapability.CONFIRM_ORDER: CapabilityContract(
        (),
        (
            CapabilityField("capability", STRING),
            CapabilityField("matchStatus", STRING),
            CapabilityField("orderReference", STRING),
            CapabilityField("evidenceRefs", STRING_LIST),
        ),
    ),
    InvestigationCapability.READ_LOGISTICS: CapabilityContract(
        ORDER_REFERENCE,
        (
            CapabilityField("capability", STRING),
            CapabilityField("delayHours", INTEGER),
            CapabilityField("delaySeconds", INTEGER),
            CapabilityField("evidenceRefs", STRING_LIST),
        ),
    ),
    InvestigationCapability.READ_PAYMENT_AND_REFUNDS: CapabilityContract(
        ORDER_REFERENCE,
        (
            CapabilityField("capability", STRING),
            CapabilityField("paid", BOOLEAN),
            CapabilityField("cancelled", BOOLEAN),
            CapabilityField("fullyRefunded", BOOLEAN),
            CapabilityField("evidenceRefs", STRING_LIST),
        ),
    ),
    InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS: CapabilityContract(
        ORDER_REFERENCE,
        (
            CapabilityField("capability", STRING),
            CapabilityField("existingCompensation", BOOLEAN),
            CapabilityField("pendingActionCount", INTEGER),
            CapabilityField("evidenceRefs", STRING_LIST),
        ),
    ),
    InvestigationCapability.READ_APPLICABLE_POLICY: CapabilityContract(
        ORDER_REFERENCE,
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


async def investigate_ticket(state: BaselineState) -> BaselineState:
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
    clarification_answer = state.get("clarification_answer", {})
    capability_request_scope = clarification_answer.get("clarificationRequestId", "initial")
    if not isinstance(capability_request_scope, str):
        capability_request_scope = "invalid-resume"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            loop_result = await _run_investigation_action_loop(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                capability_request_scope,
            )
        except ActionLoopFailure as error:
            return await _human_handoff(
                client,
                base_url,
                ticket_id,
                generation_id,
                scope_headers,
                (
                    "INVALID_TOOL_RESPONSE"
                    if error.code is ActionLoopFailureCode.INVALID_TOOL_RESPONSE
                    else "TOOL_RETRY_EXHAUSTED"
                ),
                [],
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
        facts = _normalize_loop_facts(loop_result.facts)
        action_records = [
            {
                "actionType": record.action_type,
                "evidenceReferences": list(record.evidence_references),
                "resultCode": record.result_code,
            }
            for record in loop_result.records
        ]
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
            )
        assert isinstance(facts, dict)
        if facts.get("matchStatus") == "AMBIGUOUS":
            return {
                "facts": facts,
                "model_mode": "fixed-fake-model-v1",
                "investigation_actions": action_records,
            }
        judgment = await investigation_judgment_model.judge(
            InvestigationJudgmentInput(
                order_reference=facts["orderReference"],
                delay_seconds=facts["delaySeconds"],
                evidence_refs=tuple(facts["evidenceRefs"]),
            )
        )
        conclusion = _build_conclusion(facts, judgment)
        try:
            conclusion_response = await _request_with_retries(
                lambda: client.post(
                    f"{base_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/conclusions",
                    headers={
                        **scope_headers,
                        "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                        "Idempotency-Key": f"{generation_id}:submit-conclusion",
                    },
                    json=conclusion,
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
            )
        return {
            "facts": facts,
            "conclusion": conclusion,
            "model_mode": "fixed-fake-model-v1",
            "investigation_actions": action_records,
        }


async def _run_investigation_action_loop(
    client: httpx.AsyncClient,
    base_url: str,
    ticket_id: str,
    generation_id: str,
    scope_headers: dict[str, str],
    request_scope: str,
):
    capability_headers = {
        **scope_headers,
        "X-Agent-Operation": "USE_INVESTIGATION_CAPABILITY",
    }
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
        return await investigation_action_model.choose(facts)

    return await ActionLoop(choose, ActionBudget.configured()).run(execute)


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
            isinstance(facts["orderReference"], str)
            and all(facts[name] is None for name in nullable_fields)
            and facts["evidenceRefs"] == []
        )
        return None if valid_ambiguity else "INVALID_TOOL_RESPONSE"
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
    return {"handoff": response.json(), "model_mode": "fixed-fake-model-v1"}


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
        response = await client.post(
            f"{os.environ['SPRING_INTERNAL_URL']}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/clarifications",
            headers=headers,
            json={"reasonCode": "ORDER_AMBIGUOUS"},
        )
        response.raise_for_status()
        return {"clarification": response.json()}


def await_clarification(state: BaselineState) -> BaselineState:
    clarification = state["clarification"]
    public_interrupt = {
        "clarificationRequestId": clarification["clarificationRequestId"],
        "promptCode": clarification["promptCode"],
        "question": clarification["question"],
    }
    answer = interrupt(public_interrupt)
    if not isinstance(answer, dict):
        answer = {}
    return {
        "clarification_answer": {
            **answer,
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
    return "investigate_ticket" if state.get("ticket_id") else "probe_spring"


def after_investigation(state: BaselineState) -> str:
    if state.get("facts", {}).get("matchStatus") == "AMBIGUOUS":
        return "request_clarification"
    if state.get("conclusion") and shadow_mode_enabled():
        return "shadow_investigation"
    return END


builder = StateGraph(BaselineState)
builder.add_node("probe_spring", probe_spring)
builder.add_node("investigate_ticket", investigate_ticket)
builder.add_node("shadow_investigation", shadow_investigation)
builder.add_node("request_clarification", request_clarification)
builder.add_node("await_clarification", await_clarification)
builder.add_conditional_edges(START, select_work)
builder.add_edge("probe_spring", END)
builder.add_conditional_edges("investigate_ticket", after_investigation)
builder.add_edge("shadow_investigation", END)
builder.add_edge("request_clarification", "await_clarification")
builder.add_edge("await_clarification", "investigate_ticket")
graph = builder.compile()
