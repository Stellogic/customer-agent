from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from langgraph_sdk import get_sync_client

from prototype.stores import SpringAuthority


ROOT = Path(__file__).resolve().parent
SCRATCH = ROOT / "scratch"
EVIDENCE = ROOT / "evidence"
SPRING_DB = SCRATCH / "server-spring.db"
CONTEXT = SCRATCH / "server-context.json"
SERVER_URL = "http://127.0.0.1:2024"
ASSISTANT_ID = "recovery_prototype"


def client():
    return get_sync_client(url=SERVER_URL)


def save_context(value: dict[str, Any]) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    CONTEXT.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_context() -> dict[str, Any]:
    return json.loads(CONTEXT.read_text(encoding="utf-8"))


def save_phase(name: str, value: dict[str, Any]) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"agent-server-{name}.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def bootstrap() -> dict[str, Any]:
    spring = SpringAuthority(SPRING_DB)
    spring.reset()
    ticket_id = os.environ.get("PROTOTYPE_SERVER_TICKET", "TICKET-SERVER-002")
    created = spring.create_generation(ticket_id)
    spring.mark_submission_attempt(created["generation_id"])
    api = client()
    first = api.threads.create(
        thread_id=created["thread_id"],
        if_exists="do_nothing",
        metadata={"generation_id": created["generation_id"]},
    )
    # The first HTTP response is deliberately ignored. A retry/reconciliation
    # uses the deterministic thread id and must return the same resource.
    pending_before = spring.pending_submission(created["generation_id"])["status"]
    reconciled = api.threads.create(
        thread_id=created["thread_id"],
        if_exists="do_nothing",
        metadata={"generation_id": created["generation_id"]},
    )
    spring.confirm_thread(created["generation_id"], reconciled["thread_id"])
    submission_request_id = f"initial-run:{created['generation_id']}"
    # The create-run response is deliberately ignored. Spring can reconcile
    # by its stable submission id in run metadata before deciding to retry.
    api.runs.create(
        created["thread_id"],
        ASSISTANT_ID,
        input={
            "generation_id": created["generation_id"],
            "ticket_id": ticket_id,
            "steps": [],
        },
        metadata={"submission_request_id": submission_request_id},
        durability="sync",
    )
    found_run: dict[str, Any] | None = None
    for _ in range(50):
        for run in api.runs.list(created["thread_id"], limit=20):
            if run.get("metadata", {}).get("submission_request_id") == submission_request_id:
                found_run = run
                break
        if found_run:
            break
        time.sleep(0.1)
    if not found_run:
        raise RuntimeError("initial run could not be reconciled by submission_request_id")
    output = api.runs.join(created["thread_id"], found_run["run_id"])
    state = api.threads.get_state(created["thread_id"])
    runs = api.runs.list(created["thread_id"], limit=20)
    save_context({**created, "ticket_id": ticket_id})
    return {
        "client_process_id": os.getpid(),
        "thread_id": created["thread_id"],
        "first_and_reconciled_are_same": first["thread_id"] == reconciled["thread_id"],
        "pending_before_reconcile": pending_before,
        "confirmed_after_reconcile": spring.pending_submission(created["generation_id"])["status"],
        "thread_status": reconciled["status"],
        "run_count": len(runs),
        "initial_run_reconciled_by_metadata": found_run["run_id"] == runs[0]["run_id"],
        "submission_request_id": submission_request_id,
        "run_statuses": [run["status"] for run in runs],
        "state_next": state.get("next", []),
        "state_interrupts": state.get("interrupts", []),
        "output": output,
    }


