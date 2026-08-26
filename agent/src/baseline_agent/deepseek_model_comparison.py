from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from baseline_agent.deepseek_investigation_model import (
    DeepSeekResponsesConfig,
    DeepSeekResponsesInvestigationModel,
    InMemoryModelCallAuditSink,
    ModelCallAttemptRecord,
)
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

ISSUE_130_OPT_IN = "issue-130-authorized-flash-pro-comparison"
FLASH_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"
_CANDIDATE_MODELS = (FLASH_MODEL, PRO_MODEL)
_REPORT_SCHEMA_VERSION = "issue-130-deepseek-model-comparison-v1"
_PRICING_VERSION = "deepseek-cny-time-of-use-observed-2026-08-26"
_DATASET_VERSION = "b0-synthetic-evaluation-v1"
_DATASET_REPETITIONS = 5
_SCENARIOS_PER_MODEL = 60
_MAX_PROVIDER_ATTEMPTS_PER_MODEL = 55
_MAX_TOTAL_PROVIDER_ATTEMPTS = 110
_MAX_ATTEMPTS_PER_SCENARIO = 1
_MAX_INPUT_TOKENS_PER_ATTEMPT = 4_096
_MAX_OUTPUT_TOKENS_PER_ATTEMPT = 128
_MAX_SPEND_CNY = 6.0
_WHOLE_COMPARISON_DEADLINE_SECONDS = 1_200
_DATASET_CONTENT_SHA256 = "1fe533a688f65115893ca0499c3c9ec858bccf3b1c2784decd59cb9c7d74b394"


class ModelComparisonBlocked(RuntimeError):
    pass


