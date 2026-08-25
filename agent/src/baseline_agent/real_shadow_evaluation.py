from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from baseline_agent.synthetic_evaluation import (
    FLASH_SHADOW_ADMISSION_THRESHOLDS,
    TokenPricing,
)

_REPORT_SCHEMA_VERSION = "issue-126-real-business-shadow-v1"
_CANDIDATE_MODEL = "deepseek-v4-flash"
_MAXIMUM_REAL_PROVIDER_ATTEMPTS = 6
_REQUIRED_FAILURE_SIMULATIONS = frozenset({"MODEL_REFUSAL", "READ_TIMEOUT", "INVALID_JSON"})


@dataclass(frozen=True)
class RealShadowScenarioResult:
    scenario_id: str
    comparison: dict[str, str]
    side_effects_match_control: bool
    real_model_invoked: bool
    expected_failure_classification: str | None = None


def build_real_shadow_report(
    results: Sequence[RealShadowScenarioResult],
    *,
    pricing: TokenPricing,
    pricing_version: str,
    pricing_tier: str,
    prior_contract_admitted: bool,
) -> dict[str, object]:
    real = [result for result in results if result.real_model_invoked]
    simulations = [result for result in results if not result.real_model_invoked]
    attempts = sum(_integer(result.comparison, "provider_attempts") or 0 for result in real)
    retries = sum(
        max(0, (_integer(result.comparison, "provider_attempts") or 0) - 1) for result in real
    )
    latencies = sorted(_integer(result.comparison, "latency_ms") or 0 for result in real)
    measurable = [result for result in real if _usage_is_measurable(result.comparison)]
    costs = [_cost(result.comparison, pricing) for result in measurable]
    matches = sum(result.comparison.get("outcome") == "MATCH" for result in real)
    mismatches = sum(result.comparison.get("outcome") == "MISMATCH" for result in real)
    failures = sum(result.comparison.get("outcome") == "FAILED" for result in real)
    scenario_count = len(real)
    failure_classifications = Counter(
        result.comparison.get("failure_classification") or "NONE" for result in real
    )
    http_status_counts = Counter(
        status for result in real if (status := result.comparison.get("provider_http_status"))
    )
    metrics = {
        "matchRate": matches / scenario_count if scenario_count else 0.0,
        "mismatchCount": mismatches,
        "failureRate": failures / scenario_count if scenario_count else 1.0,
        "p50LatencyMs": _percentile(latencies, 0.50),
        "p95LatencyMs": _percentile(latencies, 0.95),
        "sideEffectInvariantRate": (
            sum(result.side_effects_match_control for result in results) / len(results)
            if results
            else 0.0
        ),
        "costMeasurementRate": len(measurable) / scenario_count if scenario_count else 0.0,
        "averageCostUsd": round(sum(costs) / scenario_count, 12) if scenario_count else 0.0,
    }
    usage = {
        "inputTokens": sum(_integer(result.comparison, "input_tokens") or 0 for result in real),
        "outputTokens": sum(_integer(result.comparison, "output_tokens") or 0 for result in real),
        "totalTokens": sum(_integer(result.comparison, "total_tokens") or 0 for result in real),
        "cachedInputTokens": sum(
            _integer(result.comparison, "cached_input_tokens") or 0 for result in real
        ),
    }
    failure_simulations = Counter(
        result.comparison.get("failure_classification", "") for result in simulations
    )
    simulations_valid = set(failure_simulations) == _REQUIRED_FAILURE_SIMULATIONS and all(
        result.comparison.get("outcome") == "FAILED"
        and result.comparison.get("failure_classification")
        == result.expected_failure_classification
        and result.side_effects_match_control
        for result in simulations
    )
    blocked_reason = next(
        (
            reason
            for result in real
            if (reason := supplier_block_reason(result.comparison)) is not None
        ),
        None,
    )
    thresholds = FLASH_SHADOW_ADMISSION_THRESHOLDS
    gate_met = (
        prior_contract_admitted
        and 0 < scenario_count <= _MAXIMUM_REAL_PROVIDER_ATTEMPTS
        and attempts <= _MAXIMUM_REAL_PROVIDER_ATTEMPTS
        and retries == 0
        and all(
            result.comparison.get("outcome") == "MATCH"
            and result.comparison.get("contract_valid") == "true"
            and result.side_effects_match_control
            for result in real
        )
        and metrics["matchRate"] >= thresholds.business_correctness_rate
        and metrics["failureRate"] <= thresholds.max_failure_rate
        and metrics["p50LatencyMs"] <= thresholds.max_p50_latency_ms
        and metrics["p95LatencyMs"] <= thresholds.max_p95_latency_ms
        and metrics["sideEffectInvariantRate"] >= thresholds.safety_invariant_rate
        and metrics["costMeasurementRate"] >= thresholds.minimum_cost_measurement_rate
        and metrics["averageCostUsd"] <= thresholds.max_average_cost_usd
        and simulations_valid
        and blocked_reason is None
    )
    if blocked_reason is None and not prior_contract_admitted:
        blocked_reason = "PRIOR_CONTRACT_NOT_ADMITTED"
    if blocked_reason is None and not gate_met:
        blocked_reason = "SHADOW_GATE_NOT_MET"
    return {
        "schemaVersion": _REPORT_SCHEMA_VERSION,
        "candidateModel": _CANDIDATE_MODEL,
        "priorContractAdmitted": prior_contract_admitted,
        "pricingVersion": pricing_version,
        "pricingTier": pricing_tier,
        "limits": {
            "maximumRealProviderAttempts": _MAXIMUM_REAL_PROVIDER_ATTEMPTS,
            "maximumAttemptsPerScenario": 1,
            "connectTimeoutSeconds": 3,
            "readTimeoutSeconds": 12,
            "callDeadlineSeconds": 20,
        },
        "scenarioIds": [result.scenario_id for result in results],
        "attempts": {
            "actualReal": attempts,
            "maximumReal": _MAXIMUM_REAL_PROVIDER_ATTEMPTS,
            "retries": retries,
        },
        "auditEvidence": {
            "contractValidAttempts": sum(
                result.comparison.get("contract_valid") == "true" for result in real
            ),
            "failureClassifications": dict(sorted(failure_classifications.items())),
            "httpStatusCounts": dict(sorted(http_status_counts.items())),
            "realProviderAttempts": attempts,
            "retries": retries,
        },
        "comparisonEvidence": {
            "failed": failures,
            "matches": matches,
            "mismatches": mismatches,
        },
        "metrics": metrics,
        "usage": usage,
        "failureSimulations": dict(sorted(failure_simulations.items())),
        "admittedForFormalMode": gate_met,
        "blockedReason": blocked_reason,
    }


