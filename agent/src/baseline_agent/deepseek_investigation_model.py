from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

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
_SUPPORTED_MODEL = "deepseek-v4-flash"
_PROMPT_VERSION = "investigation-judgment-v1"
_SCHEMA_VERSION = "investigation-judgment-v1"
_TRANSIENT_HTTP_STATUSES = frozenset({429, 500, 503})


class DeepSeekFailureClassification(StrEnum):
    CONNECTION_TIMEOUT = "CONNECTION_TIMEOUT"
    READ_TIMEOUT = "READ_TIMEOUT"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    PROVIDER_REQUEST_REJECTED = "PROVIDER_REQUEST_REJECTED"
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
    model: str = _SUPPORTED_MODEL
    connect_timeout_seconds: float = 3
    read_timeout_seconds: float = 15
    deadline_seconds: float = 20
    max_attempts: int = 3
    retry_base_delay_seconds: float = 0.2
    max_output_tokens: int = 128

    def __post_init__(self) -> None:
        if (
            not self.api_key.strip()
            or self.model != _SUPPORTED_MODEL
            or self.connect_timeout_seconds <= 0
            or self.read_timeout_seconds <= 0
            or self.deadline_seconds <= 0
            or not 1 <= self.max_attempts <= 3
            or self.retry_base_delay_seconds < 0
            or not 32 <= self.max_output_tokens <= 256
        ):
            raise InvestigationJudgmentFailure(InvestigationJudgmentFailureCode.CONFIGURATION_ERROR)

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> DeepSeekResponsesConfig:
        return cls(
            api_key=environment.get("DEEPSEEK_API_KEY", ""),
            model=environment.get("DEEPSEEK_MODEL", _SUPPORTED_MODEL),
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
    failure_classification: DeepSeekFailureClassification | None


class ModelCallAuditSink(Protocol):
    async def record(self, record: ModelCallAttemptRecord) -> None: ...


class InMemoryModelCallAuditSink:
    def __init__(self) -> None:
        self.records: list[ModelCallAttemptRecord] = []

    async def record(self, record: ModelCallAttemptRecord) -> None:
        self.records.append(record)


class DeepSeekResponsesInvestigationModel:
    def __init__(
        self,
        config: DeepSeekResponsesConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        audit_sink: ModelCallAuditSink | None = None,
    ) -> None:
        self._config = config
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
                        client.post(_RESPONSES_ENDPOINT, json=request_body),
                        timeout=remaining,
                    )
                except TimeoutError:
                    classification = DeepSeekFailureClassification.DEADLINE_EXCEEDED
                    await self._record_attempt(
                        internal_call_id,
                        attempt_id,
                        attempt_number,
                        attempt_started,
                        classification,
                    )
                    raise _model_call_failure() from None
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
                        classification,
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
                        failure.classification,
                        payload,
                    )
                    raise _model_call_failure() from None
                await self._record_attempt(
                    internal_call_id,
                    attempt_id,
                    attempt_number,
                    attempt_started,
                    None,
                    payload,
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
        failure_classification: DeepSeekFailureClassification | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        usage = payload.get("usage") if payload else None
        usage = usage if isinstance(usage, dict) else {}
        input_details = usage.get("input_tokens_details")
        input_details = input_details if isinstance(input_details, dict) else {}
        cached_tokens = _optional_int(input_details.get("cached_tokens"))
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
                prompt_version=_PROMPT_VERSION,
                schema_version=_SCHEMA_VERSION,
                duration_ms=max(0, round((time.monotonic() - attempt_started) * 1000)),
                input_tokens=_optional_int(usage.get("input_tokens")),
                output_tokens=_optional_int(usage.get("output_tokens")),
                total_tokens=_optional_int(usage.get("total_tokens")),
                cached_tokens=cached_tokens,
                cache_hit=cached_tokens > 0 if cached_tokens is not None else None,
                failure_classification=failure_classification,
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


class _DeepSeekResponseFailure(Exception):
    def __init__(self, classification: DeepSeekFailureClassification) -> None:
        self.classification = classification
        super().__init__(classification.value)


def _model_call_failure() -> InvestigationJudgmentFailure:
    return InvestigationJudgmentFailure(InvestigationJudgmentFailureCode.MODEL_CALL_FAILED)
