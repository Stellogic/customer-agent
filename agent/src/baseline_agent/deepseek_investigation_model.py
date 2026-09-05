from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from weakref import WeakKeyDictionary

import httpx

from baseline_agent.investigation_model import (
    InvestigationJudgment,
    InvestigationJudgmentFailure,
    InvestigationJudgmentFailureCode,
    InvestigationJudgmentInput,
    InvestigationReasonCode,
    validate_investigation_judgment_input,
)

_RESPONSES_ENDPOINT = "https://api.deepseek.com/responses"
DEEPSEEK_FLASH_MODEL = "deepseek-v4-flash"
DEEPSEEK_PRO_MODEL = "deepseek-v4-pro"
INVESTIGATION_JUDGMENT_PROMPT_VERSION = "investigation-judgment-v1"
INVESTIGATION_JUDGMENT_SCHEMA_VERSION = "investigation-judgment-v1"
_TRANSIENT_HTTP_STATUSES = frozenset({429, 500, 503})
_FLASH_INPUT_USD_PER_MILLION_TOKENS = 0.44
_FLASH_OUTPUT_USD_PER_MILLION_TOKENS = 1.32


class DeepSeekFailureClassification(StrEnum):
    CONNECTION_TIMEOUT = "CONNECTION_TIMEOUT"
    READ_TIMEOUT = "READ_TIMEOUT"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    PROVIDER_REQUEST_REJECTED = "PROVIDER_REQUEST_REJECTED"
    PUBLIC_REPLY_PUBLISH_FAILED = "PUBLIC_REPLY_PUBLISH_FAILED"
    TRANSIENT_PROVIDER_ERROR = "TRANSIENT_PROVIDER_ERROR"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    PROVIDER_INCOMPLETE = "PROVIDER_INCOMPLETE"
    MODEL_REFUSAL = "MODEL_REFUSAL"
    EMPTY_OUTPUT = "EMPTY_OUTPUT"
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"


@dataclass(frozen=True)
class DeepSeekResponsesConfig:
    api_key: str = field(repr=False)
    model: str = DEEPSEEK_FLASH_MODEL
    connect_timeout_seconds: float = 3
    read_timeout_seconds: float = 15
    deadline_seconds: float = 20
    max_attempts: int = 3
    retry_base_delay_seconds: float = 0.2
    max_output_tokens: int = 128
    _model_comparison_candidate: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not self.api_key.strip()
            or self.model
            not in (
                {DEEPSEEK_FLASH_MODEL, DEEPSEEK_PRO_MODEL}
                if self._model_comparison_candidate
                else {DEEPSEEK_FLASH_MODEL}
            )
            or self.connect_timeout_seconds <= 0
            or self.read_timeout_seconds <= 0
            or self.deadline_seconds <= 0
            or not 1 <= self.max_attempts <= 3
            or self.retry_base_delay_seconds < 0
            or not 32 <= self.max_output_tokens <= 256
        ):
            raise InvestigationJudgmentFailure(InvestigationJudgmentFailureCode.CONFIGURATION_ERROR)

    @classmethod
    def for_model_comparison(
        cls,
        *,
        api_key: str,
        model: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        deadline_seconds: float,
        max_attempts: int,
        retry_base_delay_seconds: float,
        max_output_tokens: int,
    ) -> DeepSeekResponsesConfig:
        return cls(
            api_key=api_key,
            model=model,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            deadline_seconds=deadline_seconds,
            max_attempts=max_attempts,
            retry_base_delay_seconds=retry_base_delay_seconds,
            max_output_tokens=max_output_tokens,
            _model_comparison_candidate=True,
        )

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> DeepSeekResponsesConfig:
        return cls(
            api_key=environment.get("DEEPSEEK_API_KEY", ""),
            model=environment.get("DEEPSEEK_MODEL", DEEPSEEK_FLASH_MODEL),
        )


@dataclass(frozen=True)
class ModelCallAttemptRecord:
    internal_call_id: str
    attempt_id: str
    attempt_number: int
    provider: str
    provider_response_id: str | None
    response_status: str | None
    request_model: str
    response_model: str | None
    backend_fingerprint: str | None
    prompt_version: str
    schema_version: str
    duration_ms: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_tokens: int | None
    cache_hit: bool | None
    failure_classification: DeepSeekFailureClassification | None = None
    provider_http_status: int | None = None
    strict_schema_requested: bool = False
    thinking_disabled: bool = False
    allowed_parameters_only: bool = False
    actual_response_shape_valid: bool = False
    usage_reported: bool = False
    cache_metrics_reported: bool = False
    reasoning_tokens: int | None = None
    validation_diagnostic: dict[str, object] | None = None


class ModelCallAuditSink(Protocol):
    async def record(self, record: ModelCallAttemptRecord) -> None: ...


