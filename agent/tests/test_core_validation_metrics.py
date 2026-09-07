from pathlib import Path

import pytest

from baseline_agent.core_validation_metrics import aggregate_core_metrics, collect_core_metrics


def test_core_metrics_include_intake_and_keep_unknown_usage_separate_from_pending_reservation() -> None:
    def attempt(attempt_id: str, input_tokens: int | None, output_tokens: int | None) -> dict:
        return {
            "attemptId": attempt_id,
            "internalCallId": f"call-{attempt_id}",
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": (
                input_tokens + output_tokens
                if input_tokens is not None and output_tokens is not None
                else None
            ),
        }

    intake = {
        "invocationId": "intake-invocation",
        "intakeId": "intake-230",
        "evidence": {"attempts": [attempt("intake-attempt", 10, 2)]},
    }
    generations = [
        {
            "ticketId": "ticket-a",
            "generationId": "generation-a",
            "provider_call_evidence": {
                "attempts": [{**attempt("reply-a", 20, 3), "role": "communication"}]
            },
        },
        {
            "ticketId": "ticket-b",
            "generationId": "generation-b",
            "provider_call_evidence": {
                "attempts": [{**attempt("reply-b", None, None), "role": "communication"}]
            },
        },
    ]
    ledger = {
        "entries": [
            {"attemptId": "intake-attempt", "status": "SETTLED", "estimatedCostMicros": 48},
            {"attemptId": "reply-a", "status": "SETTLED", "estimatedCostMicros": 87},
            {"attemptId": "reply-b", "status": "PENDING", "reservedMicros": 1_000},
        ]
    }

    report = aggregate_core_metrics([intake], generations, ledger)

    assert report["currency"] == "CNY"
    assert report["intakeInvocations"] == 1
    assert report["logicalCalls"] == 3
    assert report["providerAttempts"] == 3
    assert report["unknownUsageAttempts"] == 1
    assert report["tokens"] is None
    assert report["knownTokens"] == 35
    assert report["estimatedCostMicros"] is None
    assert report["knownEstimatedCostMicros"] == 135
    assert report["supplierChargeMicros"] is None
    assert report["pendingReservedMicros"] == 1_000
    assert report["unattributedAttemptIds"] == []
    by_id = {item["attemptId"]: item for item in report["attempts"]}
    assert by_id["intake-attempt"]["intakeId"] == "intake-230"
    assert by_id["reply-a"]["ticketId"] == "ticket-a"
    assert by_id["reply-b"]["ticketId"] == "ticket-b"


def test_core_metrics_deduplicate_checkpoint_attempts_and_keep_retry_calls_together() -> None:
    generation = {
        "ticketId": "ticket-a",
        "generationId": "generation-a",
        "provider_call_evidence": {
            "currency": "USD",
            "costMicros": 999,
            "attempts": [
                {"attemptId": "first", "internalCallId": "reply", "inputTokens": 10, "outputTokens": 2},
                {"attemptId": "retry", "internalCallId": "reply", "inputTokens": 20, "outputTokens": 3},
            ],
        },
    }
    ledger = {
        "entries": [
            {"attemptId": "first", "status": "SETTLED", "estimatedCostMicros": 48},
            {"attemptId": "retry", "status": "SETTLED", "estimatedCostMicros": 87},
        ]
    }

    report = aggregate_core_metrics([], [generation, generation], ledger)

    assert report["logicalCalls"] == 1
    assert report["providerAttempts"] == 2
    assert report["tokens"] == 35
    assert report["estimatedCostMicros"] == 135
    assert report["supplierChargeMicros"] is None
    assert report["pendingReservedMicros"] == 0


def test_core_metrics_expose_missing_audit_and_unattributed_in_flight_reservation() -> None:
    report = aggregate_core_metrics(
        [{"invocationId": "unfinished", "intakeId": "intake-230", "evidence": None}],
        [],
        {"entries": [{"attemptId": "orphan", "status": "IN_FLIGHT", "reservedMicros": 1000}]},
    )

    assert report["missingEvidenceSources"] == 1
    assert report["logicalCalls"] is None
    assert report["providerAttempts"] is None
    assert report["knownProviderAttempts"] == 1
    assert report["tokens"] is None
    assert report["estimatedCostMicros"] is None
    assert report["knownTokens"] == 0
    assert report["knownEstimatedCostMicros"] == 0
    assert report["pendingReservedMicros"] == 0
    assert report["inFlightReservedMicros"] == 1000
    assert report["unattributedAttemptIds"] == ["orphan"]


def test_core_collector_keeps_database_owners_and_reads_current_generation_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Rows:
        def __init__(self, rows: list[tuple]) -> None:
            self.rows = rows

        def fetchall(self) -> list[tuple]:
            return self.rows

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def execute(self, sql: str) -> Rows:
            if "from intake_model_call" in sql:
                return Rows([("invocation", "intake", "SUCCEEDED", None, {"attempts": []})])
            assert "from agent_processing_generation" in sql
            return Rows([("generation", "ticket", "thread", "COMPLETED")])

    class Response:
        status_code = 200

        def json(self) -> dict:
            return {
                "values": {
                    "provider_call_evidence": {
                        "attempts": [{"attemptId": "reply", "internalCallId": "call", "inputTokens": 10, "outputTokens": 2}]
                    },
                    "customer_description": "不应进入计量报告的业务原文",
                }
            }

    urls = []

    def get(url: str, **_: object) -> Response:
        urls.append(url)
        return Response()

    monkeypatch.setenv("SPRING_FORMAL_DATABASE_URI", "synthetic-database-uri")
    monkeypatch.setenv("AGENT_SERVER_URL", "http://agent")
    monkeypatch.setenv("SPRING_TO_AGENT_TOKEN", "synthetic-token")
    monkeypatch.setattr("baseline_agent.core_validation_metrics.psycopg.connect", lambda _: Connection())
    monkeypatch.setattr("baseline_agent.core_validation_metrics.httpx.get", get)
    ledger = tmp_path / "ledger.json"
    ledger.write_text(
        '{"currency":"CNY","authorizationId":"core-230","entries":'
        '[{"attemptId":"reply","status":"SETTLED","estimatedCostMicros":48}]}',
        encoding="utf-8",
    )

    report = collect_core_metrics(ledger)

    assert urls == ["http://agent/threads/thread/state"]
    assert report["authorizationId"] == "core-230"
    assert report["providerAttempts"] == 1
    assert report["estimatedCostMicros"] == 48
    assert report["attempts"][0]["ticketId"] == "ticket"
    assert report["generationResults"] == [{"generationId": "generation", "ticketId": "ticket", "status": "COMPLETED"}]
    assert "不应进入计量报告" not in str(report)
