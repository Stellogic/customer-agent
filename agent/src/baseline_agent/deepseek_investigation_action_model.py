from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from baseline_agent.deepseek_investigation_model import (
    DEEPSEEK_FLASH_MODEL,
    DeepSeekFailureClassification,
    InMemoryModelCallAuditSink,
    ModelCallAttemptRecord,
    ModelCallAuditSink,
    estimate_flash_cost_micros,
)
from baseline_agent.investigation_action_loop import (
    CAPABILITY_PARAMETER_NAMES,
    ActionDecision,
    ActionLoopFailure,
    ActionLoopFailureCode,
    ActionUsage,
    InvestigationCapability,
    TerminalAction,
)

_RESPONSES_ENDPOINT = "https://api.deepseek.com/responses"
_TRANSIENT_HTTP_STATUSES = frozenset({429, 500, 503})
ACTION_PROMPT_VERSION = "investigation-action-v2"
ACTION_SCHEMA_VERSION = "investigation-action-v2"


@dataclass(frozen=True)
class DeepSeekActionConfig:
    api_key: str = field(repr=False)
    model: str = DEEPSEEK_FLASH_MODEL
    connect_timeout_seconds: float = 3
    read_timeout_seconds: float = 9
    deadline_seconds: float = 12
    max_attempts: int = 2
    retry_base_delay_seconds: float = 0.2
    max_output_tokens: int = 128

    def __post_init__(self) -> None:
        if (
            not self.api_key.strip()
            or self.model != DEEPSEEK_FLASH_MODEL
            or self.connect_timeout_seconds <= 0
            or self.read_timeout_seconds <= 0
            or self.deadline_seconds <= 0
            or not 1 <= self.max_attempts <= 2
            or self.retry_base_delay_seconds < 0
            or not 32 <= self.max_output_tokens <= 256
        ):
            raise ActionLoopFailure(ActionLoopFailureCode.MODEL_CALL_FAILED)

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> DeepSeekActionConfig:
        return cls(
            api_key=environment.get("DEEPSEEK_API_KEY", ""),
            model=environment.get("DEEPSEEK_MODEL", ""),
            max_attempts=1,
        )


