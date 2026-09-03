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
    total_tokens = 0
    communication_calls = 0
    communication_attempts = 0
    communication_cost_micros = 0
    communication_duration_ms = 0
    communication_tokens = 0
    aggregate_action_calls = 0
    action_attempts = 0
    judgment_calls = 0
    judgment_attempts = 0
    failures: dict[str, int] = {}
    included_states: list[str] = []
    handoff_with_model_calls = 0
    usage_trusted = True
    for values, terminal_state in zip(checkpoints, terminal_states, strict=True):
        if _FORMAL_COMMUNICATION_MODE not in str(values.get("model_mode", "")):
            continue
        run = values.get("investigation_run_evidence")
        judgment = values.get("investigation_judgment_evidence")
        communication = values.get("customer_communication_evidence")
        run = run if isinstance(run, dict) else {}
        judgment = judgment if isinstance(judgment, dict) else {}
        communication = communication if isinstance(communication, dict) else {}
        for evidence in (run, judgment, communication):
            if _integer(evidence.get("providerAttempts")) > 0 and (
                _integer(evidence.get("tokens")) == 0 or _integer(evidence.get("costMicros")) == 0
            ):
                usage_trusted = False
        model_calls = run.get("modelCalls")
        action_calls = len(model_calls) if isinstance(model_calls, list) else 0
        action_attempt_count = _integer(run.get("providerAttempts"))
        judgment_call_count = _integer(judgment.get("logicalCalls"))
        judgment_attempt_count = _integer(judgment.get("providerAttempts"))
        aggregate_action_calls += action_calls
        action_attempts += action_attempt_count
        judgment_calls += judgment_call_count
        judgment_attempts += judgment_attempt_count
        logical_calls += (
            action_calls + judgment_call_count + _integer(communication.get("logicalCalls"))
        )
        provider_attempts += (
            action_attempt_count
            + judgment_attempt_count
            + _integer(communication.get("providerAttempts"))
        )
        estimated_cost_micros += (
            _integer(run.get("costMicros"))
            + _integer(judgment.get("costMicros"))
            + _integer(communication.get("costMicros"))
        )
        total_tokens += (
            _integer(run.get("tokens"))
            + _integer(judgment.get("tokens"))
            + _integer(communication.get("tokens"))
        )
        communication_calls += _integer(communication.get("logicalCalls"))
        communication_attempts += _integer(communication.get("providerAttempts"))
        communication_cost_micros += _integer(communication.get("costMicros"))
        communication_duration_ms += _integer(communication.get("durationMs"))
        communication_tokens += _integer(communication.get("tokens"))
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
        "totalTokens": total_tokens,
        "usageTrusted": usage_trusted,
        "action": {
            "promptVersion": "investigation-action-v3",
            "schemaVersion": "investigation-action-v3",
            "logicalCalls": aggregate_action_calls,
            "providerAttempts": action_attempts,
        },
        "judgment": {
            "promptVersion": "investigation-judgment-v1",
            "schemaVersion": "investigation-judgment-v1",
            "logicalCalls": judgment_calls,
            "providerAttempts": judgment_attempts,
        },
        "customerCommunication": {
            "promptVersions": ["customer-communication-v2", "customer-knowledge-communication-v1"],
            "schemaVersions": ["customer-reply-v1", "customer-reply-v2"],
            "logicalCalls": communication_calls,
            "providerAttempts": communication_attempts,
            "estimatedCostMicros": communication_cost_micros,
            "totalDurationMs": communication_duration_ms,
            "tokens": communication_tokens,
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
        if not isinstance(values, dict):
            raise RuntimeError("formal checkpoint metrics are incomplete")
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
