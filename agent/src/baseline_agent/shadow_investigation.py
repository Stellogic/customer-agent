from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum

import httpx

from baseline_agent.deepseek_investigation_model import (
    DEEPSEEK_FLASH_MODEL,
    INVESTIGATION_JUDGMENT_PROMPT_VERSION,
    INVESTIGATION_JUDGMENT_SCHEMA_VERSION,
    DeepSeekResponsesConfig,
    DeepSeekResponsesInvestigationModel,
    InMemoryModelCallAuditSink,
    ModelCallAttemptRecord,
)
from baseline_agent.investigation_model import (
    InvestigationJudgment,
    InvestigationJudgmentInput,
    InvestigationJudgmentModel,
)
from baseline_agent.real_shadow_policy import REAL_SHADOW_PROVIDER_POLICY

_SHADOW_MODE_ENVIRONMENT_KEY = "AGENT_INVESTIGATION_SHADOW_MODE"


class ShadowComparisonOutcome(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ShadowCandidate:
    model: InvestigationJudgmentModel
    model_name: str
    prompt_version: str
    schema_version: str
    maximum_provider_attempts: int = 1
    audit_records: list[ModelCallAttemptRecord] | None = None


@dataclass(frozen=True)
class ShadowComparisonRecord:
    comparison_id: str
    ticket_id: str
    generation_id: str
    model: str
    prompt_version: str
    schema_version: str
    outcome: ShadowComparisonOutcome
    failure_classification: str = ""
    latency_ms: int = 0
    provider_attempts: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    contract_valid: bool = False
    provider_http_status: int | None = None

    def as_checkpoint_value(self) -> dict[str, str]:
        return {
            name: (
                ""
                if value is None
                else str(value).lower()
                if isinstance(value, bool)
                else str(value)
            )
            for name, value in asdict(self).items()
        }


def configured_shadow_candidate(
    environment: Mapping[str, str] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    audit_sink: InMemoryModelCallAuditSink | None = None,
) -> ShadowCandidate | None:
    values = os.environ if environment is None else environment
    mode = _configured_shadow_mode(values)
    if mode in {"", "disabled"}:
        return None
    if mode == "offline":
        audit = audit_sink or InMemoryModelCallAuditSink()
        fault = values.get("AGENT_INVESTIGATION_SHADOW_FAULT", "").strip().lower()
        if fault not in {"", "refusal", "timeout", "invalid-output"}:
            raise ValueError("unsupported investigation shadow fault")
        config = DeepSeekResponsesConfig(
            api_key="offline-shadow-substitute",
            max_attempts=1,
            retry_base_delay_seconds=0,
        )
        return ShadowCandidate(
            model=DeepSeekResponsesInvestigationModel(
                config,
                transport=transport
                or httpx.MockTransport(lambda request: _offline_supplier_response(request, fault)),
                audit_sink=audit,
            ),
            model_name=DEEPSEEK_FLASH_MODEL,
            prompt_version=INVESTIGATION_JUDGMENT_PROMPT_VERSION,
            schema_version=INVESTIGATION_JUDGMENT_SCHEMA_VERSION,
            audit_records=audit.records,
        )
    if mode != "deepseek":
        raise ValueError("unsupported investigation shadow mode")
    audit = audit_sink or InMemoryModelCallAuditSink()
    policy = REAL_SHADOW_PROVIDER_POLICY
    config = DeepSeekResponsesConfig(
        api_key=values.get("DEEPSEEK_API_KEY", ""),
        model=values.get("DEEPSEEK_MODEL", policy.candidate_model),
        connect_timeout_seconds=policy.connect_timeout_seconds,
        read_timeout_seconds=policy.read_timeout_seconds,
        deadline_seconds=policy.call_deadline_seconds,
        max_attempts=policy.maximum_attempts_per_scenario,
        retry_base_delay_seconds=0,
        max_output_tokens=policy.maximum_output_tokens,
    )
    return ShadowCandidate(
        model=DeepSeekResponsesInvestigationModel(
            config,
            transport=transport,
            audit_sink=audit,
        ),
        model_name=config.model,
        prompt_version=INVESTIGATION_JUDGMENT_PROMPT_VERSION,
        schema_version=INVESTIGATION_JUDGMENT_SCHEMA_VERSION,
        audit_records=audit.records,
    )


def shadow_mode_enabled(environment: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environment is None else environment
    return _configured_shadow_mode(values) not in {"", "disabled"}


def _configured_shadow_mode(environment: Mapping[str, str]) -> str:
    return environment.get(_SHADOW_MODE_ENVIRONMENT_KEY, "disabled").strip().lower()


def _offline_supplier_response(request: httpx.Request, fault: str = "") -> httpx.Response:
    if fault == "timeout":
        raise httpx.ReadTimeout("controlled offline shadow timeout")
    request_body = json.loads(request.content)
    model_input = json.loads(request_body["input"])
    delay_seconds = model_input["syntheticInvestigationFacts"]["delaySeconds"]
    compensation_required = delay_seconds >= 24 * 60 * 60
    reason_code = "LOGISTICS_DELAY" if compensation_required else "DELAY_UNDER_24_HOURS"
    judgment = (
        "controlled-invalid-json"
        if fault == "invalid-output"
        else json.dumps(
            {
                "compensationReviewRequired": compensation_required,
                "reasonCode": reason_code,
            },
            separators=(",", ":"),
        )
    )
    content = (
        [{"type": "refusal", "refusal": "controlled offline shadow refusal"}]
        if fault == "refusal"
        else [{"type": "output_text", "text": judgment}]
    )
    return httpx.Response(
        200,
        json={
            "id": "offline-shadow-response",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "model": DEEPSEEK_FLASH_MODEL,
            "system_fingerprint": "offline-shadow-substitute-v1",
            "output": [
                {
                    "id": "offline-shadow-message",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": content,
                }
            ],
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        },
    )


def failed_shadow_comparison(
    *, ticket_id: str, generation_id: str, candidate: ShadowCandidate
) -> ShadowComparisonRecord:
    return _comparison_record(
        ticket_id=ticket_id,
        generation_id=generation_id,
        candidate=candidate,
        outcome=ShadowComparisonOutcome.FAILED,
    )


async def compare_shadow_judgment(
    *,
    ticket_id: str,
    generation_id: str,
    model_input: InvestigationJudgmentInput,
    baseline: InvestigationJudgment,
    candidate: ShadowCandidate,
) -> ShadowComparisonRecord:
    outcome = ShadowComparisonOutcome.FAILED
    started = time.monotonic()
    existing_attempts = len(candidate.audit_records or ())
    failure_classification = ""
    try:
        shadow = await candidate.model.judge(model_input)
        outcome = (
            ShadowComparisonOutcome.MATCH
            if shadow == baseline
            else ShadowComparisonOutcome.MISMATCH
        )
    except Exception:
        # Shadow is observational only. Provider, parsing, and configuration failures must
        # never alter the already-authoritative fake-model business path.
        failure_classification = "MODEL_CALL_FAILED"
    records = (candidate.audit_records or [])[existing_attempts:]
    if records and records[-1].failure_classification is not None:
        failure_classification = records[-1].failure_classification.value
    usage_reported = bool(records) and all(record.usage_reported for record in records)
    cache_reported = bool(records) and all(record.cache_metrics_reported for record in records)
    contract_valid = bool(records) and (
        outcome is not ShadowComparisonOutcome.FAILED
        and all(
            record.failure_classification is None
            and record.response_status == "completed"
            and record.strict_schema_requested
            and record.thinking_disabled
            and record.allowed_parameters_only
            and record.actual_response_shape_valid
            and record.usage_reported
            and record.cache_metrics_reported
            for record in records
        )
    )
    return _comparison_record(
        ticket_id=ticket_id,
        generation_id=generation_id,
        candidate=candidate,
        outcome=outcome,
        failure_classification=failure_classification,
        latency_ms=(
            sum(record.duration_ms for record in records)
            if records
            else max(0, round((time.monotonic() - started) * 1000))
        ),
        provider_attempts=len(records),
        input_tokens=(
            sum(record.input_tokens or 0 for record in records) if usage_reported else None
        ),
        output_tokens=(
            sum(record.output_tokens or 0 for record in records) if usage_reported else None
        ),
        total_tokens=(
            sum(record.total_tokens or 0 for record in records) if usage_reported else None
        ),
        cached_input_tokens=(
            sum(record.cached_tokens or 0 for record in records) if cache_reported else None
        ),
        contract_valid=contract_valid,
        provider_http_status=(records[-1].provider_http_status if records else None),
    )


def _comparison_record(
    *,
    ticket_id: str,
    generation_id: str,
    candidate: ShadowCandidate,
    outcome: ShadowComparisonOutcome,
    failure_classification: str = "",
    latency_ms: int = 0,
    provider_attempts: int = 0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    contract_valid: bool = False,
    provider_http_status: int | None = None,
) -> ShadowComparisonRecord:
    comparison_id = hashlib.sha256(
        (
            f"{ticket_id}\n{generation_id}\n{candidate.model_name}\n"
            f"{candidate.prompt_version}\n{candidate.schema_version}"
        ).encode()
    ).hexdigest()
    return ShadowComparisonRecord(
        comparison_id=comparison_id,
        ticket_id=ticket_id,
        generation_id=generation_id,
        model=candidate.model_name,
        prompt_version=candidate.prompt_version,
        schema_version=candidate.schema_version,
        outcome=outcome,
        failure_classification=failure_classification,
        latency_ms=latency_ms,
        provider_attempts=provider_attempts,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input_tokens,
        contract_valid=contract_valid,
        provider_http_status=provider_http_status,
    )