def _integer(comparison: dict[str, str], field: str) -> int | None:
    value = comparison.get(field, "")
    return int(value) if value else None


def _usage_is_measurable(comparison: dict[str, str]) -> bool:
    return all(
        _integer(comparison, field) is not None
        for field in ("input_tokens", "output_tokens", "cached_input_tokens")
    )


def _cost(comparison: dict[str, str], pricing: TokenPricing) -> float:
    input_tokens = _integer(comparison, "input_tokens") or 0
    cached_tokens = _integer(comparison, "cached_input_tokens") or 0
    output_tokens = _integer(comparison, "output_tokens") or 0
    uncached_tokens = max(0, input_tokens - cached_tokens)
    return (
        uncached_tokens * pricing.input_usd_per_million_tokens
        + cached_tokens * pricing.cached_input_usd_per_million_tokens
        + output_tokens * pricing.output_usd_per_million_tokens
    ) / 1_000_000


def _percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    return values[max(0, math.ceil(len(values) * quantile) - 1)]


def supplier_block_reason(comparison: dict[str, str]) -> str | None:
    status = _integer(comparison, "provider_http_status")
    failure = comparison.get("failure_classification")
    if status == 402:
        return "INSUFFICIENT_BALANCE"
    if status in {401, 403, 429}:
        return "SUPPLIER_REQUEST_BLOCKED"
    if status is not None and status >= 500:
        return "SUPPLIER_UNAVAILABLE"
    if failure in {
        "CONNECTION_TIMEOUT",
        "READ_TIMEOUT",
        "DEADLINE_EXCEEDED",
        "TRANSIENT_PROVIDER_ERROR",
        "PROVIDER_FAILED",
    }:
        return "SUPPLIER_FAILURE"
    return None
