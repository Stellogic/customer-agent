import pytest

from baseline_agent.deepseek_investigation_action_model import (
    ACTION_PROMPT_VERSION,
    ACTION_SCHEMA_VERSION,
)
from baseline_agent.formal_mode_metrics import (
    aggregate_checkpoint_metrics,
    collect_formal_metrics,
)


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
            "tokens": 400,
            "failureClassification": "",
        },
        "investigation_judgment_evidence": {
            "logicalCalls": 1,
            "providerAttempts": 1,
            "costMicros": 10,
            "tokens": 100,
            "failureClassification": "",
        },
        "customer_communication_evidence": {
            "logicalCalls": 2,
            "providerAttempts": 2,
            "costMicros": 20,
            "tokens": 200,
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
    assert report["totalTokens"] == 700
    assert report["usageTrusted"] is True
    assert report["action"] == {
        "promptVersion": ACTION_PROMPT_VERSION,
        "schemaVersion": ACTION_SCHEMA_VERSION,
        "logicalCalls": 2,
        "providerAttempts": 2,
    }
    assert report["judgment"] == {
        "promptVersion": "investigation-judgment-v1",
        "schemaVersion": "investigation-judgment-v1",
        "logicalCalls": 1,
        "providerAttempts": 1,
    }
    assert report["customerCommunication"] == {
        "promptVersions": ["customer-communication-v2", "customer-knowledge-communication-v1"],
        "schemaVersions": ["customer-reply-v1", "customer-reply-v2"],
        "logicalCalls": 2,
        "providerAttempts": 2,
        "estimatedCostMicros": 20,
        "totalDurationMs": 300,
        "tokens": 200,
    }
    assert report["generationResults"] == {
        "successCount": 1,
        "handoffCount": 0,
        "handoffWithModelCallsCount": 0,
    }
    assert "thread" not in str(report).lower()


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


def test_marks_provider_usage_untrusted_when_a_real_attempt_has_no_usage() -> None:
    report = aggregate_checkpoint_metrics(
        [
            {
                "model_mode": "deepseek-v4-flash-customer-communication-formal-v1",
                "investigation_run_evidence": {
                    "modelCalls": [{"callNumber": 1}],
                    "providerAttempts": 1,
                    "failureClassification": "TRANSPORT_UNCONFIRMED",
                },
            }
        ],
        ["HANDED_OFF"],
    )

    assert report["usageTrusted"] is False
    assert report["failureClassifications"] == {"TRANSPORT_UNCONFIRMED": 1}
