import httpx
import pytest

from baseline_agent.deepseek_investigation_model import (
    DeepSeekResponsesInvestigationModel,
    InMemoryModelCallAuditSink,
)
from baseline_agent.investigation_model import (
    InvestigationJudgment,
    InvestigationJudgmentInput,
    InvestigationReasonCode,
)
from baseline_agent.shadow_investigation import (
    ShadowCandidate,
    ShadowComparisonOutcome,
    compare_shadow_judgment,
    configured_shadow_candidate,
)


class _Model:
    def __init__(self, result: InvestigationJudgment | Exception) -> None:
        self.result = result
        self.calls = 0

    async def judge(self, _model_input: InvestigationJudgmentInput) -> InvestigationJudgment:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _judgment(required: bool) -> InvestigationJudgment:
    return InvestigationJudgment(
        compensation_review_required=required,
        reason_code=(
            InvestigationReasonCode.LOGISTICS_DELAY
            if required
            else InvestigationReasonCode.DELAY_UNDER_24_HOURS
        ),
    )


def _input() -> InvestigationJudgmentInput:
    return InvestigationJudgmentInput(
        order_reference="SYNTHETIC-ORDER-116",
        delay_seconds=80 * 60 * 60,
        evidence_refs=(
            "order:SYNTHETIC-ORDER-116",
            "logistics:SYNTHETIC-ORDER-116",
        ),
    )


def test_shadow_is_disabled_by_default_without_reading_deepseek_configuration() -> None:
    assert configured_shadow_candidate({}) is None
    assert configured_shadow_candidate({"DEEPSEEK_API_KEY": "must-not-be-read"}) is None


def test_enabled_shadow_requires_the_explicit_supported_mode_and_configuration() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        configured_shadow_candidate({"AGENT_INVESTIGATION_SHADOW_MODE": "fake"})

    candidate = configured_shadow_candidate(
        {
            "AGENT_INVESTIGATION_SHADOW_MODE": "deepseek",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
        }
    )
    assert candidate is not None
    assert candidate.model_name == "deepseek-v4-flash"
    assert candidate.maximum_provider_attempts == 1
    assert candidate.prompt_version == "investigation-judgment-v1"
    assert candidate.schema_version == "investigation-judgment-v1"

    offline = configured_shadow_candidate({"AGENT_INVESTIGATION_SHADOW_MODE": "offline"})
    assert offline is not None
    assert offline.model_name == "deepseek-v4-flash"
    assert offline.maximum_provider_attempts == 1
    assert isinstance(offline.model, DeepSeekResponsesInvestigationModel)


@pytest.mark.parametrize(
    ("delay_seconds", "expected"),
    [
        (24 * 60 * 60 - 1, False),
        (24 * 60 * 60, True),
        (48 * 60 * 60, True),
        (72 * 60 * 60, True),
    ],
)
@pytest.mark.asyncio
async def test_offline_shadow_exercises_the_deepseek_responses_adapter_at_policy_boundaries(
    delay_seconds: int,
    expected: bool,
) -> None:
    candidate = configured_shadow_candidate({"AGENT_INVESTIGATION_SHADOW_MODE": "offline"})
    assert candidate is not None

    judgment = await candidate.model.judge(
        InvestigationJudgmentInput(
            order_reference="SYNTHETIC-ORDER-116",
            delay_seconds=delay_seconds,
            evidence_refs=(
                "order:SYNTHETIC-ORDER-116",
                "logistics:SYNTHETIC-ORDER-116",
            ),
        )
    )

    assert judgment.compensation_review_required is expected
    assert isinstance(candidate.model, DeepSeekResponsesInvestigationModel)
    assert len(candidate.model.audit_sink.records) == 1
    assert candidate.model.audit_sink.records[0].provider_response_id == "offline-shadow-response"
    assert candidate.model.audit_sink.records[0].thinking_disabled is True


