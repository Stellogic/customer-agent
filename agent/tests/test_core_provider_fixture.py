import pytest
from support.core_provider_fixture import _intake


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,assessment",
    [
        ("NO-COMPENSATION-1", "ASSERTED"),
        ("NO-COMPENSATION-2", "NOT_MENTIONED"),
        ("PENDING-APPROVAL-2", "UNCERTAIN"),
    ],
)
async def test_logistics_fixture_covers_direct_and_both_clarification_paths(
    case: str, assessment: str
) -> None:
    reference = f"ORDER-CORE-{case}-FIXTURE"
    result = await _intake(
        "customer_intake_issue_assessments",
        {
            "customerText": f"{reference} 请解释物流状态",
            "visibleOrders": [
                {"reference": reference, "summary": "合成物流订单"},
                {"reference": "ORDER-OTHER", "summary": "其他合成订单"},
            ],
            "currentOrderReference": None,
            "currentIssueSummary": None,
            "currentIssues": [],
            "currentPendingIssueKinds": [],
            "currentRemainingOrderReferences": [],
        },
    )
    assert result["candidateOrderReference"] == reference
    assert result["issueAssessments"]["LOGISTICS_DELAY"]["assessment"] == assessment
    assert result["remainingOrderReferences"] == ["ORDER-OTHER"]
    assert result["issueAssessments"]["DUPLICATE_CHARGE"]["assessment"] == "NOT_MENTIONED"


@pytest.mark.asyncio
async def test_logistics_confirmation_is_affirmed() -> None:
    assert await _intake(
        "customer_intake_clarification",
        {"question": "请确认物流是否仍然延迟。", "customerText": "确实延迟，请核实物流状态。"},
    ) == {"answer": "AFFIRMED"}
