from __future__ import annotations

import json
import importlib.metadata
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.types import Command

from .graph_app import build_graph
from .model import ScenarioResult, SimulatedResponseLoss, StaleGenerationRejected, stable_effect_key
from .stores import AgentDirectory, SpringAuthority


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "scratch" / "core"
EVIDENCE = ROOT / "evidence"
SPRING_DB = SCRATCH / "spring.db"
AGENT_DB = SCRATCH / "agent-directory.db"
CHECKPOINT_DB = SCRATCH / "checkpoints.db"
CONTEXT_FILE = SCRATCH / "context.json"


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _write_context(context: dict[str, Any]) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    CONTEXT_FILE.write_text(json.dumps(context, indent=2), encoding="utf-8")


def _read_context() -> dict[str, Any]:
    return json.loads(CONTEXT_FILE.read_text(encoding="utf-8"))


def reset() -> None:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)
    SpringAuthority(SPRING_DB)
    AgentDirectory(AGENT_DB)


def phase_bootstrap() -> dict[str, Any]:
    spring = SpringAuthority(SPRING_DB)
    agent = AgentDirectory(AGENT_DB)
    created = spring.create_generation("TICKET-DEMO-001")
    spring.mark_submission_attempt(created["generation_id"])
    agent.create_thread(created["generation_id"], created["thread_id"])
    # Deliberately lose the create-thread response: Spring still sees PENDING.
    pending_before = spring.pending_submission(created["generation_id"])
    found = agent.get_thread(created["thread_id"])
    spring.confirm_thread(created["generation_id"], found["thread_id"])
    initial_run, _ = agent.create_run(created["thread_id"], "initial")
    graph, connection = build_graph(CHECKPOINT_DB, SPRING_DB)
    try:
        result = graph.invoke(
            {
                "generation_id": created["generation_id"],
                "ticket_id": "TICKET-DEMO-001",
                "steps": [],
            },
            _config(created["thread_id"]),
        )
        state = graph.get_state(_config(created["thread_id"]))
    finally:
        connection.close()
    context = {**created, "ticket_id": "TICKET-DEMO-001", "initial_run_id": initial_run}
    _write_context(context)
    return {
        "process_id": os.getpid(),
        "pending_before_reconcile": pending_before["status"],
        "confirmed_after_reconcile": spring.pending_submission(created["generation_id"])["status"],
        "thread_count": len(agent.snapshot()["threads"]),
        "interrupt_count": len(result.get("__interrupt__", [])),
        "next_nodes": list(state.next),
    }


def phase_resume_with_lost_tool_response() -> dict[str, Any]:
    context = _read_context()
    spring = SpringAuthority(SPRING_DB)
    agent = AgentDirectory(AGENT_DB)
    run_id, accepted = spring.register_resume(context["generation_id"], "resume-request-001", "yes")
    agent_run_id, agent_created = agent.create_run(
        context["thread_id"], "resume", request_id="resume-request-001"
    )
    spring.arm_fault("tool_response_loss")
    graph, connection = build_graph(CHECKPOINT_DB, SPRING_DB)
    lost = False
    try:
        graph.invoke(Command(resume="yes"), _config(context["thread_id"]))
    except SimulatedResponseLoss:
        lost = True
    finally:
        connection.close()
    return {
        "process_id": os.getpid(),
        "spring_resume_run_id": run_id,
        "spring_resume_accepted": accepted,
        "agent_run_id": agent_run_id,
        "agent_run_created": agent_created,
        "response_lost_after_commit": lost,
        "effect_count_after_loss": spring.counts()["effects"],
    }


def phase_recover_after_restart() -> dict[str, Any]:
    context = _read_context()
    spring = SpringAuthority(SPRING_DB)
    agent = AgentDirectory(AGENT_DB)
    duplicate_run, duplicate_accepted = spring.register_resume(
        context["generation_id"], "resume-request-001", "yes"
    )
    agent_run, agent_created = agent.create_run(
        context["thread_id"], "resume", request_id="resume-request-001"
    )
    graph, connection = build_graph(CHECKPOINT_DB, SPRING_DB)
    try:
        result = graph.invoke(None, _config(context["thread_id"]))
        state = graph.get_state(_config(context["thread_id"]))
    finally:
        connection.close()
    events = [row["event_type"] for row in spring.snapshot()["audit"]]
    return {
        "process_id": os.getpid(),
        "duplicate_resume_returned_same_run": not duplicate_accepted,
        "duplicate_run_id": duplicate_run,
        "agent_duplicate_created_new_run": agent_created,
        "agent_run_id": agent_run,
        "effect_count_after_recovery": spring.counts()["effects"],
        "effect_replayed": "EFFECT_REPLAYED" in events,
        "graph_completed": not state.next,
        "proposal": result.get("proposal"),
        "steps": result.get("steps", []),
    }


