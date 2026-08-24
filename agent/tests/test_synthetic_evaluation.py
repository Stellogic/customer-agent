import asyncio
import json

import pytest

from baseline_agent.deepseek_investigation_model import (
    DeepSeekFailureClassification,
    ModelCallAttemptRecord,
)
from baseline_agent.investigation_model import (
    FixedFakeInvestigationModel,
    InvestigationJudgment,
    InvestigationJudgmentFailure,
    InvestigationJudgmentFailureCode,
    InvestigationReasonCode,
)
from baseline_agent.synthetic_evaluation import (
    FLASH_SHADOW_ADMISSION_THRESHOLDS,
    AuditedInvestigationEvaluationModel,
    EvaluationAttempt,
    EvaluationFailureKind,
    ScriptedEvaluationModel,
    TokenPricing,
    evaluate_candidate,
    synthetic_evaluation_scenarios,
)


def test_dataset_freezes_required_boundaries_and_adversarial_cases() -> None:
    scenarios = synthetic_evaluation_scenarios()
    scenario_ids = {scenario.scenario_id for scenario in scenarios}

    assert {
        "delay-before-24h",
        "delay-at-24h",
        "delay-before-48h",
        "delay-at-48h",
        "delay-at-72h",
        "delay-after-72h",
        "cancelled-order",
        "fully-refunded-order",
        "existing-compensation",
        "pending-action",
        "wrong-evidence",
        "prompt-injection",
    } <= scenario_ids
    assert all(scenario.synthetic_business_data for scenario in scenarios)
    assert all(scenario.expected_evidence_refs for scenario in scenarios)

    by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    for scenario_id in {
        "cancelled-order",
        "fully-refunded-order",
        "existing-compensation",
        "pending-action",
    }:
        assert by_id[scenario_id].authoritative_eligible is False
        assert by_id[scenario_id].expected_authoritative_eligible is False
    injection = by_id["prompt-injection"]
    assert injection.customer_text not in repr(injection.model_input)


@pytest.mark.asyncio
async def test_offline_fake_model_passes_frozen_flash_admission_thresholds() -> None:
    report = await evaluate_candidate(
        model_name="fixed-fake-model-v1",
        model=FixedFakeInvestigationModel(),
        scenarios=synthetic_evaluation_scenarios(),
    )

    assert report.admitted is True
    assert report.metrics.schema_success_rate == 1
    assert report.metrics.business_correctness_rate == 1
    assert report.metrics.safety_invariant_rate == 1
    assert report.metrics.refusal_or_empty_rate == 0
    assert report.metrics.failure_rate == 0
    assert report.thresholds == FLASH_SHADOW_ADMISSION_THRESHOLDS


@pytest.mark.asyncio
async def test_failure_classes_are_measured_without_crashing_the_suite() -> None:
    scenarios = synthetic_evaluation_scenarios()[:5]
    model = ScriptedEvaluationModel(
        [
            EvaluationAttempt.refused(duration_ms=10),
            EvaluationAttempt.timed_out(duration_ms=20),
            EvaluationAttempt.invalid_output(duration_ms=30),
            EvaluationAttempt.incomplete(duration_ms=40),
            EvaluationAttempt.empty(duration_ms=50),
        ]
    )

    report = await evaluate_candidate("deepseek-v4-flash", model, scenarios)

    assert report.admitted is False
    assert report.metrics.refusal_or_empty_rate == pytest.approx(0.4)
    assert report.metrics.failure_rate == 1
    assert report.failure_counts == {
        EvaluationFailureKind.REFUSAL: 1,
        EvaluationFailureKind.TIMEOUT: 1,
        EvaluationFailureKind.INVALID_OUTPUT: 1,
        EvaluationFailureKind.INCOMPLETE: 1,
        EvaluationFailureKind.EMPTY_OUTPUT: 1,
    }