class DeepSeekResponsesInvestigationActionModel:
    def __init__(
        self,
        config: DeepSeekActionConfig,
        *,
        endpoint: str = _RESPONSES_ENDPOINT,
        transport: httpx.AsyncBaseTransport | None = None,
        audit_sink: ModelCallAuditSink | None = None,
    ) -> None:
        self._config = config
        self._endpoint = endpoint
        self._transport = transport
        self.audit_sink = audit_sink or InMemoryModelCallAuditSink()

    async def choose(self, facts: dict) -> ActionDecision:
        controlled_facts = _controlled_facts(facts)
        allowed_actions = _allowed_actions(controlled_facts)
        request_body = _build_request(self._config, controlled_facts, allowed_actions)
        internal_call_id = str(uuid.uuid4())
        call_started = time.monotonic()
        timeout = httpx.Timeout(
            connect=self._config.connect_timeout_seconds,
            read=self._config.read_timeout_seconds,
            write=self._config.connect_timeout_seconds,
            pool=self._config.connect_timeout_seconds,
        )
        async with httpx.AsyncClient(
            timeout=timeout,
            transport=self._transport,
            headers={"Authorization": f"Bearer {self._config.api_key}"},
        ) as client:
            for attempt_number in range(1, self._config.max_attempts + 1):
                remaining = self._config.deadline_seconds - (time.monotonic() - call_started)
                if remaining <= 0:
                    raise _failure(attempt_number - 1)
                attempt_id = str(uuid.uuid4())
                attempt_started = time.monotonic()
                try:
                    response = await asyncio.wait_for(
                        client.post(self._endpoint, json=request_body), timeout=remaining
                    )
                except (TimeoutError, httpx.TransportError):
                    await self._record_attempt(
                        internal_call_id,
                        attempt_id,
                        attempt_number,
                        attempt_started,
                        request_body,
                        DeepSeekFailureClassification.TRANSIENT_PROVIDER_ERROR,
                    )
                    if await self._can_retry(attempt_number, call_started):
                        continue
                    raise _failure(attempt_number) from None

                if response.status_code >= 400:
                    classification = (
                        DeepSeekFailureClassification.TRANSIENT_PROVIDER_ERROR
                        if response.status_code in _TRANSIENT_HTTP_STATUSES
                        else DeepSeekFailureClassification.PROVIDER_REQUEST_REJECTED
                    )
                    await self._record_attempt(
                        internal_call_id,
                        attempt_id,
                        attempt_number,
                        attempt_started,
                        request_body,
                        classification,
                        provider_http_status=response.status_code,
                    )
                    if response.status_code in _TRANSIENT_HTTP_STATUSES and await self._can_retry(
                        attempt_number, call_started
                    ):
                        continue
                    raise _failure(attempt_number)

                payload: object | None = None
                try:
                    payload = response.json()
                    decision = _parse_response(
                        payload,
                        controlled_facts,
                        allowed_actions,
                        attempt_number,
                    )
                except (ValueError, TypeError, KeyError, ActionLoopFailure):
                    await self._record_attempt(
                        internal_call_id,
                        attempt_id,
                        attempt_number,
                        attempt_started,
                        request_body,
                        DeepSeekFailureClassification.SCHEMA_MISMATCH,
                        payload if isinstance(payload, dict) else None,
                        provider_http_status=response.status_code,
                    )
                    raise _failure(attempt_number) from None
                assert isinstance(payload, dict)
                await self._record_attempt(
                    internal_call_id,
                    attempt_id,
                    attempt_number,
                    attempt_started,
                    request_body,
                    None,
                    payload,
                    provider_http_status=response.status_code,
                )
                return decision
        raise AssertionError("attempt budget must produce a result or controlled failure")

    async def _can_retry(self, attempt_number: int, call_started: float) -> bool:
        if attempt_number >= self._config.max_attempts:
            return False
        delay = self._config.retry_base_delay_seconds * (2 ** (attempt_number - 1))
        remaining = self._config.deadline_seconds - (time.monotonic() - call_started)
        if delay >= remaining:
            return False
        if delay:
            await asyncio.sleep(delay)
        return True

    async def _record_attempt(
        self,
        internal_call_id: str,
        attempt_id: str,
        attempt_number: int,
        attempt_started: float,
        request_body: dict[str, Any],
        failure: DeepSeekFailureClassification | None,
        payload: dict[str, Any] | None = None,
        *,
        provider_http_status: int | None = None,
    ) -> None:
        usage = payload.get("usage") if payload else None
        usage = usage if isinstance(usage, dict) else {}
        await self.audit_sink.record(
            ModelCallAttemptRecord(
                internal_call_id=internal_call_id,
                attempt_id=attempt_id,
                attempt_number=attempt_number,
                provider="deepseek",
                provider_response_id=_optional_string(payload.get("id")) if payload else None,
                response_status=_optional_string(payload.get("status")) if payload else None,
                request_model=self._config.model,
                response_model=_optional_string(payload.get("model")) if payload else None,
                backend_fingerprint=(
                    _optional_string(payload.get("system_fingerprint")) if payload else None
                ),
                prompt_version=ACTION_PROMPT_VERSION,
                schema_version=ACTION_SCHEMA_VERSION,
                duration_ms=max(0, round((time.monotonic() - attempt_started) * 1000)),
                input_tokens=_optional_int(usage.get("input_tokens")),
                output_tokens=_optional_int(usage.get("output_tokens")),
                total_tokens=_optional_int(usage.get("total_tokens")),
                cached_tokens=None,
                cache_hit=None,
                failure_classification=failure,
                provider_http_status=provider_http_status,
                strict_schema_requested=request_body["text"]["format"].get("strict") is True,
                thinking_disabled=request_body.get("reasoning") == {"effort": "none"},
                allowed_parameters_only=set(request_body)
                == {
                    "model",
                    "instructions",
                    "input",
                    "max_output_tokens",
                    "reasoning",
                    "stream",
                    "text",
                },
                actual_response_shape_valid=failure is None,
                usage_reported=all(
                    _optional_int(usage.get(name)) is not None
                    for name in ("input_tokens", "output_tokens", "total_tokens")
                ),
                cache_metrics_reported=False,
            )
        )


