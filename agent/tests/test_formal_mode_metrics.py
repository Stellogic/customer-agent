from baseline_agent.formal_mode_metrics import aggregate_checkpoint_metrics


def test_aggregates_only_formal_customer_communication_checkpoints_without_identifiers() -> None:
    formal = {
        "model_mode": (
            "deepseek-v4-flash-action-formal-v1+deepseek-v4-flash-formal-v1+"
            "deepseek-v4-flash-customer-communication-formal-v1"
        ),
        "investigation_run_evidence": {
            "modelCalls": [{"callNumber": 1}, {"callNumber": 2}],
            "providerAttempts": 2,
            "costMicros": 40,
            "failureClassification": "",
        },
        "investigation_judgment_evidence": {
            "logicalCalls": 1,
            "providerAttempts": 1,
            "costMicros": 10,
            "failureClassification": "",
        },
        "customer_communication_evidence": {
            "logicalCalls": 2,
            "providerAttempts": 2,
            "costMicros": 20,
            "durationMs": 300,
            "failureClassification": "",
        },
    }
    report = aggregate_checkpoint_metrics(
        [formal, {"model_mode": "fixed-fake-model-v1"}], ["COMPLETED", "HANDED_OFF"]
    )

    assert report["observedGenerationCount"] == 1
    assert report["totalLogicalCalls"] == 5
    assert report["totalProviderAttempts"] == 5
    assert report["estimatedCostMicros"] == 70
    assert report["customerCommunication"] == {
        "logicalCalls": 2,
        "providerAttempts": 2,
        "estimatedCostMicros": 20,
        "totalDurationMs": 300,
    }
    assert report["generationResults"] == {
        "successCount": 1,
        "handoffCount": 0,
        "handoffWithModelCallsCount": 0,
    }
    assert "thread" not in str(report).lower()
