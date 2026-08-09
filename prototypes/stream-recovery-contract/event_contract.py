"""PROTOTYPE: pure product-event projection and browser reducer."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


SCHEMA_VERSION = 1
FORBIDDEN_KEYS = {
    "prompt",
    "messages",
    "model_input",
    "model_output",
    "reasoning",
    "tool_payload",
    "tool_result",
    "checkpoint",
    "checkpoint_id",
    "thread_id",
    "run_id",
    "trace_id",
}

EVENT_PAYLOAD_KEYS = {
    "public.progress_changed": {"statusCode"},
    "customer.message_published": {"messageCode"},
    "generation.activated": {"generationId"},
    "generation.revoked": {"generationId", "reasonCode"},
    "investigation.phase_changed": {"phase"},
    "evidence.added": {"evidenceRef", "category", "summary"},
    "tool.progress_changed": {"operationRef", "category", "status"},
    "investigation.input_required": {
        "requestRef",
        "inputKind",
        "promptKey",
        "allowedActions",
    },
    "proposal.created": {"proposalRevisionRef", "summary"},
    "ticket.result_changed": {"ticketState", "resultCode"},
    "investigation.failed": {"reasonCode", "retryable"},
    "approval.lease_changed": {"proposalRevisionRef", "leaseRef", "leaseStatus"},
    "approval.decision_recorded": {"proposalRevisionRef", "leaseRef", "decision"},
}

GENERATION_SCOPED = {
    "investigation.phase_changed",
    "evidence.added",
    "tool.progress_changed",
    "investigation.input_required",
    "proposal.created",
    "investigation.failed",
}

ENUMS = {
    "viewType": {"CUSTOMER_PUBLIC", "SUPPORT_WORKBENCH", "APPROVAL_VIEW"},
    "phase": {
        "ORDER_LOOKUP",
        "LOGISTICS_LOOKUP",
        "POLICY_EVALUATION",
        "AWAITING_INPUT",
        "PROPOSAL_DRAFTING",
        "COMPLETE",
    },
    "category": {
        "ORDER",
        "LOGISTICS",
        "POLICY",
        "ORDER_QUERY",
        "LOGISTICS_QUERY",
        "POLICY_QUERY",
    },
    "status": {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED"},
    "inputKind": {"CUSTOMER_INFORMATION", "SUPPORT_DECISION", "RETRY_DECISION"},
    "ticketState": {
        "NEW",
        "INVESTIGATING",
        "WAITING_FOR_CUSTOMER",
        "WAITING_FOR_EXTERNAL_INFORMATION",
        "RESOLVED",
        "CLOSED",
    },
    "leaseStatus": {"AVAILABLE", "ACTIVE", "EXPIRED", "RELEASED", "ENDED"},
    "decision": {"APPROVED", "REJECTED"},
}


class ContractViolation(ValueError):
    pass


@dataclass(frozen=True)
class Cursor:
    epoch: str
    sequence: int

    @classmethod
    def parse(cls, value: str) -> "Cursor":
        epoch, raw_sequence = value.rsplit(":", 1)
        return cls(epoch=epoch, sequence=int(raw_sequence))

    def __str__(self) -> str:
        return f"{self.epoch}:{self.sequence}"


def initial_state() -> dict[str, Any]:
    return {
        "stream": {
            "epoch": None,
            "lastSequence": 0,
            "viewType": None,
            "connection": "DISCONNECTED",
            "needsSnapshot": True,
        },
        "access": "UNKNOWN",
        "ticket": {
            "ticketState": None,
            "currentGenerationId": None,
            "investigationPhase": None,
            "evidence": [],
            "operations": {},
            "pendingInput": None,
            "proposalRevisionRef": None,
            "resultCode": None,
            "failure": None,
        },
        "lastAction": "INITIALIZED",
        "diagnostics": [],
    }


def apply_snapshot(state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Replace the projection. A snapshot is authoritative, never merged."""
    next_state = initial_state()
    cursor = Cursor.parse(snapshot["cursor"])
    next_state["stream"] = {
        "epoch": cursor.epoch,
        "lastSequence": cursor.sequence,
        "viewType": snapshot["viewType"],
        "connection": "CONNECTING",
        "needsSnapshot": False,
    }
    next_state["access"] = "AUTHORIZED"
    next_state["ticket"] = deepcopy(snapshot["ticket"])
    next_state["lastAction"] = "SNAPSHOT_REPLACED"
    return next_state