class InMemoryModelCallAuditSink:
    def __init__(self) -> None:
        self.records: list[ModelCallAttemptRecord] = []
        self._task_records: WeakKeyDictionary[asyncio.Task[Any], list[ModelCallAttemptRecord]] = (
            WeakKeyDictionary()
        )

    def current_task_records(self) -> list[ModelCallAttemptRecord]:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("model audit requires an asyncio task")
        return self._task_records.setdefault(task, [])

    async def record(self, record: ModelCallAttemptRecord) -> None:
        self.records.append(record)
        self.current_task_records().append(record)


def estimate_flash_cost_micros(input_tokens: int, output_tokens: int) -> int:
    return math.ceil(
        input_tokens * _FLASH_INPUT_USD_PER_MILLION_TOKENS
        + output_tokens * _FLASH_OUTPUT_USD_PER_MILLION_TOKENS
    )


class DeepSeekResponsesInvestigationModel:
    def __init__(
        self,
        config: DeepSeekResponsesConfig,
        *,
        endpoint: str = _RESPONSES_ENDPOINT,
        transport: httpx.AsyncBaseTransport | None = None,
        audit_sink: ModelCallAuditSink | None = None,
    ) -> None:
        self._config = config
        self._endpoint = endpoint
        self._transport = transport
        self.audit_sink = audit_sink or InMemoryModelCallAuditSink()

    async def judge(self, model_input: InvestigationJudgmentInput) -> InvestigationJudgment:
        validate_investigation_judgment_input(model_input)
        request_body = _build_request(self._config, model_input)
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
                    raise _model_call_failure()
                attempt_id = str(uuid.uuid4())
                attempt_started = time.monotonic()
                try:
                    response = await asyncio.wait_for(
                        client.post(self._endpoint, json=request_body),
                        timeout=remaining,
                    )
                except TimeoutError:
                    classification = DeepSeekFailureClassification.DEADLINE_EXCEEDED
                    await self._record_attempt(
                        internal_call_id,
                        attempt_id,
                        attempt_number,
                        attempt_started,
                        request_body,
                        classification,
                    )
                    raise _model_call_failure() from None
                except asyncio.CancelledError:
                    await self._record_attempt(
                        internal_call_id,
                        attempt_id,
                        attempt_number,
                        attempt_started,
                        request_body,
                        DeepSeekFailureClassification.DEADLINE_EXCEEDED,
                    )
                    raise
                except httpx.TransportError as error:
                    if isinstance(error, httpx.ConnectTimeout):
                        classification = DeepSeekFailureClassification.CONNECTION_TIMEOUT
                    elif isinstance(error, httpx.ReadTimeout):
                        classification = DeepSeekFailureClassification.READ_TIMEOUT
                    else:
                        classification = DeepSeekFailureClassification.TRANSIENT_PROVIDER_ERROR
                    await self._record_attempt(
                        internal_call_id,
                        attempt_id,
                        attempt_number,
                        attempt_started,
                        request_body,
                        classification,
                    )
                    if await self._can_retry(attempt_number, call_started):
                        continue
                    raise _model_call_failure() from None

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
                    raise _model_call_failure()

                try:
                    payload = response.json()
                except json.JSONDecodeError:
                    classification = DeepSeekFailureClassification.INVALID_JSON
                    await self._record_attempt(
                        internal_call_id,
                        attempt_id,
                        attempt_number,
                        attempt_started,
                        request_body,
                        classification,
                    )
                    raise _model_call_failure() from None

                if not isinstance(payload, dict):
                    classification = DeepSeekFailureClassification.SCHEMA_MISMATCH
                    await self._record_attempt(
                        internal_call_id,
                        attempt_id,
                        attempt_number,
                        attempt_started,
                        request_body,
                        classification,
                    )
                    raise _model_call_failure()

                try:
                    judgment = _parse_response(payload)
                except _DeepSeekResponseFailure as failure:
                    await self._record_attempt(
                        internal_call_id,
                        attempt_id,
                        attempt_number,
                        attempt_started,
                        request_body,
                        failure.classification,
                        payload,
                        provider_http_status=response.status_code,
                    )
                    raise _model_call_failure() from None
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
                return judgment

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
        failure_classification: DeepSeekFailureClassification | None,
        payload: dict[str, Any] | None = None,
        *,
        provider_http_status: int | None = None,
    ) -> None:
        usage = payload.get("usage") if payload else None
        usage = usage if isinstance(usage, dict) else {}
        input_details = usage.get("input_tokens_details")
        input_details = input_details if isinstance(input_details, dict) else {}
        output_details = usage.get("output_tokens_details")
        output_details = output_details if isinstance(output_details, dict) else {}
        cached_tokens = _optional_int(input_details.get("cached_tokens"))
        reasoning_tokens = _optional_int(output_details.get("reasoning_tokens"))
        response_model = _optional_string(payload.get("model")) if payload else None
        response_shape_valid = failure_classification is None and _has_expected_response_shape(
            payload, self._config.model
        )
        allowed_parameters_only = set(request_body) == {
            "model",
            "instructions",
            "input",
            "max_output_tokens",
            "reasoning",
            "stream",
            "text",
        }
        await self.audit_sink.record(
            ModelCallAttemptRecord(
                internal_call_id=internal_call_id,
                attempt_id=attempt_id,
                attempt_number=attempt_number,
                provider="deepseek",
                provider_response_id=_optional_string(payload.get("id")) if payload else None,
                response_status=_optional_string(payload.get("status")) if payload else None,
                request_model=self._config.model,
                response_model=response_model,
                backend_fingerprint=(
                    _optional_string(payload.get("system_fingerprint")) if payload else None
                ),
                prompt_version=INVESTIGATION_JUDGMENT_PROMPT_VERSION,
                schema_version=INVESTIGATION_JUDGMENT_SCHEMA_VERSION,
                duration_ms=max(0, round((time.monotonic() - attempt_started) * 1000)),
                input_tokens=_optional_int(usage.get("input_tokens")),
                output_tokens=_optional_int(usage.get("output_tokens")),
                total_tokens=_optional_int(usage.get("total_tokens")),
                cached_tokens=cached_tokens,
                cache_hit=cached_tokens > 0 if cached_tokens is not None else None,
                failure_classification=failure_classification,
                provider_http_status=provider_http_status,
                strict_schema_requested=_strict_schema_requested(request_body),
                thinking_disabled=(
                    request_body.get("reasoning") == {"effort": "none"}
                    and reasoning_tokens == 0
                    and not _contains_reasoning_item(payload)
                ),
                allowed_parameters_only=allowed_parameters_only,
                actual_response_shape_valid=response_shape_valid,
                usage_reported=(
                    _optional_int(usage.get("input_tokens")) is not None
                    and _optional_int(usage.get("output_tokens")) is not None
                    and _optional_int(usage.get("total_tokens")) is not None
                ),
                cache_metrics_reported=(
                    "cached_tokens" in input_details and cached_tokens is not None
                ),
                reasoning_tokens=reasoning_tokens,
            )
        )


