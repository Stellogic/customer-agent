from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx
import psycopg

from baseline_agent.formal_mode_metrics import aggregate_checkpoint_metrics


def build_clarification_evidence(
    values: dict[str, object], spring_state: dict[str, str | None]
) -> dict[str, object]:
    run = values.get("investigation_run_evidence")
    run = run if isinstance(run, dict) else {}
    calls = run.get("modelCalls")
    calls = calls if isinstance(calls, list) else []
    actions = [
        str(call.get("selectedAction"))
        for call in calls
        if isinstance(call, dict) and isinstance(call.get("selectedAction"), str)
    ]
    records = values.get("investigation_actions")
    records = records if isinstance(records, list) else []
    result_codes = [
        str(record.get("resultCode"))
        for record in records
        if isinstance(record, dict) and isinstance(record.get("resultCode"), str)
    ]
    reply = values.get("customer_reply")
    reply = reply if isinstance(reply, dict) else {}
    metrics = aggregate_checkpoint_metrics([values], [spring_state["generationStatus"] or ""])
    return {
        "schemaVersion": "issue-129-clarification-retest-evidence-v1",
        "model": "deepseek-v4-flash",
        "metrics": metrics,
        "actionState": {
            "selectedActions": actions,
            "toolResultCodes": result_codes,
            "providerAttempts": int(run.get("providerAttempts", 0)),
            "checkpointTerminal": values.get("investigation_progress") is None,
        },
        "clarification": {
            "submitted": isinstance(values.get("clarification"), dict),
            "resumed": isinstance(values.get("clarification_answer"), dict),
        },
        "customerReply": {
            "generated": bool(reply),
            "intent": reply.get("intent") if isinstance(reply.get("intent"), str) else None,
        },
        "springState": spring_state,
    }


def collect_clarification_evidence() -> dict[str, object]:
    with psycopg.connect(os.environ["SPRING_FORMAL_DATABASE_URI"]) as connection:
        rows = connection.execute(
            "select g.thread_id, g.status, s.status, t.lifecycle_state, t.handling_mode, "
            "t.human_handoff_reason_code from agent_processing_generation g "
            "join agent_submission s on s.generation_id = g.id "
            "join support_ticket t on t.id = g.ticket_id "
            "where g.thread_id is not null order by g.created_at, g.id"
        ).fetchall()
    if len(rows) != 1:
        raise RuntimeError("clarification retest must observe exactly one generation")
    thread_id, generation, submission, lifecycle, handling, handoff = rows[0]
    response = httpx.get(
        f"{os.environ['AGENT_SERVER_URL']}/threads/{thread_id}/state",
        headers={"Authorization": f"Bearer {os.environ['SPRING_TO_AGENT_TOKEN']}"},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError("clarification checkpoint is unavailable")
    values = response.json().get("values")
    if not isinstance(values, dict):
        raise RuntimeError("clarification checkpoint is invalid")
    return build_clarification_evidence(
        values,
        {
            "generationStatus": str(generation),
            "submissionStatus": str(submission),
            "lifecycleState": str(lifecycle),
            "handlingMode": str(handling),
            "handoffReasonCode": str(handoff) if handoff is not None else None,
        },
    )


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-path", required=True)
    args = parser.parse_args()
    report = collect_clarification_evidence()
    Path(args.report_path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    _main()