def mark_connected(state: dict[str, Any]) -> dict[str, Any]:
    next_state = deepcopy(state)
    if next_state["access"] == "AUTHORIZED" and not next_state["stream"]["needsSnapshot"]:
        next_state["stream"]["connection"] = "LIVE"
        next_state["lastAction"] = "STREAM_CONNECTED"
    return next_state


def mark_access_revoked(state: dict[str, Any]) -> dict[str, Any]:
    """Model Spring closing the stream after current permission becomes invalid."""
    next_state = deepcopy(state)
    next_state["access"] = "FORBIDDEN"
    next_state["stream"]["connection"] = "CLOSED"
    next_state["stream"]["needsSnapshot"] = True
    next_state["lastAction"] = "ACCESS_REVOKED_STREAM_CLOSED"
    return next_state


def mark_reset_required(state: dict[str, Any], reason: str) -> dict[str, Any]:
    next_state = deepcopy(state)
    next_state["stream"]["connection"] = "RESET_REQUIRED"
    next_state["stream"]["needsSnapshot"] = True
    next_state["lastAction"] = f"RESET_REQUIRED:{reason}"
    next_state["diagnostics"].append(reason)
    return next_state


def reduce_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Apply one sequenced product event or demand a fresh snapshot."""
    stream = state["stream"]
    if state["access"] != "AUTHORIZED":
        return _diagnose(state, "IGNORED_WITHOUT_ACCESS")
    if stream["needsSnapshot"]:
        return _diagnose(state, "INCREMENTAL_IGNORED_UNTIL_SNAPSHOT")

    try:
        validate_product_event(event)
        cursor = Cursor.parse(event["id"])
    except (ContractViolation, KeyError, ValueError) as exc:
        return mark_reset_required(state, f"INVALID_EVENT:{exc}")

    if cursor.epoch != stream["epoch"]:
        return mark_reset_required(state, "EPOCH_MISMATCH")
    if event["viewType"] != stream["viewType"]:
        return mark_reset_required(state, "VIEW_MISMATCH")
    if cursor.sequence <= stream["lastSequence"]:
        return _diagnose(state, f"DUPLICATE_IGNORED:{event['id']}")
    if cursor.sequence != stream["lastSequence"] + 1:
        return mark_reset_required(
            state,
            f"SEQUENCE_GAP:expected={stream['lastSequence'] + 1},actual={cursor.sequence}",
        )

    event_type = event["type"]
    current_generation = state["ticket"].get("currentGenerationId")
    if event_type in GENERATION_SCOPED and event["generationId"] != current_generation:
        next_state = deepcopy(state)
        next_state["stream"]["lastSequence"] = cursor.sequence
        return _diagnose(next_state, f"STALE_GENERATION_IGNORED:{event['generationId']}")

    if event_type.startswith("approval."):
        current_proposal = state["ticket"].get("proposalRevisionRef")
        current_lease = state["ticket"].get("leaseRef")
        payload = event["payload"]
        if (
            payload["proposalRevisionRef"] != current_proposal
            or payload["leaseRef"] != current_lease
        ):
            next_state = deepcopy(state)
            next_state["stream"]["lastSequence"] = cursor.sequence
            return _diagnose(
                next_state,
                "STALE_APPROVAL_SCOPE_IGNORED:"
                f"{payload['proposalRevisionRef']}:{payload['leaseRef']}",
            )

    next_state = deepcopy(state)
    next_state["stream"]["lastSequence"] = cursor.sequence
    payload = event["payload"]
    ticket = next_state["ticket"]

    if event_type == "public.progress_changed":
        ticket["publicProgress"] = payload["statusCode"]
    elif event_type == "customer.message_published":
        ticket["lastMessageCode"] = payload["messageCode"]
    elif event_type == "generation.activated":
        ticket["currentGenerationId"] = payload["generationId"]
        ticket["investigationPhase"] = None
        ticket["pendingInput"] = None
        ticket["failure"] = None
    elif event_type == "generation.revoked":
        if ticket["currentGenerationId"] == payload["generationId"]:
            ticket["currentGenerationId"] = None
            ticket["pendingInput"] = None
    elif event_type == "investigation.phase_changed":
        ticket["investigationPhase"] = payload["phase"]
    elif event_type == "evidence.added":
        if not any(item["evidenceRef"] == payload["evidenceRef"] for item in ticket["evidence"]):
            ticket["evidence"].append(deepcopy(payload))
    elif event_type == "tool.progress_changed":
        ticket["operations"][payload["operationRef"]] = deepcopy(payload)
    elif event_type == "investigation.input_required":
        ticket["pendingInput"] = deepcopy(payload)
    elif event_type == "proposal.created":
        ticket["proposalRevisionRef"] = payload["proposalRevisionRef"]
        ticket["pendingInput"] = None
    elif event_type == "ticket.result_changed":
        ticket["ticketState"] = payload["ticketState"]
        ticket["resultCode"] = payload["resultCode"]
    elif event_type == "investigation.failed":
        ticket["failure"] = deepcopy(payload)
    elif event_type == "approval.lease_changed":
        ticket["leaseStatus"] = payload["leaseStatus"]
        if payload["leaseStatus"] in {"EXPIRED", "RELEASED", "ENDED"}:
            return _close_approval_view(next_state, event_type, event["id"])
    elif event_type == "approval.decision_recorded":
        ticket["decision"] = payload["decision"]
        ticket["leaseStatus"] = "ENDED"
        return _close_approval_view(next_state, event_type, event["id"])

    next_state["lastAction"] = f"EVENT_APPLIED:{event_type}@{event['id']}"
    return next_state


def validate_product_event(event: dict[str, Any]) -> None:
    required = {
        "schemaVersion",
        "id",
        "type",
        "ticketId",
        "viewType",
        "generationId",
        "occurredAt",
        "payload",
    }
    if set(event) != required:
        raise ContractViolation(f"envelope keys must be {sorted(required)}")
    if event["schemaVersion"] != SCHEMA_VERSION:
        raise ContractViolation("unsupported schemaVersion")
    if event["type"] not in EVENT_PAYLOAD_KEYS:
        raise ContractViolation(f"event type is not allowlisted: {event['type']}")
    expected_payload = EVENT_PAYLOAD_KEYS[event["type"]]
    if set(event["payload"]) != expected_payload:
        raise ContractViolation(
            f"payload keys for {event['type']} must be {sorted(expected_payload)}"
        )
    if not isinstance(event["id"], str) or not event["id"]:
        raise ContractViolation("id must be a non-empty string")
    if not isinstance(event["ticketId"], str) or not event["ticketId"]:
        raise ContractViolation("ticketId must be a non-empty string")
    if event["viewType"] not in ENUMS["viewType"]:
        raise ContractViolation(f"unsupported viewType: {event['viewType']}")
    if event["type"] in GENERATION_SCOPED and not event["generationId"]:
        raise ContractViolation("generation-scoped event requires generationId")
    if event["type"].startswith("generation."):
        if event["generationId"] != event["payload"]["generationId"]:
            raise ContractViolation("generation envelope and payload must match")
    _validate_payload_values(event["payload"])
    _reject_forbidden_keys(event)


def project_raw_event(
    raw: dict[str, Any], cursor: Cursor, view_type: str = "SUPPORT_WORKBENCH"
) -> dict[str, Any] | None:
    """Spring-side allowlist projection. Unknown or stale raw events yield no product event."""
    kind = raw.get("kind")
    generation_id = raw.get("generation_id")
    mapping: dict[str, tuple[str, dict[str, Any], set[str]]] = {
        "spring.public_progress": (
            "public.progress_changed",
            {"statusCode": raw.get("status_code")},
            {"CUSTOMER_PUBLIC"},
        ),
        "spring.customer_message": (
            "customer.message_published",
            {"messageCode": raw.get("message_code")},
            {"CUSTOMER_PUBLIC"},
        ),
        "spring.generation_activated": (
            "generation.activated",
            {"generationId": generation_id},
            {"SUPPORT_WORKBENCH"},
        ),
        "spring.generation_revoked": (
            "generation.revoked",
            {"generationId": generation_id, "reasonCode": raw.get("reason_code")},
            {"SUPPORT_WORKBENCH"},
        ),
        "agent.phase": (
            "investigation.phase_changed",
            {"phase": raw.get("phase")},
            {"SUPPORT_WORKBENCH"},
        ),
        "agent.evidence": (
            "evidence.added",
            {
                "evidenceRef": raw.get("evidence_ref"),
                "category": raw.get("category"),
                "summary": raw.get("safe_summary"),
            },
            {"SUPPORT_WORKBENCH"},
        ),
        "agent.tool": (
            "tool.progress_changed",
            {
                "operationRef": raw.get("operation_ref"),
                "category": raw.get("category"),
                "status": raw.get("status"),
            },
            {"SUPPORT_WORKBENCH"},
        ),
        "agent.interrupt": (
            "investigation.input_required",
            {
                "requestRef": raw.get("request_ref"),
                "inputKind": raw.get("input_kind"),
                "promptKey": raw.get("prompt_key"),
                "allowedActions": raw.get("allowed_actions"),
            },
            {"SUPPORT_WORKBENCH"},
        ),
        "spring.proposal": (
            "proposal.created",
            {
                "proposalRevisionRef": raw.get("proposal_revision_ref"),
                "summary": raw.get("safe_summary"),
            },
            {"SUPPORT_WORKBENCH"},
        ),
        "spring.result": (
            "ticket.result_changed",
            {
                "ticketState": raw.get("ticket_state"),
                "resultCode": raw.get("result_code"),
            },
            {"CUSTOMER_PUBLIC", "SUPPORT_WORKBENCH"},
        ),
        "agent.failed": (
            "investigation.failed",
            {"reasonCode": raw.get("reason_code"), "retryable": raw.get("retryable")},
            {"SUPPORT_WORKBENCH"},
        ),
        "spring.approval_lease": (
            "approval.lease_changed",
            {
                "proposalRevisionRef": raw.get("proposal_revision_ref"),
                "leaseRef": raw.get("lease_ref"),
                "leaseStatus": raw.get("lease_status"),
            },
            {"APPROVAL_VIEW"},
        ),
        "spring.approval_decision": (
            "approval.decision_recorded",
            {
                "proposalRevisionRef": raw.get("proposal_revision_ref"),
                "leaseRef": raw.get("lease_ref"),
                "decision": raw.get("decision"),
            },
            {"APPROVAL_VIEW"},
        ),
    }
    if kind not in mapping:
        return None
    event_type, payload, allowed_views = mapping[kind]
    if view_type not in allowed_views:
        return None
    exposed_generation_id = generation_id if view_type == "SUPPORT_WORKBENCH" else None
    event = {
        "schemaVersion": SCHEMA_VERSION,
        "id": str(cursor),
        "type": event_type,
        "ticketId": raw["ticket_id"],
        "viewType": view_type,
        "generationId": exposed_generation_id,
        "occurredAt": raw["occurred_at"],
        "payload": payload,
    }
    validate_product_event(event)
    return event


def _reject_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        illegal = FORBIDDEN_KEYS.intersection(value)
        if illegal:
            raise ContractViolation(f"forbidden keys: {sorted(illegal)}")
        for nested in value.values():
            _reject_forbidden_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_keys(nested)


def _validate_payload_values(payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        if value is None:
            raise ContractViolation(f"payload value cannot be null: {key}")
        if key in ENUMS and value not in ENUMS[key]:
            raise ContractViolation(f"unsupported {key}: {value}")
        if key == "allowedActions":
            if not isinstance(value, list) or not value:
                raise ContractViolation("allowedActions must be a non-empty list")
            if not all(isinstance(item, str) and item for item in value):
                raise ContractViolation("allowedActions items must be non-empty strings")
        elif key == "retryable":
            if not isinstance(value, bool):
                raise ContractViolation("retryable must be boolean")
        elif not isinstance(value, str) or not value:
            raise ContractViolation(f"payload value must be a non-empty string: {key}")


def _close_approval_view(
    state: dict[str, Any], event_type: str, event_id: str
) -> dict[str, Any]:
    """End proposal-scoped responsibility and discard no-longer-authorized detail."""
    ticket = state["ticket"]
    state["ticket"] = {
        "proposalRevisionRef": ticket["proposalRevisionRef"],
        "leaseRef": ticket["leaseRef"],
        "leaseStatus": ticket["leaseStatus"],
        "decision": ticket.get("decision"),
    }
    state["access"] = "FORBIDDEN"
    state["stream"]["connection"] = "CLOSED"
    state["stream"]["needsSnapshot"] = True
    state["lastAction"] = f"APPROVAL_ACCESS_ENDED:{event_type}@{event_id}"
    return state


def _diagnose(state: dict[str, Any], message: str) -> dict[str, Any]:
    next_state = deepcopy(state)
    next_state["lastAction"] = message
    next_state["diagnostics"].append(message)
    return next_state