def phase_stale_generation() -> dict[str, Any]:
    context = _read_context()
    spring = SpringAuthority(SPRING_DB)
    replacement = spring.create_generation(context["ticket_id"])
    rejected = False
    try:
        spring.execute_business_tool(
            context["generation_id"],
            context["ticket_id"],
            "late-old-generation-effect",
            {"late": True},
        )
    except StaleGenerationRejected:
        rejected = True
    snapshot = spring.snapshot()
    return {
        "process_id": os.getpid(),
        "replacement_generation_id": replacement["generation_id"],
        "old_generation_rejected": rejected,
        "late_effect_created": any(
            row["idempotency_key"] == "late-old-generation-effect" for row in snapshot["effects"]
        ),
        "stale_audit_count": sum(
            row["event_type"] == "STALE_RESULT_REJECTED" for row in snapshot["audit"]
        ),
    }


def _run_phase(name: str) -> dict[str, Any]:
    command = [sys.executable, str(ROOT / "run_prototype.py"), "phase", name]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(f"phase {name} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
    return json.loads(completed.stdout)


def run_matrix() -> list[ScenarioResult]:
    reset()
    bootstrap = _run_phase("bootstrap")
    resume_loss = _run_phase("resume-loss")
    recovery = _run_phase("recover")
    stale = _run_phase("stale")
    spring = SpringAuthority(SPRING_DB)
    agent = AgentDirectory(AGENT_DB)

    results = [
        ScenarioResult(
            "可靠提交响应丢失后对账",
            bootstrap["pending_before_reconcile"] == "PENDING"
            and bootstrap["confirmed_after_reconcile"] == "CONFIRMED"
            and bootstrap["thread_count"] == 1,
            bootstrap,
        ),
        ScenarioResult(
            "一个 generation 一个 thread 且允许多个 run",
            bootstrap["thread_count"] == 1
            and len(agent.snapshot()["runs"]) == 2
            and len({row["thread_id"] for row in agent.snapshot()["runs"]}) == 1,
            agent.snapshot(),
        ),
        ScenarioResult(
            "interrupt 后跨进程 resume",
            bootstrap["interrupt_count"] == 1
            and bootstrap["next_nodes"] == ["wait_for_confirmation"]
            and recovery["graph_completed"],
            {"bootstrap": bootstrap, "recovery": recovery},
        ),
        ScenarioResult(
            "重复恢复请求幂等",
            recovery["duplicate_resume_returned_same_run"]
            and not recovery["agent_duplicate_created_new_run"],
            recovery,
        ),
        ScenarioResult(
            "工具响应丢失与同幂等键重试",
            resume_loss["response_lost_after_commit"]
            and resume_loss["effect_count_after_loss"] == 1
            and recovery["effect_count_after_recovery"] == 1
            and recovery["effect_replayed"],
            {"loss": resume_loss, "recovery": recovery},
        ),
        ScenarioResult(
            "旧 generation 迟到调用拒绝",
            stale["old_generation_rejected"]
            and not stale["late_effect_created"]
            and stale["stale_audit_count"] == 1,
            stale,
        ),
    ]

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("langgraph", "langgraph-checkpoint", "langgraph-checkpoint-sqlite", "langgraph-sdk")
        },
        "process_ids": [
            bootstrap["process_id"],
            resume_loss["process_id"],
            recovery["process_id"],
            stale["process_id"],
        ],
        "results": [result.__dict__ for result in results],
        "spring_snapshot": spring.snapshot(),
        "agent_snapshot": agent.snapshot(),
    }
    (EVIDENCE / "matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"{'PASS' if result.passed else 'FAIL'} | {result.scenario} | {json.dumps(result.evidence, ensure_ascii=False, sort_keys=True)}"
        for result in results
    ]
    (EVIDENCE / "matrix.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


def phase(name: str) -> dict[str, Any]:
    phases = {
        "bootstrap": phase_bootstrap,
        "resume-loss": phase_resume_with_lost_tool_response,
        "recover": phase_recover_after_restart,
        "stale": phase_stale_generation,
    }
    return phases[name]()


def state_snapshot() -> dict[str, Any]:
    return {
        "spring": SpringAuthority(SPRING_DB).snapshot() if SPRING_DB.exists() else {},
        "agent": AgentDirectory(AGENT_DB).snapshot() if AGENT_DB.exists() else {},
        "context": _read_context() if CONTEXT_FILE.exists() else {},
    }