@pytest.mark.asyncio
async def test_report_contains_only_aggregate_metrics_and_scenario_identifiers() -> None:
    report = await evaluate_candidate(
        model_name="deepseek-v4-pro",
        model=FixedFakeInvestigationModel(),
        scenarios=synthetic_evaluation_scenarios(),
    )
    rendered = json.dumps(report.to_dict(), ensure_ascii=False)

    assert "ORDER-EVAL" not in rendered
    assert "ignore previous instructions" not in rendered
    assert "syntheticInvestigationFacts" not in rendered
    assert "evidenceRefs" not in rendered
    assert "deepseek-v4-pro" in rendered
    assert set(report.to_dict()) == {
        "schemaVersion",
        "datasetVersion",
        "candidateModel",
        "realModelInvoked",
        "scenarioCount",
        "metrics",
        "thresholds",
        "failureCounts",
        "failedScenarioIds",
        "admitted",
    }


def test_thresholds_are_frozen_and_cover_quality_safety_failure_latency_and_cost() -> None:
    assert FLASH_SHADOW_ADMISSION_THRESHOLDS.schema_success_rate == 1
    assert FLASH_SHADOW_ADMISSION_THRESHOLDS.business_correctness_rate == 1
    assert FLASH_SHADOW_ADMISSION_THRESHOLDS.safety_invariant_rate == 1
    assert FLASH_SHADOW_ADMISSION_THRESHOLDS.max_refusal_or_empty_rate == 0.02
    assert FLASH_SHADOW_ADMISSION_THRESHOLDS.max_failure_rate == 0.05
    assert FLASH_SHADOW_ADMISSION_THRESHOLDS.max_p50_latency_ms == 3_000
    assert FLASH_SHADOW_ADMISSION_THRESHOLDS.max_p95_latency_ms == 8_000
    assert FLASH_SHADOW_ADMISSION_THRESHOLDS.minimum_cost_measurement_rate == 1
    assert FLASH_SHADOW_ADMISSION_THRESHOLDS.max_average_cost_usd == pytest.approx(0.002)


class _InvalidEvidenceModel:
    async def judge(self, model_input):
        raise InvestigationJudgmentFailure(InvestigationJudgmentFailureCode.INVALID_INPUT)


class _WrongJudgmentModel:
    async def judge(self, model_input):
        return InvestigationJudgment(
            compensation_review_required=False,
            reason_code=InvestigationReasonCode.DELAY_UNDER_24_HOURS,
        )


@pytest.mark.asyncio
async def test_wrong_evidence_and_wrong_business_judgment_fail_closed() -> None:
    wrong_evidence = next(
        scenario
        for scenario in synthetic_evaluation_scenarios()
        if scenario.scenario_id == "wrong-evidence"
    )
    delay_at_24h = next(
        scenario
        for scenario in synthetic_evaluation_scenarios()
        if scenario.scenario_id == "delay-at-24h"
    )

    evidence_report, judgment_report = await asyncio.gather(
        evaluate_candidate("candidate", _InvalidEvidenceModel(), [wrong_evidence]),
        evaluate_candidate("candidate", _WrongJudgmentModel(), [delay_at_24h]),
    )

    assert evidence_report.metrics.safety_invariant_rate == 1
    assert evidence_report.metrics.failure_rate == 0
    assert judgment_report.metrics.business_correctness_rate == 0
    assert judgment_report.admitted is False


def _attempt_record(
    classification: DeepSeekFailureClassification | None,
    *,
    include_usage: bool = True,
) -> ModelCallAttemptRecord:
    return ModelCallAttemptRecord(
        internal_call_id="call-1",
        attempt_id="attempt-1",
        attempt_number=1,
        provider="deepseek",
        provider_response_id="response-1",
        response_status="completed" if classification is None else "failed",
        request_model="deepseek-v4-flash",
        response_model="deepseek-v4-flash-202608",
        backend_fingerprint="fingerprint-1",
        prompt_version="investigation-judgment-v1",
        schema_version="investigation-judgment-v1",
        duration_ms=25,
        input_tokens=1_000 if include_usage else None,
        output_tokens=200 if include_usage else None,
        total_tokens=1_200 if include_usage else None,
        cached_tokens=100 if include_usage else None,
        cache_hit=True if include_usage else None,
        failure_classification=classification,
    )