def _build_request(
    config: DeepSeekResponsesConfig,
    model_input: InvestigationJudgmentInput,
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "compensationReviewRequired": {"type": "boolean"},
            "reasonCode": {
                "type": "string",
                "enum": [
                    InvestigationReasonCode.LOGISTICS_DELAY.value,
                    InvestigationReasonCode.DELAY_UNDER_24_HOURS.value,
                ],
            },
        },
        "required": ["compensationReviewRequired", "reasonCode"],
        "additionalProperties": False,
    }
    return {
        "model": config.model,
        "instructions": (
            "Judge only whether the supplied synthetic logistics delay requires Spring "
            "compensation review. A delay of at least 86400 seconds requires review. "
            "Return LOGISTICS_DELAY when review is required, otherwise return "
            "DELAY_UNDER_24_HOURS. Return only the strict JSON schema; do not include "
            "orders, evidence, amounts, methods, raw data, credentials, or reasoning."
        ),
        "input": json.dumps(
            {"syntheticInvestigationFacts": {"delaySeconds": model_input.delay_seconds}},
            separators=(",", ":"),
        ),
        "max_output_tokens": config.max_output_tokens,
        "reasoning": {"effort": "none"},
        "stream": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "customer_agent_investigation_judgment",
                "strict": True,
                "schema": schema,
            }
        },
    }