class _StopComparison(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CnyTokenPricing:
    cached_input: float
    uncached_input: float
    output: float


_OFF_PEAK_PRICING = {
    FLASH_MODEL: CnyTokenPricing(cached_input=0.05, uncached_input=1.5, output=4.5),
    PRO_MODEL: CnyTokenPricing(cached_input=0.15, uncached_input=4.5, output=13.5),
}
_PEAK_PRICING = {
    FLASH_MODEL: CnyTokenPricing(cached_input=0.10, uncached_input=3.0, output=9.0),
    PRO_MODEL: CnyTokenPricing(cached_input=0.30, uncached_input=9.0, output=27.0),
}


def deepseek_pricing_at(
    observed_at: datetime,
) -> tuple[str, dict[str, CnyTokenPricing]]:
    if observed_at.tzinfo is None:
        raise ValueError("pricing observation must be timezone-aware")
    observed_utc = observed_at.astimezone(UTC)
    is_peak = observed_utc.weekday() < 5 and (
        1 <= observed_utc.hour < 4 or 6 <= observed_utc.hour < 10
    )
    return ("peak", _PEAK_PRICING) if is_peak else ("off-peak", _OFF_PEAK_PRICING)


def _validate_environment(environment: Mapping[str, str]) -> None:
    if environment.get("DEEPSEEK_MODEL_COMPARISON") != ISSUE_130_OPT_IN:
        raise ModelComparisonBlocked("OPT_IN_REQUIRED")
    if not environment.get("DEEPSEEK_API_KEY", "").strip():
        raise ModelComparisonBlocked("MISSING_API_KEY")
    if "DEEPSEEK_MODEL" in environment:
        raise ModelComparisonBlocked("EXTERNAL_MODEL_SELECTION_FORBIDDEN")


def _validate_dataset(scenarios) -> None:
    content_sha256 = hashlib.sha256(
        json.dumps(
            [asdict(scenario) for scenario in scenarios],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if (
        len(scenarios) != _SCENARIOS_PER_MODEL
        or not all(scenario.synthetic_business_data for scenario in scenarios)
        or content_sha256 != _DATASET_CONTENT_SHA256
    ):
        raise ModelComparisonBlocked("SYNTHETIC_DATASET_ANOMALY")


class _BudgetedFailFastModel:
    def __init__(
        self,
        delegate: AuditedInvestigationEvaluationModel,
        records: list[ModelCallAttemptRecord],
        all_records: list[ModelCallAttemptRecord],
        pricing: Mapping[str, CnyTokenPricing],
    ) -> None:
        self._delegate = delegate
        self._records = records
        self._all_records = all_records
        self._pricing = pricing

    async def evaluate(self, model_input):
        try:
            validate_investigation_judgment_input(model_input)
        except InvestigationJudgmentFailure:
            return await self._delegate.evaluate(model_input)
        if len(self._records) >= _MAX_PROVIDER_ATTEMPTS_PER_MODEL:
            raise _StopComparison("CALL_BUDGET_EXHAUSTED")
        if len(self._all_records) >= _MAX_TOTAL_PROVIDER_ATTEMPTS:
            raise _StopComparison("CALL_BUDGET_EXHAUSTED")
        budget_records = [*self._all_records, *self._records]
        if (
            _actual_cost_cny(budget_records, self._pricing)
            + _next_attempt_reserve_cny(
                self._records[0].request_model if self._records else None, self._pricing
            )
            > _MAX_SPEND_CNY
        ):
            raise _StopComparison("SPEND_BUDGET_EXHAUSTED")
        offset = len(self._records)
        result = await self._delegate.evaluate(model_input)
        new_records = self._records[offset:]
        if len(new_records) != 1:
            raise _StopComparison("ATTEMPT_ACCOUNTING_ANOMALY")
        record = new_records[0]
        supplier_reason = supplier_block_reason(record)
        if supplier_reason is not None:
            raise _StopComparison(supplier_reason)
        if _telemetry_anomaly(record):
            raise _StopComparison("PROVIDER_TELEMETRY_ANOMALY")
        if _actual_cost_cny([*self._all_records, *self._records], self._pricing) > _MAX_SPEND_CNY:
            raise _StopComparison("SPEND_BUDGET_EXCEEDED")
        return result


def _telemetry_anomaly(record: ModelCallAttemptRecord) -> bool:
    if record.failure_classification is not None:
        return False
    return bool(
        not record.usage_reported
        or not record.cache_metrics_reported
        or record.input_tokens is None
        or record.output_tokens is None
        or record.input_tokens > _MAX_INPUT_TOKENS_PER_ATTEMPT
        or record.output_tokens > _MAX_OUTPUT_TOKENS_PER_ATTEMPT
    )


def _next_attempt_reserve_cny(model: str | None, pricing: Mapping[str, CnyTokenPricing]) -> float:
    selected = (
        pricing[model]
        if model is not None and model in pricing
        else max(pricing.values(), key=lambda value: value.uncached_input + value.output)
    )
    return (
        _MAX_INPUT_TOKENS_PER_ATTEMPT * selected.uncached_input
        + _MAX_OUTPUT_TOKENS_PER_ATTEMPT * selected.output
    ) / 1_000_000


def _record_cost_cny(
    record: ModelCallAttemptRecord, pricing: Mapping[str, CnyTokenPricing]
) -> float:
    rates = pricing.get(record.request_model)
    if rates is None or record.input_tokens is None or record.output_tokens is None:
        return 0.0
    cached = record.cached_tokens or 0
    uncached = max(0, record.input_tokens - cached)
    return (
        cached * rates.cached_input
        + uncached * rates.uncached_input
        + record.output_tokens * rates.output
    ) / 1_000_000


def _actual_cost_cny(
    records: list[ModelCallAttemptRecord], pricing: Mapping[str, CnyTokenPricing]
) -> float:
    return sum(_record_cost_cny(record, pricing) for record in records)


def _preflight_maximum_cost_cny(pricing: Mapping[str, CnyTokenPricing]) -> float:
    return sum(
        _MAX_PROVIDER_ATTEMPTS_PER_MODEL
        * (
            _MAX_INPUT_TOKENS_PER_ATTEMPT * pricing[model].uncached_input
            + _MAX_OUTPUT_TOKENS_PER_ATTEMPT * pricing[model].output
        )
        / 1_000_000
        for model in _CANDIDATE_MODELS
    )


async def run_model_comparison(
    environment: Mapping[str, str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    pricing_observed_at: datetime | None = None,
) -> dict[str, object]:
    _validate_environment(environment)
    observed_at = pricing_observed_at or datetime.now(UTC)
    pricing_tier, pricing = deepseek_pricing_at(observed_at)
    preflight_maximum = _preflight_maximum_cost_cny(pricing)
    if preflight_maximum > _MAX_SPEND_CNY:
        raise ModelComparisonBlocked("PREFLIGHT_SPEND_BUDGET_EXCEEDED")
    scenarios = synthetic_evaluation_scenarios() * _DATASET_REPETITIONS
    _validate_dataset(scenarios)

    all_records: list[ModelCallAttemptRecord] = []
    candidate_reports: list[dict[str, object]] = []
    blocked_reason: str | None = None

    async def compare() -> None:
        for model_name in _CANDIDATE_MODELS:
            audit = InMemoryModelCallAuditSink()
            config = DeepSeekResponsesConfig.for_model_comparison(
                api_key=environment["DEEPSEEK_API_KEY"],
                model=model_name,
                connect_timeout_seconds=3,
                read_timeout_seconds=12,
                deadline_seconds=20,
                max_attempts=1,
                retry_base_delay_seconds=0,
                max_output_tokens=_MAX_OUTPUT_TOKENS_PER_ATTEMPT,
            )
            model = DeepSeekResponsesInvestigationModel(
                config,
                transport=transport,
                audit_sink=audit,
            )
            numeric_cny_pricing = TokenPricing(
                input_usd_per_million_tokens=pricing[model_name].uncached_input,
                output_usd_per_million_tokens=pricing[model_name].output,
                cached_input_usd_per_million_tokens=pricing[model_name].cached_input,
            )
            evaluated = AuditedInvestigationEvaluationModel(
                model, audit.records, numeric_cny_pricing
            )
            fail_fast = _BudgetedFailFastModel(evaluated, audit.records, all_records, pricing)
            try:
                evaluation = await evaluate_candidate(
                    model_name,
                    fail_fast,
                    scenarios,
                    real_model_invoked=True,
                )
            finally:
                all_records.extend(audit.records)
            candidate_reports.append(
                _candidate_report(model_name, evaluation.to_dict(), audit.records, pricing)
            )

    try:
        await asyncio.wait_for(compare(), timeout=_WHOLE_COMPARISON_DEADLINE_SECONDS)
    except TimeoutError:
        blocked_reason = "COMPARISON_DEADLINE_EXCEEDED"
    except _StopComparison as error:
        blocked_reason = error.reason

    if (
        pricing_observed_at is None
        and deepseek_pricing_at(datetime.now(UTC))[0] != pricing_tier
        and blocked_reason is None
    ):
        blocked_reason = "PRICING_WINDOW_CHANGED"

    return _comparison_report(
        candidate_reports,
        all_records,
        blocked_reason,
        pricing_tier,
        pricing,
        preflight_maximum,
        observed_at,
    )


def _candidate_report(
    model_name: str,
    evaluation: dict[str, object],
    records: list[ModelCallAttemptRecord],
    pricing: Mapping[str, CnyTokenPricing],
) -> dict[str, object]:
    evaluation.pop("admitted", None)
    evaluation.pop("thresholds", None)
    metrics = evaluation.get("metrics")
    if isinstance(metrics, dict):
        metrics["averageCostCny"] = metrics.pop("averageCostUsd")
        failed_ids = evaluation.get("failedScenarioIds")
        failed_prompt_injection = (
            sum(item == "prompt-injection" for item in failed_ids)
            if isinstance(failed_ids, list)
            else _DATASET_REPETITIONS
        )
        metrics["promptInjectionSafetyRate"] = (
            _DATASET_REPETITIONS - failed_prompt_injection
        ) / _DATASET_REPETITIONS
        provider_latencies = [record.duration_ms for record in records]
        metrics["p50LatencyMs"] = _nearest_rank(provider_latencies, 0.50)
        metrics["p95LatencyMs"] = _nearest_rank(provider_latencies, 0.95)
        metrics["latencySampleCount"] = len(provider_latencies)
        metrics["latencyPopulation"] = "provider-attempts-only"
    successful = [record for record in records if record.failure_classification is None]
    contract_checks = {
        "strictSchema": bool(records) and all(record.strict_schema_requested for record in records),
        "completedStatus": bool(successful)
        and all(record.response_status == "completed" for record in successful),
        "thinkingDisabled": bool(records) and all(record.thinking_disabled for record in records),
        "allowedParametersOnly": bool(records)
        and all(record.allowed_parameters_only for record in records),
        "actualResponseShape": bool(successful)
        and all(record.actual_response_shape_valid for record in successful),
        "usageReported": bool(records) and all(record.usage_reported for record in records),
        "cacheReported": bool(records) and all(record.cache_metrics_reported for record in records),
    }
    usage = {
        "inputTokens": sum(record.input_tokens or 0 for record in records),
        "outputTokens": sum(record.output_tokens or 0 for record in records),
        "totalTokens": sum(record.total_tokens or 0 for record in records),
        "cachedInputTokens": sum(record.cached_tokens or 0 for record in records),
        "cacheHitAttempts": sum(record.cache_hit is True for record in records),
    }
    return {
        "requestModel": model_name,
        "evaluation": evaluation,
        "attempts": {
            "actual": len(records),
            "maximum": _MAX_PROVIDER_ATTEMPTS_PER_MODEL,
            "retries": sum(max(0, record.attempt_number - 1) for record in records),
        },
        "contractChecks": contract_checks,
        "usage": usage,
        "costCny": round(_actual_cost_cny(records, pricing), 9),
        "observedProvider": {
            "responseModels": sorted(
                {record.response_model for record in records if record.response_model}
            ),
            "backendFingerprints": sorted(
                {record.backend_fingerprint for record in records if record.backend_fingerprint}
            ),
            "backendFingerprintReportedAttempts": sum(
                record.backend_fingerprint is not None for record in records
            ),
            "backendFingerprintMissingAttempts": sum(
                record.backend_fingerprint is None for record in records
            ),
            "failureClassifications": sorted(
                {
                    record.failure_classification.value
                    for record in records
                    if record.failure_classification
                }
            ),
        },
    }


def _comparison_report(
    candidates: list[dict[str, object]],
    records: list[ModelCallAttemptRecord],
    blocked_reason: str | None,
    pricing_tier: str,
    pricing: Mapping[str, CnyTokenPricing],
    preflight_maximum: float,
    observed_at: datetime,
) -> dict[str, object]:
    actual_cost = _actual_cost_cny(records, pricing)
    report: dict[str, object] = {
        "schemaVersion": _REPORT_SCHEMA_VERSION,
        "dataset": {
            "version": _DATASET_VERSION,
            "contentSha256": _DATASET_CONTENT_SHA256,
            "repetitions": _DATASET_REPETITIONS,
            "scenarioCountPerModel": _SCENARIOS_PER_MODEL,
            "providerAttemptsPerModel": _MAX_PROVIDER_ATTEMPTS_PER_MODEL,
            "identicalForAllCandidates": True,
        },
        "fixedCandidates": list(_CANDIDATE_MODELS),
        "automaticModelSwitching": False,
        "sharedContract": {
            "promptVersion": "investigation-judgment-v1",
            "schemaVersion": "investigation-judgment-v1",
            "thinking": "disabled",
            "strictJsonSchema": True,
            "maximumAttemptsPerScenario": _MAX_ATTEMPTS_PER_SCENARIO,
        },
        "pricing": {
            "version": _PRICING_VERSION,
            "tier": pricing_tier,
            "observedAtUtc": observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "cnyPerMillionTokens": {
                model: {
                    "cachedInput": rates.cached_input,
                    "uncachedInput": rates.uncached_input,
                    "output": rates.output,
                }
                for model, rates in pricing.items()
            },
        },
        "spend": {
            "maximumCny": _MAX_SPEND_CNY,
            "preflightWorstCaseCny": round(preflight_maximum, 9),
            "actualCny": round(actual_cost, 9),
            "withinBudget": actual_cost <= _MAX_SPEND_CNY,
        },
        "attempts": {
            "actual": len(records),
            "maximum": _MAX_TOTAL_PROVIDER_ATTEMPTS,
            "retries": sum(max(0, record.attempt_number - 1) for record in records),
        },
        "candidates": candidates,
        "blockedReason": blocked_reason,
    }
    report["comparison"] = _behavior_comparison(candidates)
    report["conclusion"] = _conclusion(candidates, blocked_reason)
    return report


def _metrics(candidate: dict[str, object]) -> dict[str, Any]:
    evaluation = candidate.get("evaluation")
    metrics = evaluation.get("metrics") if isinstance(evaluation, dict) else None
    return metrics if isinstance(metrics, dict) else {}


def _as_float(value: object) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _nearest_rank(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, int(len(ordered) * percentile + 0.999999999))
    return ordered[min(rank - 1, len(ordered) - 1)]


def _quality_tuple(candidate: dict[str, object]) -> tuple[float, ...]:
    metrics = _metrics(candidate)
    return (
        float(metrics.get("safetyInvariantRate", 0)),
        float(metrics.get("businessCorrectnessRate", 0)),
        float(metrics.get("schemaSuccessRate", 0)),
        float(metrics.get("promptInjectionSafetyRate", 0)),
        -float(metrics.get("failureRate", 1)),
        -float(metrics.get("refusalOrEmptyRate", 1)),
    )


def _behavior_comparison(candidates: list[dict[str, object]]) -> dict[str, object] | None:
    if len(candidates) != 2:
        return None
    flash, pro = candidates
    flash_metrics = _metrics(flash)
    pro_metrics = _metrics(pro)
    flash_provider = flash.get("observedProvider", {})
    pro_provider = pro.get("observedProvider", {})
    return {
        "qualityDeltaProMinusFlash": {
            key: round(float(pro_metrics.get(key, 0)) - float(flash_metrics.get(key, 0)), 9)
            for key in (
                "schemaSuccessRate",
                "businessCorrectnessRate",
                "safetyInvariantRate",
                "promptInjectionSafetyRate",
                "refusalOrEmptyRate",
                "failureRate",
            )
        },
        "latencyDeltaMsProMinusFlash": {
            key: int(pro_metrics.get(key, 0)) - int(flash_metrics.get(key, 0))
            for key in ("p50LatencyMs", "p95LatencyMs")
        },
        "costDeltaCnyProMinusFlash": round(
            _as_float(pro.get("costCny")) - _as_float(flash.get("costCny")), 9
        ),
        "responseModelBehaviorDiffers": flash_provider != pro_provider,
    }


def _conclusion(candidates: list[dict[str, object]], blocked_reason: str | None) -> dict[str, str]:
    if blocked_reason is not None or len(candidates) != 2:
        return {
            "decision": "INSUFFICIENT_EVIDENCE",
            "basis": "评测未完整完成或触发首错即停，不能据此改变模型选择。",
        }
    flash, pro = candidates
    all_contracts_valid = all(
        all(checks.values())
        for candidate in candidates
        if isinstance((checks := candidate.get("contractChecks")), dict)
    )
    if not all_contracts_valid:
        return {
            "decision": "INSUFFICIENT_EVIDENCE",
            "basis": "供应商契约或计量证据不完整，不能形成可靠横向结论。",
        }
    flash_quality = _quality_tuple(flash)
    pro_quality = _quality_tuple(pro)
    if pro_quality > flash_quality and _metrics(pro).get("safetyInvariantRate") == 1.0:
        return {
            "decision": "RECOMMEND_PRO",
            "basis": "相同评测契约下 Pro 的质量序列严格优于 Flash，且安全不变量全部通过。",
        }
    if flash_quality >= pro_quality and _as_float(flash.get("costCny")) <= _as_float(
        pro.get("costCny")
    ):
        return {
            "decision": "CONTINUE_FLASH",
            "basis": "Pro 未提供更高质量，Flash 在相同契约下成本不高于 Pro。",
        }
    return {
        "decision": "INSUFFICIENT_EVIDENCE",
        "basis": "质量、延迟与成本信号互有取舍，当前完整评测不足以支持切换。",
    }


async def _main() -> None:
    report = await run_model_comparison(os.environ)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["blockedReason"] is not None:
        raise SystemExit(2)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
