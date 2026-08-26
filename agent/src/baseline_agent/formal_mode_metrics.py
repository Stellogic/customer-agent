from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx
import psycopg

_FORMAL_COMMUNICATION_MODE = "deepseek-v4-flash-customer-communication-formal-v1"


def aggregate_checkpoint_metrics(
    checkpoints: list[dict[str, object]], terminal_states: list[str]
) -> dict[str, object]:
    logical_calls = 0
    provider_attempts = 0
    estimated_cost_micros = 0
    communication_calls = 0
    communication_attempts = 0
    communication_cost_micros = 0
    communication_duration_ms = 0
    failures: dict[str, int] = {}
    included_states: list[str] = []
    handoff_with_model_calls = 0
    for values, terminal_state in zip(checkpoints, terminal_states, strict=True):
        if _FORMAL_COMMUNICATION_MODE not in str(values.get("model_mode", "")):
            continue
        run = values.get("investigation_run_evidence")
        judgment = values.get("investigation_judgment_evidence")
        communication = values.get("customer_communication_evidence")
        run = run if isinstance(run, dict) else {}
        judgment = judgment if isinstance(judgment, dict) else {}
        communication = communication if isinstance(communication, dict) else {}
        model_calls = run.get("modelCalls")
        action_calls = len(model_calls) if isinstance(model_calls, list) else 0
        logical_calls += (
            action_calls
            + _integer(judgment.get("logicalCalls"))
            + _integer(communication.get("logicalCalls"))
        )
        provider_attempts += (
            _integer(run.get("providerAttempts"))
            + _integer(judgment.get("providerAttempts"))
            + _integer(communication.get("providerAttempts"))
        )
        estimated_cost_micros += (
            _integer(run.get("costMicros"))
            + _integer(judgment.get("costMicros"))
            + _integer(communication.get("costMicros"))
        )
        communication_calls += _integer(communication.get("logicalCalls"))
        communication_attempts += _integer(communication.get("providerAttempts"))
        communication_cost_micros += _integer(communication.get("costMicros"))
        communication_duration_ms += _integer(communication.get("durationMs"))
        for evidence in (run, judgment, communication):
            classification = evidence.get("failureClassification")
            if isinstance(classification, str) and classification:
                failures[classification] = failures.get(classification, 0) + 1
        included_states.append(terminal_state)
        if terminal_state == "HANDED_OFF" and action_calls > 0:
            handoff_with_model_calls += 1
    return {
        "schemaVersion": "issue-129-aggregate-provider-metrics-v1",
        "model": "deepseek-v4-flash",
        "observedGenerationCount": len(included_states),
        "totalLogicalCalls": logical_calls,
        "totalProviderAttempts": provider_attempts,
        "estimatedCostMicros": estimated_cost_micros,
        "customerCommunication": {
            "logicalCalls": communication_calls,
            "providerAttempts": communication_attempts,
            "estimatedCostMicros": communication_cost_micros,
            "totalDurationMs": communication_duration_ms,
        },
        "generationResults": {
            "successCount": included_states.count("COMPLETED"),
            "handoffCount": included_states.count("HANDED_OFF"),
            "handoffWithModelCallsCount": handoff_with_model_calls,
        },
        "failureClassifications": failures,
    }


def collect_formal_metrics() -> dict[str, object]:
    connection_uri = os.environ["SPRING_FORMAL_DATABASE_URI"]
    with psycopg.connect(connection_uri) as connection:
        rows = connection.execute(
            "select thread_id, status from agent_processing_generation "
            "where thread_id is not null order by created_at, id"
        ).fetchall()
    checkpoints: list[dict[str, object]] = []
    terminal_states: list[str] = []
    for thread_id, status in rows:
        response = httpx.get(
            f"{os.environ['AGENT_SERVER_URL']}/threads/{thread_id}/state",
            headers={"Authorization": f"Bearer {os.environ['SPRING_TO_AGENT_TOKEN']}"},
            timeout=20,
        )
        if response.status_code != 200:
            raise RuntimeError("formal checkpoint metrics are incomplete")
        values = response.json().get("values")
        if isinstance(values, dict):
            checkpoints.append(values)
            terminal_states.append(str(status))
    return aggregate_checkpoint_metrics(checkpoints, terminal_states)


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-path", required=True)
    arguments = parser.parse_args()
    report = collect_formal_metrics()
    Path(arguments.report_path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    _main()
