import json
from dataclasses import asdict

import httpx
import pytest

from baseline_agent.deepseek_intake_model import DeepSeekIntakeModel
from baseline_agent.deepseek_investigation_model import (
    DeepSeekFailureClassification,
    InMemoryModelCallAuditSink,
)
from baseline_agent.intake_model import IntakeIssue, IntakeModelInput, VisibleOrder


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "classification", "http_status", "exception_type"),
    [
        (
            "http_rejected",
            DeepSeekFailureClassification.PROVIDER_REQUEST_REJECTED,
            400,
            httpx.HTTPStatusError,
        ),
        ("read_timeout", DeepSeekFailureClassification.READ_TIMEOUT, None, httpx.ReadTimeout),
        ("invalid_json", DeepSeekFailureClassification.INVALID_JSON, 200, json.JSONDecodeError),
    ],
)
async def test_intake_provider_failures_keep_one_attempt_with_unknown_usage(
    failure: str,
    classification: DeepSeekFailureClassification,
    http_status: int | None,
    exception_type: type[Exception],
) -> None:
    private_marker = "PRIVATE_PROVIDER_FAILURE_NOT_FOR_AUDIT"
    requests: list[httpx.Request] = []
    audit = InMemoryModelCallAuditSink()

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "read_timeout":
            raise httpx.ReadTimeout(private_marker, request=request)
        return httpx.Response(400 if failure == "http_rejected" else 200, text=private_marker)

    model = DeepSeekIntakeModel(
        "synthetic-test-key", transport=httpx.MockTransport(provider), audit_sink=audit
    )
    with pytest.raises(exception_type):
        await model.understand(_clarifying_intake_input())

    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert len(audit.records) == 1
    attempt = audit.records[0]
    assert attempt.attempt_number == 1
    assert attempt.failure_classification is classification
    assert attempt.provider_http_status == http_status
    assert (attempt.input_tokens, attempt.output_tokens, attempt.total_tokens) == (None, None, None)
    assert attempt.cached_tokens is None
    assert attempt.usage_reported is False
    assert attempt.actual_response_shape_valid is False
    assert private_marker not in json.dumps(asdict(attempt))


def _clarifying_intake_input() -> IntakeModelInput:
    return IntakeModelInput(
        customer_message="是的，确实有这个问题",
        visible_orders=(VisibleOrder("ORDER-230", "合成订单"),),
        current_order_reference="ORDER-230",
        current_pending_issue_kinds=("DUPLICATE_CHARGE",),
    )


def _completed_intake_response() -> dict:
    return {
        "id": "response-intake-230",
        "status": "completed",
        "model": "deepseek-v4-flash",
        "system_fingerprint": "synthetic-intake-fingerprint",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"answer":"AFFIRMED"}'}],
            }
        ],
        "usage": {
            "input_tokens": 80,
            "output_tokens": 20,
            "total_tokens": 100,
            "input_tokens_details": {"cached_tokens": 16},
        },
    }


@pytest.mark.asyncio
async def test_successful_intake_preserves_actual_provider_attempt_usage_and_cache() -> None:
    requests: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_completed_intake_response())

    audit = InMemoryModelCallAuditSink()
    model = DeepSeekIntakeModel(
        "synthetic-test-key", transport=httpx.MockTransport(provider), audit_sink=audit
    )
    result = await model.understand(_clarifying_intake_input())

    assert result.status == "READY_TO_CONFIRM"
    assert result.issues == (IntakeIssue("DUPLICATE_CHARGE", "重复扣款"),)
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert len(audit.records) == 1
    attempt = audit.records[0]
    assert attempt.internal_call_id
    assert attempt.attempt_id
    assert attempt.attempt_number == 1
    assert attempt.provider_response_id == "response-intake-230"
    assert attempt.provider_http_status == 200
    assert attempt.request_model == "deepseek-v4-flash"
    assert attempt.response_model == "deepseek-v4-flash"
    assert attempt.prompt_version == "intake-v3"
    assert attempt.schema_version == "customer_intake_clarification"
    assert (attempt.input_tokens, attempt.output_tokens, attempt.total_tokens) == (80, 20, 100)
    assert attempt.cached_tokens == 16
    assert attempt.cache_metrics_reported is True
    assert attempt.usage_reported is True
    assert attempt.failure_classification is None


