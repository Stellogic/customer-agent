import json

import httpx
import pytest

from baseline_agent.deepseek_intake_model import DeepSeekIntakeModel
from baseline_agent.intake_model import IntakeIssue, IntakeModelInput, VisibleOrder


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["AFFIRMED", "DENIED", "UNCLEAR"])
async def test_explicit_clarification_advances_only_the_head_and_keeps_existing_issues(
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"answer": answer}),
                            }
                        ],
                    }
                ],
            },
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(respond)),
    )
    existing = IntakeIssue("LOGISTICS_DELAY", "客户此前描述物流延迟")
    result = await DeepSeekIntakeModel("synthetic-test-key").understand(
        IntakeModelInput(
            customer_message="是的，包裹至今仍未收到",
            visible_orders=(VisibleOrder("ORDER-215", "合成订单"),),
            current_order_reference="ORDER-215",
            current_issues=(existing,),
            current_pending_issue_kinds=("PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE"),
        )
    )
    assert result.intent == "UNDERSTANDING"
    assert result.status == "NEEDS_CLARIFICATION"
    assert result.candidate_order_reference == "ORDER-215"
    assert result.issues == (
        (existing, IntakeIssue("PACKAGE_NOT_RECEIVED", "包裹未收到"))
        if answer == "AFFIRMED"
        else (existing,)
    )
    assert result.pending_issue_kinds == (
        ("PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE")
        if answer == "UNCLEAR"
        else ("DUPLICATE_CHARGE",)
    )

    if answer == "AFFIRMED":
        final = await DeepSeekIntakeModel("synthetic-test-key").understand(
            IntakeModelInput(
                customer_message="是的，确实重复扣款",
                visible_orders=(VisibleOrder("ORDER-215", "合成订单"),),
                current_order_reference="ORDER-215",
                current_issues=result.issues,
                current_pending_issue_kinds=result.pending_issue_kinds,
            )
        )
        assert final.status == "READY_TO_CONFIRM"
        assert final.intent == "UNDERSTANDING"
        assert final.issues == (*result.issues, IntakeIssue("DUPLICATE_CHARGE", "重复扣款"))
        assert final.pending_issue_kinds == ()


@pytest.mark.asyncio
async def test_initial_understanding_retains_both_asserted_and_uncertain_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = {
        "candidateOrderReference": "ORDER-215",
        "remainingOrderReferences": [],
        "issueAssessments": {
            "LOGISTICS_DELAY": {"assessment": "NOT_MENTIONED", "summary": ""},
            "PACKAGE_NOT_RECEIVED": {"assessment": "ASSERTED", "summary": "包裹一直没收到"},
            "DUPLICATE_CHARGE": {"assessment": "UNCERTAIN", "summary": "疑似重复扣款"},
        },
    }

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(value)}],
                    }
                ],
            },
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            **kwargs,
            transport=httpx.MockTransport(respond),
        ),
    )
    result = await DeepSeekIntakeModel("synthetic-test-key").understand(
        IntakeModelInput(
            customer_message="ORDER-215 的包裹没收到，而且疑似重复扣款",
            visible_orders=(VisibleOrder("ORDER-215", "合成订单"),),
        )
    )
    assert result.status == "NEEDS_CLARIFICATION"
    assert result.issues == (IntakeIssue("PACKAGE_NOT_RECEIVED", "包裹一直没收到"),)
    assert result.pending_issue_kinds == ("DUPLICATE_CHARGE",)