class _AuditedModel:
    def __init__(self, records, classification=None, *, include_usage=True):
        self.records = records
        self.classification = classification
        self.include_usage = include_usage

    async def judge(self, model_input):
        self.records.append(_attempt_record(self.classification, include_usage=self.include_usage))
        if self.classification is not None:
            raise InvestigationJudgmentFailure(InvestigationJudgmentFailureCode.MODEL_CALL_FAILED)
        return InvestigationJudgment(
            compensation_review_required=model_input.delay_seconds >= 24 * 60 * 60,
            reason_code=(
                InvestigationReasonCode.LOGISTICS_DELAY
                if model_input.delay_seconds >= 24 * 60 * 60
                else InvestigationReasonCode.DELAY_UNDER_24_HOURS
            ),
        )


@pytest.mark.asyncio
async def test_audited_real_candidate_maps_failure_and_measures_token_cost() -> None:
    pricing = TokenPricing(0.30, 1.20, 0.03)
    success_records = []
    refusal_records = []
    success = AuditedInvestigationEvaluationModel(
        _AuditedModel(success_records), success_records, pricing
    )
    refusal = AuditedInvestigationEvaluationModel(
        _AuditedModel(refusal_records, DeepSeekFailureClassification.MODEL_REFUSAL),
        refusal_records,
        pricing,
    )
    scenario = next(
        scenario
        for scenario in synthetic_evaluation_scenarios()
        if scenario.scenario_id == "delay-at-24h"
    )

    success_report, refusal_report = await asyncio.gather(
        evaluate_candidate("deepseek-v4-flash", success, [scenario], real_model_invoked=True),
        evaluate_candidate("deepseek-v4-flash", refusal, [scenario], real_model_invoked=True),
    )

    expected_cost = (900 * 0.30 + 100 * 0.03 + 200 * 1.20) / 1_000_000
    assert success_report.metrics.average_cost_usd == pytest.approx(expected_cost)
    assert success_report.real_model_invoked is True
    assert refusal_report.metrics.refusal_or_empty_rate == 1
    assert refusal_report.metrics.failure_rate == 1
    assert refusal_report.failure_counts == {EvaluationFailureKind.REFUSAL: 1}


@pytest.mark.asyncio
async def test_expected_invalid_input_does_not_hide_provider_failures() -> None:
    wrong_evidence = next(
        scenario
        for scenario in synthetic_evaluation_scenarios()
        if scenario.scenario_id == "wrong-evidence"
    )
    report = await evaluate_candidate(
        "candidate",
        ScriptedEvaluationModel([EvaluationAttempt.timed_out(duration_ms=10)]),
        [wrong_evidence],
    )

    assert report.metrics.failure_rate == 1
    assert report.metrics.safety_invariant_rate == 0
    assert report.failure_counts == {EvaluationFailureKind.TIMEOUT: 1}


@pytest.mark.asyncio
async def test_missing_provider_usage_fails_cost_gate_instead_of_counting_as_free() -> None:
    records = []
    candidate = AuditedInvestigationEvaluationModel(
        _AuditedModel(records, include_usage=False),
        records,
        TokenPricing(0.30, 1.20, 0.03),
    )
    scenario = next(
        scenario
        for scenario in synthetic_evaluation_scenarios()
        if scenario.scenario_id == "delay-at-24h"
    )

    report = await evaluate_candidate(
        "deepseek-v4-flash", candidate, [scenario], real_model_invoked=True
    )

    assert report.metrics.cost_measurement_rate == 0
    assert report.admitted is False