@pytest.mark.asyncio
async def test_invalid_intake_result_keeps_usage_from_successful_provider_http_response() -> None:
    payload = _completed_intake_response()
    payload["output"][0]["content"][0]["text"] = '{"answer":"NOT_A_VALID_ANSWER"}'
    audit = InMemoryModelCallAuditSink()
    model = DeepSeekIntakeModel(
        "synthetic-test-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        audit_sink=audit,
    )

    with pytest.raises(ValueError, match="invalid clarification answer"):
        await model.understand(_clarifying_intake_input())

    assert len(audit.records) == 1
    attempt = audit.records[0]
    assert attempt.provider_http_status == 200
    assert (attempt.input_tokens, attempt.output_tokens, attempt.total_tokens) == (80, 20, 100)
    assert attempt.cached_tokens == 16
    assert attempt.usage_reported is True
    assert attempt.failure_classification is DeepSeekFailureClassification.SCHEMA_MISMATCH
    assert attempt.actual_response_shape_valid is False


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["AFFIRMED", "DENIED", "UNCLEAR"])
async def test_explicit_clarification_advances_only_the_head_and_keeps_existing_issues(
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

    existing = IntakeIssue("LOGISTICS_DELAY", "客户此前描述物流延迟")
    result = await DeepSeekIntakeModel(
        "synthetic-test-key", transport=httpx.MockTransport(respond)
    ).understand(
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
        final = await DeepSeekIntakeModel(
            "synthetic-test-key", transport=httpx.MockTransport(respond)
        ).understand(
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
async def test_initial_understanding_retains_both_asserted_and_uncertain_issues() -> None:
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

    result = await DeepSeekIntakeModel(
        "synthetic-test-key", transport=httpx.MockTransport(respond)
    ).understand(
        IntakeModelInput(
            customer_message="ORDER-215 的包裹没收到，而且疑似重复扣款",
            visible_orders=(VisibleOrder("ORDER-215", "合成订单"),),
        )
    )
    assert result.status == "NEEDS_CLARIFICATION"
    assert result.issues == (IntakeIssue("PACKAGE_NOT_RECEIVED", "包裹一直没收到"),)
    assert result.pending_issue_kinds == ("DUPLICATE_CHARGE",)


@pytest.mark.asyncio
async def test_order_only_intake_keeps_selected_order_when_customer_describes_issue() -> None:
    value = {
        "intent": "UNDERSTANDING",
        "status": "READY_TO_CONFIRM",
        "candidateOrderReference": "ORDER-215",
        "remainingOrderReferences": [],
        "issues": [{"kind": "PACKAGE_NOT_RECEIVED", "summary": "包裹未收到"}],
        "pendingIssueKinds": [],
        "assistantMessage": "请确认包裹未收到的问题。",
    }

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["text"]["format"]["name"] == "customer_intake_understanding"
        assert json.loads(payload["input"])["currentOrderReference"] == "ORDER-215"
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

    result = await DeepSeekIntakeModel(
        "synthetic-test-key", transport=httpx.MockTransport(respond)
    ).understand(
        IntakeModelInput(
            customer_message="包裹没收到",
            visible_orders=(
                VisibleOrder("ORDER-215", "合成订单"),
                VisibleOrder("ORDER-OTHER", "其他订单"),
            ),
            current_order_reference="ORDER-215",
        )
    )
    assert result.candidate_order_reference == "ORDER-215"
    assert result.status == "READY_TO_CONFIRM"
    assert result.issues == (IntakeIssue("PACKAGE_NOT_RECEIVED", "包裹未收到"),)
