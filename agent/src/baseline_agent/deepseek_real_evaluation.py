from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime

import httpx

from baseline_agent.deepseek_investigation_model import (
    DEEPSEEK_FLASH_MODEL,
    DeepSeekResponsesConfig,
    DeepSeekResponsesInvestigationModel,
    InMemoryModelCallAuditSink,
    ModelCallAttemptRecord,
)
from baseline_agent.deepseek_pricing import time_of_use_tier_at
from baseline_agent.deepseek_real_evaluation_policy import supplier_block_reason
from baseline_agent.investigation_model import (
    InvestigationJudgmentFailure,
    validate_investigation_judgment_input,
)
from baseline_agent.synthetic_evaluation import (
    AuditedInvestigationEvaluationModel,
    TokenPricing,
    evaluate_candidate,
    synthetic_evaluation_scenarios,
)

ISSUE_125_OPT_IN = "issue-125-authorized-real-deepseek-evaluation"
_REPORT_SCHEMA_VERSION = "issue-125-deepseek-real-contract-v1"
DEEPSEEK_PRICING_VERSION = "deepseek-time-of-use-2026-08-25"
_DATASET_REPETITIONS = 5
_MAX_PROVIDER_ATTEMPTS = 55
_WHOLE_EVALUATION_DEADLINE_SECONDS = 600
_FLASH_PEAK_PRICING = TokenPricing(
    input_usd_per_million_tokens=0.44,
    output_usd_per_million_tokens=1.32,
    cached_input_usd_per_million_tokens=0.014,
)
_FLASH_OFF_PEAK_PRICING = TokenPricing(
    input_usd_per_million_tokens=0.22,
    output_usd_per_million_tokens=0.66,
    cached_input_usd_per_million_tokens=0.007,
)


class RealEvaluationBlocked(RuntimeError):
    pass


class _FailFastSupplierError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _FailFastEvaluationModel:
    def __init__(
        self,
        delegate: AuditedInvestigationEvaluationModel,
        records: list[ModelCallAttemptRecord],
    ) -> None:
        self._delegate = delegate
        self._records = records

    async def evaluate(self, model_input):
        try:
            validate_investigation_judgment_input(model_input)
        except InvestigationJudgmentFailure:
            return await self._delegate.evaluate(model_input)
        if len(self._records) >= _MAX_PROVIDER_ATTEMPTS:
            raise _FailFastSupplierError("CALL_BUDGET_EXHAUSTED")
        offset = len(self._records)
        result = await self._delegate.evaluate(model_input)
        new_records = self._records[offset:]
        if len(self._records) > _MAX_PROVIDER_ATTEMPTS:
            raise _FailFastSupplierError("CALL_BUDGET_EXHAUSTED")
        if not new_records:
            return result
        final = new_records[-1]
        reason = supplier_block_reason(final)
        if reason is not None:
            raise _FailFastSupplierError(reason)
        return result


def _validate_environment(environment: Mapping[str, str]) -> None:
    if environment.get("DEEPSEEK_REAL_EVALUATION") != ISSUE_125_OPT_IN:
        raise RealEvaluationBlocked("OPT_IN_REQUIRED")
    if not environment.get("DEEPSEEK_API_KEY", "").strip():
        raise RealEvaluationBlocked("MISSING_API_KEY")
    if environment.get("DEEPSEEK_MODEL", DEEPSEEK_FLASH_MODEL) != DEEPSEEK_FLASH_MODEL:
        raise RealEvaluationBlocked("UNSUPPORTED_MODEL")


def deepseek_flash_pricing_at(observed_at: datetime) -> tuple[str, TokenPricing]:
    tier = time_of_use_tier_at(observed_at)
    if tier == "peak":
        return "peak", _FLASH_PEAK_PRICING
    return "off-peak", _FLASH_OFF_PEAK_PRICING


