"""PROTOTYPE TUI and deterministic scenarios for the stream contract."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy

from event_contract import (
    Cursor,
    apply_snapshot,
    initial_state,
    mark_access_revoked,
    mark_connected,
    mark_reset_required,
    project_raw_event,
    reduce_event,
)


TICKET_ID = "ticket-demo-001"
EPOCH = "ticket-demo-001.v1"


def snapshot(sequence: int = 2, generation_id: str = "gen-001") -> dict:
    return {
        "cursor": f"{EPOCH}:{sequence}",
        "ticket": {
            "ticketState": "INVESTIGATING",
            "currentGenerationId": generation_id,
            "investigationPhase": "ORDER_LOOKUP",
            "evidence": [],
            "operations": {},
            "pendingInput": None,
            "proposalRevisionRef": None,
            "resultCode": None,
            "failure": None,
        },
    }


def raw(kind: str, generation_id: str = "gen-001", **fields) -> dict:
    value = {
        "kind": kind,
        "ticket_id": TICKET_ID,
        "generation_id": generation_id,
        "occurred_at": "2026-08-09T10:00:00Z",
        # These simulate private upstream data. Projection must never copy them.
        "prompt": "private prompt",
        "model_output": "private model output",
        "tool_payload": {"trackingNumber": "private"},
        "checkpoint_id": "private-checkpoint",
        "run_id": "private-run",
    }
    value.update(fields)
    return value


def event(sequence: int, kind: str, generation_id: str = "gen-001", **fields) -> dict:
    projected = project_raw_event(raw(kind, generation_id, **fields), Cursor(EPOCH, sequence))
    assert projected is not None
    return projected


def run_scenarios(verbose: bool = True) -> list[dict]:
    results = []

    state = mark_connected(apply_snapshot(initial_state(), snapshot()))
    safe_event = event(3, "agent.evidence", evidence_ref="ev-logistics-1", category="LOGISTICS", safe_summary="物流轨迹显示延迟")
    serialized = json.dumps(safe_event, ensure_ascii=False)
    private_terms = ["private prompt", "private model output", "trackingNumber", "private-checkpoint", "private-run"]
    results.append(result("white_list_projection", not any(term in serialized for term in private_terms), safe_event))

    state = reduce_event(state, safe_event)
    once = deepcopy(state)
    state = reduce_event(state, safe_event)
    results.append(result("duplicate_is_idempotent", state["ticket"] == once["ticket"] and "DUPLICATE_IGNORED" in state["lastAction"], state))

    gap_state = reduce_event(once, event(5, "agent.phase", phase="POLICY_EVALUATION"))
    results.append(result("gap_requires_snapshot", gap_state["stream"]["needsSnapshot"] and "SEQUENCE_GAP" in gap_state["lastAction"], gap_state))

    reconnect = mark_connected(apply_snapshot(gap_state, snapshot(sequence=4)))
    reconnect = reduce_event(reconnect, event(5, "agent.phase", phase="POLICY_EVALUATION"))
    results.append(result("replay_after_snapshot", reconnect["stream"]["lastSequence"] == 5 and reconnect["ticket"]["investigationPhase"] == "POLICY_EVALUATION", reconnect))

    next_generation = reduce_event(reconnect, event(6, "spring.generation_activated", generation_id="gen-002"))
    stale = reduce_event(next_generation, event(7, "agent.tool", generation_id="gen-001", operation_ref="op-old", category="LOGISTICS_QUERY", status="SUCCEEDED"))
    results.append(result("stale_generation_ignored", "op-old" not in stale["ticket"]["operations"] and "STALE_GENERATION_IGNORED" in stale["lastAction"], stale))

    revoked = mark_access_revoked(stale)
    after_revoke = reduce_event(revoked, event(8, "agent.phase", generation_id="gen-002", phase="COMPLETE"))
    results.append(result("permission_revocation_stops_delivery", after_revoke["stream"]["connection"] == "CLOSED" and after_revoke["ticket"]["investigationPhase"] is None, after_revoke))

    epoch_state = mark_connected(apply_snapshot(initial_state(), snapshot()))
    foreign_epoch = event(3, "agent.phase", phase="POLICY_EVALUATION")
    foreign_epoch["id"] = "ticket-demo-001.v2:3"
    epoch_state = reduce_event(epoch_state, foreign_epoch)
    results.append(result("epoch_change_requires_snapshot", epoch_state["stream"]["needsSnapshot"] and "EPOCH_MISMATCH" in epoch_state["lastAction"], epoch_state))

    unknown = project_raw_event(raw("agent.debug", debug={"reasoning": "secret"}), Cursor(EPOCH, 3))
    results.append(result("unknown_raw_event_is_dropped", unknown is None, unknown))

    malformed_state = mark_connected(apply_snapshot(initial_state(), snapshot()))
    malformed = event(3, "agent.phase", phase="POLICY_EVALUATION")
    malformed["payload"]["prompt"] = "must not pass"
    malformed_state = reduce_event(malformed_state, malformed)
    results.append(result("malformed_product_event_requires_snapshot", malformed_state["stream"]["needsSnapshot"] and "INVALID_EVENT" in malformed_state["lastAction"], malformed_state))

    if verbose:
        for item in results:
            print(f"[{'PASS' if item['passed'] else 'FAIL'}] {item['name']}")
        print(json.dumps({"passed": sum(item["passed"] for item in results), "total": len(results)}, ensure_ascii=False))
    return results


def result(name: str, passed: bool, state) -> dict:
    return {"name": name, "passed": bool(passed), "state": state}


def interactive() -> None:
    state = mark_connected(apply_snapshot(initial_state(), snapshot()))
    sequence = 3
    while True:
        print("\x1b[2J\x1b[H", end="")
        print("\x1b[1mPROTOTYPE — 产品事件与断线恢复状态\x1b[0m")
        print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
        print("\n[a] 正常阶段事件  [d] 重复事件  [g] 序号缺口  [n] 新 generation")
        print("[s] 旧 generation 迟到事件  [r] 权限撤销  [x] reset_required  [h] 帮助  [q] 退出")
        choice = input("> ").strip().lower()
        if choice == "q":
            return
        if choice == "a":
            state = reduce_event(state, event(sequence, "agent.phase", generation_id=state["ticket"]["currentGenerationId"] or "gen-001", phase="POLICY_EVALUATION"))
            sequence += 1
        elif choice == "d":
            duplicate_sequence = max(1, state["stream"]["lastSequence"])
            state = reduce_event(state, event(duplicate_sequence, "agent.phase", generation_id=state["ticket"]["currentGenerationId"] or "gen-001", phase="POLICY_EVALUATION"))
        elif choice == "g":
            state = reduce_event(state, event(sequence + 1, "agent.phase", generation_id=state["ticket"]["currentGenerationId"] or "gen-001", phase="POLICY_EVALUATION"))
            sequence += 2
        elif choice == "n":
            state = reduce_event(state, event(sequence, "spring.generation_activated", generation_id="gen-002"))
            sequence += 1
        elif choice == "s":
            state = reduce_event(state, event(sequence, "agent.tool", generation_id="gen-001", operation_ref="op-old", category="LOGISTICS_QUERY", status="SUCCEEDED"))
            sequence += 1
        elif choice == "r":
            state = mark_access_revoked(state)
        elif choice == "x":
            state = mark_reset_required(state, "SERVER_CURSOR_EXPIRED")
        elif choice == "h":
            input("动作会显示完整 state；需要快照后应重新 GET 权威投影，再用其 cursor 建立 SSE。回车继续。")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="run deterministic scenarios")
    args = parser.parse_args()
    if args.all:
        results = run_scenarios()
        return 0 if all(item["passed"] for item in results) else 1
    interactive()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