@pytest.mark.parametrize(
    ("candidate_result", "expected"),
    [
        (_judgment(True), ShadowComparisonOutcome.MATCH),
        (_judgment(False), ShadowComparisonOutcome.MISMATCH),
        (RuntimeError("raw provider response must not escape"), ShadowComparisonOutcome.FAILED),
    ],
)
@pytest.mark.asyncio
async def test_shadow_records_only_a_stable_minimal_comparison(
    candidate_result: InvestigationJudgment | Exception,
    expected: ShadowComparisonOutcome,
) -> None:
    model = _Model(candidate_result)
    candidate = ShadowCandidate(
        model=model,
        model_name="offline-deepseek-v4-flash",
        prompt_version="investigation-judgment-v1",
        schema_version="investigation-judgment-v1",
        maximum_provider_attempts=1,
    )

    first = await compare_shadow_judgment(
        ticket_id="ticket-116",
        generation_id="generation-116",
        model_input=_input(),
        baseline=_judgment(True),
        candidate=candidate,
    )
    duplicate = await compare_shadow_judgment(
        ticket_id="ticket-116",
        generation_id="generation-116",
        model_input=_input(),
        baseline=_judgment(True),
        candidate=candidate,
    )

    assert first.outcome is expected
    assert duplicate.comparison_id == first.comparison_id
    assert model.calls == 2
    checkpoint = first.as_checkpoint_value()
    assert set(checkpoint) == {
        "comparison_id",
        "ticket_id",
        "generation_id",
        "model",
        "prompt_version",
        "schema_version",
        "outcome",
        "failure_classification",
        "latency_ms",
        "provider_attempts",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "contract_valid",
        "provider_http_status",
    }
    serialized = repr(checkpoint)
    assert "SYNTHETIC-ORDER-116" not in serialized
    assert "raw provider response" not in serialized
    assert "compensation_review_required" not in serialized


@pytest.mark.asyncio
async def test_real_shadow_checkpoint_reports_safe_attempt_metrics_and_never_retries() -> None:
    requests = 0

    def supplier(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(503, json={"error": "raw provider response"})

    audit = InMemoryModelCallAuditSink()
    candidate = configured_shadow_candidate(
        {
            "AGENT_INVESTIGATION_SHADOW_MODE": "deepseek",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
        },
        transport=httpx.MockTransport(supplier),
        audit_sink=audit,
    )
    assert candidate is not None

    comparison = await compare_shadow_judgment(
        ticket_id="ticket-126",
        generation_id="generation-126",
        model_input=_input(),
        baseline=_judgment(True),
        candidate=candidate,
    )

    assert requests == 1
    assert comparison.outcome is ShadowComparisonOutcome.FAILED
    assert comparison.as_checkpoint_value() == {
        "comparison_id": comparison.comparison_id,
        "ticket_id": "ticket-126",
        "generation_id": "generation-126",
        "model": "deepseek-v4-flash",
        "prompt_version": "investigation-judgment-v1",
        "schema_version": "investigation-judgment-v1",
        "outcome": "FAILED",
        "failure_classification": "TRANSIENT_PROVIDER_ERROR",
        "latency_ms": comparison.as_checkpoint_value()["latency_ms"],
        "provider_attempts": "1",
        "input_tokens": "",
        "output_tokens": "",
        "total_tokens": "",
        "cached_input_tokens": "",
        "contract_valid": "false",
        "provider_http_status": "503",
    }
    assert "raw provider response" not in repr(comparison.as_checkpoint_value())


@pytest.mark.parametrize(
    ("fault", "expected_failure"),
    [
        ("refusal", "MODEL_REFUSAL"),
        ("timeout", "READ_TIMEOUT"),
        ("invalid-output", "INVALID_JSON"),
    ],
)
@pytest.mark.asyncio
async def test_offline_business_shadow_faults_use_the_real_adapter_and_fail_closed(
    fault: str,
    expected_failure: str,
) -> None:
    candidate = configured_shadow_candidate(
        {
            "AGENT_INVESTIGATION_SHADOW_MODE": "offline",
            "AGENT_INVESTIGATION_SHADOW_FAULT": fault,
        }
    )
    assert candidate is not None

    comparison = await compare_shadow_judgment(
        ticket_id=f"ticket-{fault}",
        generation_id=f"generation-{fault}",
        model_input=_input(),
        baseline=_judgment(True),
        candidate=candidate,
    )

    assert comparison.outcome is ShadowComparisonOutcome.FAILED
    assert comparison.failure_classification == expected_failure
    assert comparison.provider_attempts == 1
    assert comparison.contract_valid is False
