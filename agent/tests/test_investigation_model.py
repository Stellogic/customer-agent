import pytest

from baseline_agent.investigation_model import (
    FixedFakeInvestigationModel,
    InvestigationJudgmentFailure,
    InvestigationJudgmentFailureCode,
    InvestigationJudgmentInput,
    InvestigationReasonCode,
)


@pytest.mark.asyncio
async def test_fixed_fake_model_returns_only_a_controlled_investigation_judgment() -> None:
    model = FixedFakeInvestigationModel()

    judgment = await model.judge(
        InvestigationJudgmentInput(
            order_reference="ORDER-DELAY-001",
            delay_seconds=80 * 60 * 60,
            evidence_refs=(
                "order:ORDER-DELAY-001",
                "logistics:ORDER-DELAY-001",
            ),
        )
    )

    assert judgment.compensation_review_required is True
    assert judgment.reason_code is InvestigationReasonCode.LOGISTICS_DELAY
    assert not hasattr(judgment, "order_reference")
    assert not hasattr(judgment, "delay_seconds")
    assert not hasattr(judgment, "evidence_refs")
    assert not hasattr(judgment, "compensation_method")
    assert not hasattr(judgment, "amount")


@pytest.mark.asyncio
async def test_fixed_fake_model_preserves_the_under_24_hour_result() -> None:
    model = FixedFakeInvestigationModel()

    judgment = await model.judge(
        InvestigationJudgmentInput(
            order_reference="ORDER-DELAY-UNDER-24",
            delay_seconds=23 * 60 * 60,
            evidence_refs=(
                "order:ORDER-DELAY-UNDER-24",
                "logistics:ORDER-DELAY-UNDER-24",
            ),
        )
    )

    assert judgment.compensation_review_required is False
    assert judgment.reason_code is InvestigationReasonCode.DELAY_UNDER_24_HOURS


@pytest.mark.asyncio
async def test_fixed_fake_model_exposes_invalid_input_as_a_stable_failure() -> None:
    model = FixedFakeInvestigationModel()

    with pytest.raises(InvestigationJudgmentFailure) as captured:
        await model.judge(
            InvestigationJudgmentInput(
                order_reference="ORDER-DELAY-001",
                delay_seconds=-1,
                evidence_refs=(
                    "order:ORDER-DELAY-001",
                    "logistics:ORDER-DELAY-001",
                ),
            )
        )

    assert captured.value.code is InvestigationJudgmentFailureCode.INVALID_INPUT
    assert str(captured.value) == "investigation judgment input is invalid"


@pytest.mark.parametrize(
    "evidence_refs",
    [
        ("order:ORDER-DELAY-001", "payment:ORDER-DELAY-001"),
        (
            "order:ORDER-DELAY-001",
            "logistics:ORDER-DELAY-001",
            "raw-tool:provider-payload",
        ),
        ("order:ANOTHER-ORDER", "logistics:ANOTHER-ORDER"),
    ],
)
@pytest.mark.asyncio
async def test_fixed_fake_model_rejects_evidence_outside_the_scoped_whitelist(
    evidence_refs: tuple[str, ...],
) -> None:
    model = FixedFakeInvestigationModel()

    with pytest.raises(InvestigationJudgmentFailure) as captured:
        await model.judge(
            InvestigationJudgmentInput(
                order_reference="ORDER-DELAY-001",
                delay_seconds=80 * 60 * 60,
                evidence_refs=evidence_refs,
            )
        )

    assert captured.value.code is InvestigationJudgmentFailureCode.INVALID_INPUT
