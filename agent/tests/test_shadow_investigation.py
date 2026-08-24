import pytest

from baseline_agent.deepseek_investigation_model import DeepSeekResponsesInvestigationModel
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
    assert candidate.prompt_version == "investigation-judgment-v1"
    assert candidate.schema_version == "investigation-judgment-v1"

    offline = configured_shadow_candidate({"AGENT_INVESTIGATION_SHADOW_MODE": "offline"})
    assert offline is not None
    assert offline.model_name == "deepseek-v4-flash"
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
    }
    serialized = repr(checkpoint)
    assert "SYNTHETIC-ORDER-116" not in serialized
    assert "raw provider response" not in serialized
    assert "compensation_review_required" not in serialized
