import pytest

from baseline_agent.formal_mode_metrics import (
    aggregate_checkpoint_metrics,
    collect_formal_metrics,
)


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "deepseek-v4-pro"])
def test_aggregates_only_formal_customer_communication_checkpoints_without_identifiers(
    model: str,
) -> None:
    formal = {
        "model_mode": (
            f"{model}-action-formal-v1+{model}-formal-v1+{model}-customer-communication-formal-v1"
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
    assert report["model"] == model
    assert report["models"] == [model]
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


def test_mixed_model_metrics_preserve_unknown_usage_instead_of_reporting_zero() -> None:
    report = aggregate_checkpoint_metrics(
        [
            {
                "model_mode": "deepseek-v4-flash-action-formal-v1+deepseek-v4-pro-customer-communication-formal-v1",
                "investigation_run_evidence": {
                    "modelCalls": [],
                    "providerAttempts": 0,
                    "costMicros": 0,
                },
                "investigation_judgment_evidence": {
                    "logicalCalls": 0,
                    "providerAttempts": 0,
                    "costMicros": 0,
                },
                "customer_communication_evidence": {
                    "logicalCalls": 1,
                    "providerAttempts": 1,
                    "costMicros": None,
                    "durationMs": 20,
                },
            }
        ],
        ["HANDED_OFF"],
    )
    assert report["model"] is None
    assert report["models"] == ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert report["totalLogicalCalls"] == 1
    assert report["totalProviderAttempts"] == 1
    assert report["estimatedCostMicros"] is None
    assert report["customerCommunication"]["estimatedCostMicros"] is None


def test_missing_formal_evidence_preserves_unknown_cost_and_legacy_call_counts() -> None:
    report = aggregate_checkpoint_metrics(
        [{"model_mode": "deepseek-v4-pro-customer-communication-formal-v1"}],
        ["HANDED_OFF"],
    )
    assert report["totalLogicalCalls"] == 0
    assert report["totalProviderAttempts"] == 0
    assert report["estimatedCostMicros"] is None


def test_formal_metrics_fail_closed_when_checkpoint_values_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, _: str) -> "Connection":
            return self

        def fetchall(self) -> list[tuple[str, str]]:
            return [("synthetic-thread", "COMPLETED")]

    class Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"values": None}

    monkeypatch.setenv("SPRING_FORMAL_DATABASE_URI", "synthetic-database-uri")
    monkeypatch.setenv("AGENT_SERVER_URL", "http://agent")
    monkeypatch.setenv("SPRING_TO_AGENT_TOKEN", "synthetic-token")
    monkeypatch.setattr(
        "baseline_agent.formal_mode_metrics.psycopg.connect", lambda _: Connection()
    )
    monkeypatch.setattr("baseline_agent.formal_mode_metrics.httpx.get", lambda *_, **__: Response())

    with pytest.raises(RuntimeError, match="incomplete"):
        collect_formal_metrics()