def resume_with_lost_response() -> dict[str, Any]:
    context = load_context()
    spring = SpringAuthority(SPRING_DB)
    spring.arm_fault("tool_response_loss")
    api = client()
    output: Any = None
    error: str | None = None
    try:
        output = api.runs.wait(
            context["thread_id"],
            ASSISTANT_ID,
            command={"resume": "yes"},
            durability="sync",
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    state = api.threads.get_state(context["thread_id"])
    runs = api.runs.list(context["thread_id"], limit=20)
    return {
        "client_process_id": os.getpid(),
        "error": error,
        "output": output,
        "effect_count_after_loss": spring.counts()["effects"],
        "state_next": state.get("next", []),
        "run_count": len(runs),
        "run_statuses": [run["status"] for run in runs],
    }


def recover() -> dict[str, Any]:
    context = load_context()
    spring = SpringAuthority(SPRING_DB)
    api = client()
    output = api.runs.wait(
        context["thread_id"],
        ASSISTANT_ID,
        input=None,
        durability="sync",
    )
    state = api.threads.get_state(context["thread_id"])
    runs = api.runs.list(context["thread_id"], limit=20)
    events = [row["event_type"] for row in spring.snapshot()["audit"]]
    return {
        "client_process_id": os.getpid(),
        "output": output,
        "effect_count_after_recovery": spring.counts()["effects"],
        "effect_replayed": "EFFECT_REPLAYED" in events,
        "state_next": state.get("next", []),
        "run_count": len(runs),
        "run_statuses": [run["status"] for run in runs],
    }


def stale_generation() -> dict[str, Any]:
    context = load_context()
    spring = SpringAuthority(SPRING_DB)
    replacement = spring.create_generation(context["ticket_id"])
    api = client()
    initial = api.runs.wait(
        context["thread_id"],
        ASSISTANT_ID,
        input={
            "generation_id": context["generation_id"],
            "ticket_id": context["ticket_id"],
            "steps": [],
        },
        durability="sync",
    )
    rejected = api.runs.wait(
        context["thread_id"],
        ASSISTANT_ID,
        command={"resume": "yes"},
        durability="sync",
        raise_error=False,
    )
    snapshot = spring.snapshot()
    stale_events = [row for row in snapshot["audit"] if row["event_type"] == "STALE_RESULT_REJECTED"]
    return {
        "client_process_id": os.getpid(),
        "replacement_generation_id": replacement["generation_id"],
        "old_generation_interrupt_seen": bool(initial.get("__interrupt__")),
        "server_error": rejected.get("__error__"),
        "stale_audit_count": len(stale_events),
        "effect_count_unchanged": spring.counts()["effects"] == 1,
        "run_count": len(api.runs.list(context["thread_id"], limit=20)),
    }


def write_report() -> dict[str, Any]:
    bootstrap_data = json.loads((EVIDENCE / "agent-server-bootstrap.json").read_text(encoding="utf-8"))
    resume_data = json.loads((EVIDENCE / "agent-server-resume-loss.json").read_text(encoding="utf-8"))
    recover_data = json.loads((EVIDENCE / "agent-server-recover.json").read_text(encoding="utf-8"))
    stale_data = json.loads((EVIDENCE / "agent-server-stale.json").read_text(encoding="utf-8"))
    checks = {
        "deterministic_thread_reconcile": (
            bootstrap_data["first_and_reconciled_are_same"]
            and bootstrap_data["pending_before_reconcile"] == "PENDING"
            and bootstrap_data["confirmed_after_reconcile"] == "CONFIRMED"
        ),
        "initial_run_reconciled_after_lost_response": (
            bootstrap_data["initial_run_reconciled_by_metadata"]
            and bootstrap_data["run_count"] == 1
        ),
        "interrupt_persisted": bool(bootstrap_data["state_interrupts"]),
        "resume_reached_tool_and_reported_lost_response": (
            resume_data["effect_count_after_loss"] == 1
            and (
                bool(resume_data["error"])
                or bool((resume_data.get("output") or {}).get("__error__"))
            )
        ),
        "tool_commit_survived_lost_response": resume_data["effect_count_after_loss"] == 1,
        "retry_in_new_run_reused_effect": (
            recover_data["effect_count_after_recovery"] == 1
            and recover_data["effect_replayed"]
            and not recover_data["state_next"]
        ),
        "one_thread_multiple_runs": recover_data["run_count"] >= 3,
        "stale_generation_rejected_by_spring": (
            stale_data["old_generation_interrupt_seen"]
            and stale_data["server_error"]["error"] == "StaleGenerationRejected"
            and stale_data["stale_audit_count"] == 1
            and stale_data["effect_count_unchanged"]
        ),
    }
    report = {
        "checks": checks,
        "passed": all(checks.values()),
        "bootstrap": bootstrap_data,
        "resume_same_server_process": resume_data,
        "recover_same_server_process": recover_data,
        "stale_generation_same_server_process": stale_data,
        "spring_snapshot": SpringAuthority(SPRING_DB).snapshot(),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "agent-server.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    command = sys.argv[1]
    if command == "bootstrap":
        result = bootstrap()
        save_phase("bootstrap", result)
    elif command == "resume-loss":
        result = resume_with_lost_response()
        save_phase("resume-loss", result)
    elif command == "recover":
        result = recover()
        save_phase("recover", result)
    elif command == "stale":
        result = stale_generation()
        save_phase("stale", result)
    elif command == "report":
        result = write_report()
    else:
        raise SystemExit("usage: server_probe.py bootstrap|resume-loss|recover|stale|report")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