def _controlled_facts(facts: dict) -> dict[str, object]:
    if not isinstance(facts, dict):
        raise _failure()
    allowed = {
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
    if not set(facts).issubset(allowed):
        raise _failure()
    return {key: facts[key] for key in sorted(facts)}


def _allowed_actions(facts: dict[str, object]) -> tuple[str, ...]:
    match_status = facts.get("matchStatus")
    if match_status is None:
        return (InvestigationCapability.CONFIRM_ORDER.value,)
    if match_status == "AMBIGUOUS":
        return (TerminalAction.REQUEST_CLARIFICATION.value,)
    reference = facts.get("orderReference")
    if match_status != "UNIQUE" or not isinstance(reference, str) or not reference:
        return (TerminalAction.HANDOFF.value,)
    completion_markers = {
        InvestigationCapability.READ_LOGISTICS: "delaySeconds",
        InvestigationCapability.READ_PAYMENT_AND_REFUNDS: "paid",
        InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS: "existingCompensation",
        InvestigationCapability.READ_APPLICABLE_POLICY: "policyVersion",
    }
    missing_capabilities = tuple(
        capability.value
        for capability in completion_markers
        if completion_markers[capability] not in facts
    )
    return missing_capabilities or (TerminalAction.SUBMIT_CONCLUSION.value,)


def _build_request(
    config: DeepSeekActionConfig,
    facts: dict[str, object],
    allowed_actions: tuple[str, ...],
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(allowed_actions)},
            "orderReference": {"type": ["string", "null"]},
        },
        "required": ["action", "orderReference"],
        "additionalProperties": False,
    }
    return {
        "model": config.model,
        "instructions": (
            "Choose exactly one next action for a synthetic support-ticket investigation. "
            "Use only the enumerated action. CONFIRM_ORDER and terminal actions require a null "
            "orderReference. Fact-reading actions require the exact supplied orderReference. "
            "Missing facts are expected investigation work, not uncertainty: when matchStatus is "
            "missing select CONFIRM_ORDER; when it is AMBIGUOUS select REQUEST_CLARIFICATION; "
            "when it is UNIQUE select any one still-unread fact capability. Submit only after all "
            "order, logistics, payment/refund, compensation/pending-action and policy facts exist. "
            "Select HANDOFF only when supplied facts explicitly conflict or mark the scenario "
            "unsupported. Never invent facts, identifiers, evidence, "
            "amounts, tools, credentials, reasoning, or customer-visible text."
        ),
        "input": json.dumps(
            {"syntheticInvestigationFacts": facts}, separators=(",", ":"), sort_keys=True
        ),
        "max_output_tokens": config.max_output_tokens,
        "reasoning": {"effort": "none"},
        "stream": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "customer_agent_investigation_action",
                "strict": True,
                "schema": schema,
            }
        },
    }


def _parse_response(
    payload: object,
    facts: dict[str, object],
    allowed_actions: tuple[str, ...],
    attempts: int,
) -> ActionDecision:
    if not isinstance(payload, dict) or payload.get("status") != "completed":
        raise _failure()
    response_model = payload.get("model")
    if not isinstance(response_model, str) or not response_model.startswith(DEEPSEEK_FLASH_MODEL):
        raise _failure()
    output = payload.get("output")
    if not isinstance(output, list):
        raise _failure()
    texts = [
        part["text"]
        for item in output
        if isinstance(item, dict) and item.get("type") == "message"
        for part in item.get("content", [])
        if isinstance(part, dict)
        and part.get("type") == "output_text"
        and isinstance(part.get("text"), str)
    ]
    refused = any(
        isinstance(part, dict) and part.get("type") == "refusal"
        for item in output
        if isinstance(item, dict)
        for part in item.get("content", [])
    )
    if refused or len(texts) != 1:
        raise _failure()
    structured = json.loads(texts[0])
    if not isinstance(structured, dict) or set(structured) != {"action", "orderReference"}:
        raise _failure()
    action = structured["action"]
    reference = structured["orderReference"]
    if not isinstance(action, str) or (reference is not None and not isinstance(reference, str)):
        raise _failure()
    if action not in allowed_actions:
        raise _failure()
    try:
        capability = InvestigationCapability(action)
        terminal = None
    except ValueError:
        capability = None
        try:
            terminal = TerminalAction(action)
        except ValueError:
            raise _failure() from None
    if capability is not None and CAPABILITY_PARAMETER_NAMES[capability]:
        if not reference or reference != facts.get("orderReference"):
            raise _failure()
        parameters = {"orderReference": reference}
    else:
        if reference is not None:
            raise _failure()
        parameters = {}
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise _failure()
    input_tokens = _optional_int(usage.get("input_tokens"))
    output_tokens = _optional_int(usage.get("output_tokens"))
    total_tokens = _optional_int(usage.get("total_tokens"))
    if input_tokens is None or output_tokens is None or total_tokens is None:
        raise _failure()
    if total_tokens < input_tokens + output_tokens:
        raise _failure()
    cost_micros = estimate_flash_cost_micros(input_tokens, output_tokens)
    selected_action = capability if capability is not None else terminal
    assert selected_action is not None
    return ActionDecision.from_values(
        selected_action,
        parameters,
        ActionUsage(
            tokens=total_tokens,
            cost_micros=cost_micros,
            provider_attempts=attempts,
        ),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _failure(provider_attempts: int = 0) -> ActionLoopFailure:
    return ActionLoopFailure(
        ActionLoopFailureCode.MODEL_CALL_FAILED,
        provider_attempts=provider_attempts,
    )
