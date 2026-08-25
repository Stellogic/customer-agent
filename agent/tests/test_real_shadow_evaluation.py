import json

from baseline_agent.real_shadow_evaluation import (
    RealShadowScenarioResult,
    build_real_shadow_report,
)
from baseline_agent.synthetic_evaluation import TokenPricing

PRICING = TokenPricing(
    input_usd_per_million_tokens=0.44,
    output_usd_per_million_tokens=1.32,
    cached_input_usd_per_million_tokens=0.014,
)


def _comparison(
    outcome: str = "MATCH",
    *,
    failure: str = "",
    status: str = "200",
) -> dict[str, str]:
    return {
        "comparison_id": "a" * 64,
        "ticket_id": "ticket-must-not-be-reported",
        "generation_id": "generation-must-not-be-reported",
        "model": "deepseek-v4-flash",
        "prompt_version": "investigation-judgment-v1",
        "schema_version": "investigation-judgment-v1",
        "outcome": outcome,
        "failure_classification": failure,
        "latency_ms": "800",
        "provider_attempts": "1",
        "input_tokens": "100",
        "output_tokens": "10",
        "total_tokens": "110",
        "cached_input_tokens": "20",
        "contract_valid": "true" if outcome != "FAILED" else "false",
        "provider_http_status": status,
    }


def test_report_aggregates_real_business_shadow_without_raw_business_or_model_text() -> None:
    real = [
        RealShadowScenarioResult(
            scenario_id=scenario_id,
            comparison=_comparison(),
            side_effects_match_control=True,
            real_model_invoked=True,
        )
        for scenario_id in ("normal", "boundary-24h", "ineligible-under-24h")
    ]
    faults = [
        RealShadowScenarioResult(
            scenario_id=scenario_id,
            comparison=_comparison("FAILED", failure=failure, status=""),
            side_effects_match_control=True,
            real_model_invoked=False,
            expected_failure_classification=failure,
        )
        for scenario_id, failure in (
            ("refusal", "MODEL_REFUSAL"),
            ("timeout", "READ_TIMEOUT"),
            ("invalid-output", "INVALID_JSON"),
        )
    ]

    report = build_real_shadow_report(
        [*real, *faults],
        pricing=PRICING,
        pricing_version="deepseek-time-of-use-2026-08-25",
        pricing_tier="peak",
        prior_contract_admitted=True,
    )

    assert report["admittedForFormalMode"] is True
    assert report["blockedReason"] is None
    assert report["attempts"] == {"actualReal": 3, "maximumReal": 6, "retries": 0}
    assert report["auditEvidence"] == {
        "contractValidAttempts": 3,
        "failureClassifications": {"NONE": 3},
        "httpStatusCounts": {"200": 3},
        "realProviderAttempts": 3,
        "retries": 0,
    }
    assert report["comparisonEvidence"] == {
        "failed": 0,
        "matches": 3,
        "mismatches": 0,
    }
    assert report["metrics"] == {
        "matchRate": 1.0,
        "mismatchCount": 0,
        "failureRate": 0.0,
        "p50LatencyMs": 800,
        "p95LatencyMs": 800,
        "sideEffectInvariantRate": 1.0,
        "costMeasurementRate": 1.0,
        "averageCostUsd": 0.00004868,
    }
    assert report["usage"] == {
        "inputTokens": 300,
        "outputTokens": 30,
        "totalTokens": 330,
        "cachedInputTokens": 60,
    }
    assert report["failureSimulations"] == {
        "INVALID_JSON": 1,
        "READ_TIMEOUT": 1,
        "MODEL_REFUSAL": 1,
    }
    rendered = json.dumps(report, ensure_ascii=False)
    assert "ticket-must-not-be-reported" not in rendered
    assert "generation-must-not-be-reported" not in rendered
    assert "raw" not in rendered.lower()


def test_balance_or_supplier_failure_stops_admission_without_model_switch() -> None:
    blocked = RealShadowScenarioResult(
        scenario_id="normal",
        comparison=_comparison(
            "FAILED",
            failure="PROVIDER_REQUEST_REJECTED",
            status="402",
        ),
        side_effects_match_control=True,
        real_model_invoked=True,
    )

    report = build_real_shadow_report(
        [blocked],
        pricing=PRICING,
        pricing_version="deepseek-time-of-use-2026-08-25",
        pricing_tier="peak",
        prior_contract_admitted=True,
    )

    assert report["blockedReason"] == "INSUFFICIENT_BALANCE"
    assert report["admittedForFormalMode"] is False
    assert report["candidateModel"] == "deepseek-v4-flash"
    assert "fallback" not in json.dumps(report).lower()


def test_admission_requires_every_frozen_real_scenario() -> None:
    real = [
        RealShadowScenarioResult(
            scenario_id=scenario_id,
            comparison=_comparison(),
            side_effects_match_control=True,
            real_model_invoked=True,
        )
        for scenario_id in ("normal", "boundary-24h")
    ]
    faults = [
        RealShadowScenarioResult(
            scenario_id=scenario_id,
            comparison=_comparison("FAILED", failure=failure, status=""),
            side_effects_match_control=True,
            real_model_invoked=False,
            expected_failure_classification=failure,
        )
        for scenario_id, failure in (
            ("refusal", "MODEL_REFUSAL"),
            ("timeout", "READ_TIMEOUT"),
            ("invalid-output", "INVALID_JSON"),
        )
    ]

    report = build_real_shadow_report(
        [*real, *faults],
        pricing=PRICING,
        pricing_version="deepseek-time-of-use-2026-08-25",
        pricing_tier="peak",
        prior_contract_admitted=True,
    )

    assert report["admittedForFormalMode"] is False
    assert report["blockedReason"] == "SHADOW_GATE_NOT_MET"
