import pytest

from baseline_agent.customer_communication_evaluation import (
    customer_communication_scenarios,
    evaluate_customer_communication,
)
from baseline_agent.customer_communication_model import (
    CustomerCommunicationFailure,
    CustomerCommunicationFailureCode,
    CustomerCommunicationInput,
    CustomerReplyIntent,
    FixedFakeCustomerCommunicationModel,
)


@pytest.mark.asyncio
async def test_fixed_fake_has_an_independent_deterministic_evaluation_boundary() -> None:
    report = await evaluate_customer_communication(
        FixedFakeCustomerCommunicationModel(), customer_communication_scenarios()
    )

    assert report.passed is True
    assert report.scenario_count == 3
    assert report.schema_success_count == 3
    assert report.safe_reply_count == 3
    assert report.failure_count == 0


@pytest.mark.asyncio
async def test_fixed_fake_returns_a_structured_customer_reply_envelope() -> None:
    result = await FixedFakeCustomerCommunicationModel().compose(
        CustomerCommunicationInput(
            order_reference="ORDER-122",
            delay_seconds=24 * 60 * 60,
            compensation_review_required=True,
            evidence_refs=("order:ORDER-122", "logistics:ORDER-122"),
        )
    )

    assert result.intent is CustomerReplyIntent.COMPENSATION_REVIEW_PENDING
    assert result.schema_version == "customer-reply-v1"
    assert result.referenced_order == "ORDER-122"
    assert result.evidence_refs == ("order:ORDER-122", "logistics:ORDER-122")
    assert result.escalation_required is False
    assert "等待人工审批" in result.body
    assert "审批完成前不会执行补偿或退款" in result.body


@pytest.mark.asyncio
async def test_communication_input_rejects_evidence_outside_the_order_scope() -> None:
    with pytest.raises(CustomerCommunicationFailure) as failure:
        await FixedFakeCustomerCommunicationModel().compose(
            CustomerCommunicationInput(
                order_reference="ORDER-122",
                delay_seconds=1,
                compensation_review_required=False,
                evidence_refs=("order:ORDER-OTHER", "logistics:ORDER-OTHER"),
            )
        )

    assert failure.value.code is CustomerCommunicationFailureCode.INVALID_INPUT
