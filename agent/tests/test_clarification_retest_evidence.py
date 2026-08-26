from baseline_agent.clarification_retest_evidence import build_clarification_evidence


def test_builds_identifier_free_clarification_retest_evidence() -> None:
    values = {
        "model_mode": "deepseek-v4-flash-customer-communication-formal-v1",
        "investigation_run_evidence": {
            "modelCalls": [
                {"selectedAction": "CONFIRM_ORDER"},
                {"selectedAction": "REQUEST_CLARIFICATION"},
            ],
            "providerAttempts": 2,
            "costMicros": 10,
        },
        "customer_communication_evidence": {
            "logicalCalls": 2,
            "providerAttempts": 2,
            "costMicros": 8,
            "durationMs": 20,
        },
        "investigation_actions": [{"actionType": "CONFIRM_ORDER", "resultCode": "AMBIGUOUS"}],
        "clarification": {"clarificationRequestId": "not-exported"},
        "clarification_answer": {"clarificationRequestId": "not-exported"},
        "customer_reply": {"intent": "COMPENSATION_REVIEW_PENDING", "body": "not-exported"},
        "investigation_progress": None,
    }
    report = build_clarification_evidence(
        values,
        {
            "generationStatus": "COMPLETED",
            "submissionStatus": "COMPLETED",
            "lifecycleState": "INVESTIGATING",
            "handlingMode": "AGENT",
            "handoffReasonCode": None,
        },
    )

    serialized = str(report)
    assert "not-exported" not in serialized
    assert report["clarification"] == {"submitted": True, "resumed": True}
    assert report["customerReply"] == {
        "generated": True,
        "intent": "COMPENSATION_REVIEW_PENDING",
    }