def _parse_response(payload: dict[str, Any]) -> InvestigationJudgment:
    status = payload.get("status")
    if status == "failed":
        raise _DeepSeekResponseFailure(DeepSeekFailureClassification.PROVIDER_FAILED)
    if status == "incomplete":
        details = payload.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, dict) else None
        code = (
            DeepSeekFailureClassification.OUTPUT_TRUNCATED
            if reason == "max_output_tokens"
            else DeepSeekFailureClassification.PROVIDER_INCOMPLETE
        )
        raise _DeepSeekResponseFailure(code)
    if status != "completed":
        raise _DeepSeekResponseFailure(DeepSeekFailureClassification.PROVIDER_INCOMPLETE)

    output_texts: list[str] = []
    refused = False
    output = payload.get("output")
    if not isinstance(output, list):
        raise _DeepSeekResponseFailure(DeepSeekFailureClassification.SCHEMA_MISMATCH)
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "refusal":
                refused = True
            elif part.get("type") == "output_text" and isinstance(part.get("text"), str):
                output_texts.append(part["text"])
    if refused:
        raise _DeepSeekResponseFailure(DeepSeekFailureClassification.MODEL_REFUSAL)
    if not output_texts or all(not text.strip() for text in output_texts):
        raise _DeepSeekResponseFailure(DeepSeekFailureClassification.EMPTY_OUTPUT)
    if len(output_texts) != 1:
        raise _DeepSeekResponseFailure(DeepSeekFailureClassification.SCHEMA_MISMATCH)
    try:
        structured = json.loads(output_texts[0])
    except json.JSONDecodeError:
        raise _DeepSeekResponseFailure(DeepSeekFailureClassification.INVALID_JSON) from None
    if not isinstance(structured, dict) or set(structured) != {
        "compensationReviewRequired",
        "reasonCode",
    }:
        raise _DeepSeekResponseFailure(DeepSeekFailureClassification.SCHEMA_MISMATCH)
    required = structured["compensationReviewRequired"]
    reason = structured["reasonCode"]
    if type(required) is not bool or not isinstance(reason, str):
        raise _DeepSeekResponseFailure(DeepSeekFailureClassification.SCHEMA_MISMATCH)
    try:
        reason_code = InvestigationReasonCode(reason)
    except ValueError:
        raise _DeepSeekResponseFailure(DeepSeekFailureClassification.SCHEMA_MISMATCH) from None
    if required is not (reason_code is InvestigationReasonCode.LOGISTICS_DELAY):
        raise _DeepSeekResponseFailure(DeepSeekFailureClassification.SCHEMA_MISMATCH)
    return InvestigationJudgment(
        compensation_review_required=required,
        reason_code=reason_code,
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _has_expected_response_shape(payload: dict[str, Any] | None, request_model: str) -> bool:
    if not payload:
        return False
    response_model = _optional_string(payload.get("model"))
    output = payload.get("output")
    usage = payload.get("usage")
    if not (
        _optional_string(payload.get("id"))
        and payload.get("object") == "response"
        and _optional_int(payload.get("created_at")) is not None
        and payload.get("status") == "completed"
        and payload.get("error") is None
        and payload.get("incomplete_details") is None
        and response_model
        and _response_model_matches(response_model, request_model)
        and isinstance(output, list)
        and output
        and isinstance(usage, dict)
    ):
        return False
    input_tokens = _optional_int(usage.get("input_tokens"))
    output_tokens = _optional_int(usage.get("output_tokens"))
    total_tokens = _optional_int(usage.get("total_tokens"))
    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    cached_tokens = (
        _optional_int(input_details.get("cached_tokens"))
        if isinstance(input_details, dict)
        else None
    )
    reasoning_tokens = (
        _optional_int(output_details.get("reasoning_tokens"))
        if isinstance(output_details, dict)
        else None
    )
    return bool(
        input_tokens is not None
        and output_tokens is not None
        and total_tokens == input_tokens + output_tokens
        and cached_tokens is not None
        and cached_tokens <= input_tokens
        and reasoning_tokens is not None
        and reasoning_tokens <= output_tokens
        and any(_is_completed_message(item) for item in output)
    )


def _response_model_matches(response_model: str, request_model: str) -> bool:
    return bool(
        response_model == request_model
        or re.fullmatch(rf"{re.escape(request_model)}-[0-9]{{4,8}}", response_model)
    )


def _is_completed_message(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    content = item.get("content")
    return bool(
        item.get("type") == "message"
        and _optional_string(item.get("id"))
        and item.get("status") == "completed"
        and item.get("role") == "assistant"
        and isinstance(content, list)
        and content
        and all(
            isinstance(part, dict)
            and part.get("type") == "output_text"
            and isinstance(part.get("text"), str)
            and bool(part["text"].strip())
            for part in content
        )
    )


def _contains_reasoning_item(payload: dict[str, Any] | None) -> bool:
    output = payload.get("output") if payload else None
    return isinstance(output, list) and any(
        isinstance(item, dict) and item.get("type") == "reasoning" for item in output
    )


def _strict_schema_requested(request_body: dict[str, Any]) -> bool:
    text = request_body.get("text")
    output_format = text.get("format") if isinstance(text, dict) else None
    schema = output_format.get("schema") if isinstance(output_format, dict) else None
    return bool(
        isinstance(output_format, dict)
        and output_format.get("type") == "json_schema"
        and output_format.get("strict") is True
        and isinstance(schema, dict)
        and schema.get("additionalProperties") is False
    )


class _DeepSeekResponseFailure(Exception):
    def __init__(self, classification: DeepSeekFailureClassification) -> None:
        self.classification = classification
        super().__init__(classification.value)


def _model_call_failure() -> InvestigationJudgmentFailure:
    return InvestigationJudgmentFailure(InvestigationJudgmentFailureCode.MODEL_CALL_FAILED)