async def run_real_evaluation(
    environment: Mapping[str, str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    pricing_observed_at: datetime | None = None,
) -> dict[str, object]:
    _validate_environment(environment)
    observed_at = pricing_observed_at or datetime.now(UTC)
    pricing_tier, pricing = deepseek_flash_pricing_at(observed_at)
    audit = InMemoryModelCallAuditSink()
    config = DeepSeekResponsesConfig(
        api_key=environment["DEEPSEEK_API_KEY"],
        model=environment.get("DEEPSEEK_MODEL", DEEPSEEK_FLASH_MODEL),
        connect_timeout_seconds=3,
        read_timeout_seconds=12,
        deadline_seconds=20,
        max_attempts=1,
        retry_base_delay_seconds=0,
        max_output_tokens=128,
    )
    model = DeepSeekResponsesInvestigationModel(
        config,
        transport=transport,
        audit_sink=audit,
    )
    evaluated = AuditedInvestigationEvaluationModel(model, audit.records, pricing)
    fail_fast = _FailFastEvaluationModel(evaluated, audit.records)
    scenarios = synthetic_evaluation_scenarios() * _DATASET_REPETITIONS
    evaluation: dict[str, object] | None = None
    blocked_reason: str | None = None
    try:
        report = await asyncio.wait_for(
            evaluate_candidate(
                DEEPSEEK_FLASH_MODEL,
                fail_fast,
                scenarios,
                real_model_invoked=True,
            ),
            timeout=_WHOLE_EVALUATION_DEADLINE_SECONDS,
        )
        evaluation = report.to_dict()
    except TimeoutError:
        blocked_reason = "EVALUATION_DEADLINE_EXCEEDED"
    except _FailFastSupplierError as error:
        blocked_reason = error.reason
    if (
        pricing_observed_at is None
        and deepseek_flash_pricing_at(datetime.now(UTC))[0] != pricing_tier
        and blocked_reason is None
    ):
        blocked_reason = "PRICING_WINDOW_CHANGED"
    return _aggregate_report(
        evaluation,
        audit.records,
        blocked_reason,
        pricing_tier,
        pricing,
        observed_at,
    )


def _aggregate_report(
    evaluation: dict[str, object] | None,
    records: list[ModelCallAttemptRecord],
    blocked_reason: str | None,
    pricing_tier: str,
    pricing: TokenPricing,
    pricing_observed_at: datetime,
) -> dict[str, object]:
    successful = [record for record in records if record.failure_classification is None]
    contract_checks = {
        "strictSchema": bool(records) and all(record.strict_schema_requested for record in records),
        "completedStatus": bool(successful)
        and all(record.response_status == "completed" for record in successful),
        "thinkingDisabled": bool(records) and all(record.thinking_disabled for record in records),
        "allowedParametersOnly": bool(records)
        and all(record.allowed_parameters_only for record in records),
        "requestTracking": bool(successful)
        and all(
            record.internal_call_id and record.attempt_id and record.provider_response_id
            for record in successful
        ),
        "actualResponseShape": bool(successful)
        and all(record.actual_response_shape_valid for record in successful),
        "usageReported": bool(successful) and all(record.usage_reported for record in successful),
        "cacheReported": bool(successful)
        and all(record.cache_metrics_reported for record in successful),
    }
    retries = sum(max(0, record.attempt_number - 1) for record in records)
    usage = {
        "inputTokens": sum(record.input_tokens or 0 for record in records),
        "outputTokens": sum(record.output_tokens or 0 for record in records),
        "totalTokens": sum(record.total_tokens or 0 for record in records),
        "cachedInputTokens": sum(record.cached_tokens or 0 for record in records),
        "cacheHitAttempts": sum(record.cache_hit is True for record in records),
        "measuredAttempts": sum(record.usage_reported for record in records),
        "unmeasuredAttempts": sum(not record.usage_reported for record in records),
    }
    admitted = bool(
        evaluation
        and evaluation.get("admitted") is True
        and all(contract_checks.values())
        and blocked_reason is None
    )
    if evaluation is not None:
        evaluation = {**evaluation, "admitted": admitted}
    return {
        "schemaVersion": _REPORT_SCHEMA_VERSION,
        "candidateModel": DEEPSEEK_FLASH_MODEL,
        "pricingVersion": DEEPSEEK_PRICING_VERSION,
        "pricingTier": pricing_tier,
        "pricingObservedAtUtc": pricing_observed_at.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "pricingUsdPerMillionTokens": {
            "cachedInput": pricing.cached_input_usd_per_million_tokens,
            "uncachedInput": pricing.input_usd_per_million_tokens,
            "output": pricing.output_usd_per_million_tokens,
        },
        "limits": {
            "datasetRepetitions": _DATASET_REPETITIONS,
            "maximumProviderAttempts": _MAX_PROVIDER_ATTEMPTS,
            "maximumAttemptsPerScenario": 1,
            "connectTimeoutSeconds": 3,
            "readTimeoutSeconds": 12,
            "callDeadlineSeconds": 20,
            "evaluationDeadlineSeconds": _WHOLE_EVALUATION_DEADLINE_SECONDS,
        },
        "attempts": {
            "actual": len(records),
            "maximum": _MAX_PROVIDER_ATTEMPTS,
            "retries": retries,
        },
        "contractChecks": contract_checks,
        "usage": usage,
        "evaluation": evaluation,
        "blockedReason": blocked_reason,
    }


async def _main() -> None:
    report = await run_real_evaluation(os.environ)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["blockedReason"] is not None or not report["evaluation"]:
        raise SystemExit(2)
    evaluation = report["evaluation"]
    if not isinstance(evaluation, dict) or evaluation.get("admitted") is not True:
        raise SystemExit(3)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
