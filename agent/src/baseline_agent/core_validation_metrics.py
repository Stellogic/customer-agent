"""合并入单、调查和独立预算账本;缺失证据保留为未知。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx
import psycopg


def aggregate_core_metrics(
    intake_calls: list[dict[str, Any]],
    generations: list[dict[str, Any]],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    attempts: dict[str, dict[str, Any]] = {}
    missing_evidence = 0
    entries = {entry["attemptId"]: entry for entry in ledger["entries"]}
    recovered_generations: list[str] = []

    def include(evidence: object, owner: dict[str, Any]) -> None:
        nonlocal missing_evidence
        if not isinstance(evidence, dict) or not isinstance(evidence.get("attempts"), list):
            missing_evidence += 1
            return
        for attempt in evidence["attempts"]:
            attempt_id = attempt["attemptId"]
            previous = attempts.get(attempt_id)
            if previous is not None and any(
                previous.get(key) != value for key, value in owner.items()
            ):
                raise ValueError("provider attempt has conflicting business ownership")
            attempts[attempt_id] = {**attempt, **owner}

    invocations = {call["invocationId"]: call for call in intake_calls}
    for call in invocations.values():
        include(
            call.get("evidence"),
            {"invocationId": call["invocationId"], "intakeId": call.get("intakeId")},
        )
    for generation in generations:
        evidence = generation.get("provider_call_evidence")
        checkpoint_attempts = evidence.get("attempts") if isinstance(evidence, dict) else None
        owned_entries = [
            entry
            for entry in entries.values()
            if entry.get("ticketId") == generation["ticketId"]
            and entry.get("generationId") == generation["generationId"]
        ]
        # 取消可发生在 node 返回之前;请求前已持久化的归属不依赖 checkpoint 提交。
        if owned_entries:
            combined = {attempt["attemptId"]: attempt for attempt in (checkpoint_attempts or [])}
            if any(entry["attemptId"] not in combined for entry in owned_entries):
                recovered_generations.append(generation["generationId"])
            for entry in owned_entries:
                attempt = {
                    **(entry.get("attempt") or {}),
                    "attemptId": entry["attemptId"],
                    "internalCallId": entry.get("internalCallId"),
                    "role": entry["role"],
                    "inputTokens": entry.get("inputTokens"),
                    "outputTokens": entry.get("outputTokens"),
                }
                combined.setdefault(entry["attemptId"], attempt)
            evidence = {"attempts": list(combined.values())}
        include(
            evidence,
            {"ticketId": generation["ticketId"], "generationId": generation["generationId"]},
        )

    # 只采用新人民币账本的金额;checkpoint 的历史 USD costMicros 不参与相加。
    unattributed = sorted(set(entries) - set(attempts))
    for attempt_id, entry in entries.items():
        attempt = attempts.setdefault(
            attempt_id, {"attemptId": attempt_id, "role": entry.get("role")}
        )
        attempt.update(
            budgetStatus=entry["status"],
            estimatedCostMicros=entry.get("estimatedCostMicros"),
            supplierChargeMicros=entry.get("supplierChargeMicros"),
            reservedMicros=entry.get("reservedMicros"),
        )
        if attempt_id in unattributed:
            attempt.update(
                inputTokens=entry.get("inputTokens"), outputTokens=entry.get("outputTokens")
            )

    values = list(attempts.values())
    token_totals = [
        attempt["inputTokens"] + attempt["outputTokens"]
        if isinstance(attempt.get("inputTokens"), int)
        and isinstance(attempt.get("outputTokens"), int)
        else None
        for attempt in values
    ]
    known_tokens = sum(value for value in token_totals if value is not None)
    costs = [attempt.get("estimatedCostMicros") for attempt in values]
    known_cost = sum(value for value in costs if value is not None)
    supplier_charges = [attempt.get("supplierChargeMicros") for attempt in values]
    call_ids = {attempt["internalCallId"] for attempt in values if attempt.get("internalCallId")}
    return {
        "schemaVersion": "issue230-core-metrics-v1",
        "currency": "CNY",
        "intakeInvocations": len(invocations),
        "logicalCalls": (
            len(call_ids)
            if not missing_evidence and all(attempt.get("internalCallId") for attempt in values)
            else None
        ),
        "providerAttempts": len(values) if not missing_evidence else None,
        "knownProviderAttempts": len(values),
        "missingEvidenceSources": missing_evidence,
        "unknownUsageAttempts": token_totals.count(None),
        "tokens": known_tokens if not missing_evidence and None not in token_totals else None,
        "knownTokens": known_tokens,
        "estimatedCostMicros": known_cost if not missing_evidence and None not in costs else None,
        "knownEstimatedCostMicros": known_cost,
        "supplierChargeMicros": (
            sum(value for value in supplier_charges if value is not None)
            if supplier_charges and not missing_evidence and None not in supplier_charges
            else None
        ),
        "pendingReservedMicros": sum(
            entry["reservedMicros"] for entry in entries.values() if entry["status"] == "PENDING"
        ),
        "inFlightReservedMicros": sum(
            entry["reservedMicros"] for entry in entries.values() if entry["status"] == "IN_FLIGHT"
        ),
        "unattributedAttemptIds": unattributed,
        "ledgerRecoveredGenerationIds": recovered_generations,
        "attempts": values,
    }


def _generation_diagnostics(values: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics = []
    for source, role in (
        ("investigation_run_evidence", "action"),
        ("investigation_judgment_evidence", "judgment"),
        ("customer_communication_evidence", "communication"),
    ):
        evidence = values.get(source)
        if not isinstance(evidence, dict):
            continue
        if (
            not evidence.get("failureClassification")
            and evidence.get("outcome") != "HANDOFF_SELECTED"
        ):
            continue
        diagnostic = {
            "source": source,
            "role": role,
            "failureClassification": evidence["failureClassification"],
        }
        if evidence.get("outcome"):
            diagnostic["outcome"] = evidence["outcome"]
        if role == "action":
            diagnostic["modelCalls"] = [
                {key: call[key] for key in ("callNumber", "selectedAction") if key in call}
                for call in evidence.get("modelCalls", [])
            ]
        diagnostic["capabilityResults"] = [
            {key: action[key] for key in ("actionType", "resultCode") if key in action}
            for action in values.get("investigation_actions", [])
        ]
        diagnostics.append(diagnostic)
    return diagnostics


def collect_core_metrics(ledger_path: Path) -> dict[str, Any]:
    """读取本轮隔离验收数据库;checkpoint 仅用于计量,不替代产品验收。"""
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger["currency"] != "CNY":
        raise ValueError("core validation requires a CNY ledger")
    with psycopg.connect(os.environ["SPRING_FORMAL_DATABASE_URI"]) as connection:
        intake_rows = connection.execute(
            "select invocation_id, intake_id, status, spring_failure_reason, evidence "
            "from intake_model_call order by started_at, invocation_id"
        ).fetchall()
        generation_rows = connection.execute(
            "select id, ticket_id, thread_id, status "
            "from agent_processing_generation order by created_at, id"
        ).fetchall()
        rejection_rows = connection.execute(
            "select ticket_id, event_type, occurred_at from audit_event "
            "where starts_with(event_type, 'AGENT_COMMAND_REJECTED_') "
            "order by occurred_at, id"
        ).fetchall()
    intake_calls = [
        {
            "invocationId": str(invocation_id),
            "intakeId": str(intake_id) if intake_id is not None else None,
            "status": status,
            "springFailureReason": failure,
            "evidence": evidence,
        }
        for invocation_id, intake_id, status, failure, evidence in intake_rows
    ]
    generations = []
    for generation_id, ticket_id, thread_id, status in generation_rows:
        generation = {
            "generationId": str(generation_id),
            "ticketId": str(ticket_id),
            "status": status,
            "provider_call_evidence": None,
        }
        response = httpx.get(
            f"{os.environ['AGENT_SERVER_URL']}/threads/{thread_id}/state",
            headers={"Authorization": f"Bearer {os.environ['SPRING_TO_AGENT_TOKEN']}"},
            timeout=20,
        )
        if response.status_code == 404:
            generation["checkpointDiagnostic"] = "CHECKPOINT_NOT_FOUND"
            generations.append(generation)
            continue
        if response.status_code != 200:
            raise RuntimeError("core checkpoint metrics are incomplete")
        values = response.json().get("values")
        if not isinstance(values, dict):
            raise RuntimeError("core checkpoint metrics are incomplete")
        generation["provider_call_evidence"] = values.get("provider_call_evidence")
        diagnostics = _generation_diagnostics(values)
        if diagnostics:
            generation["diagnostics"] = diagnostics
        generations.append(generation)
    report = aggregate_core_metrics(intake_calls, generations, ledger)
    for generation in generations:
        if generation["generationId"] in report["ledgerRecoveredGenerationIds"]:
            generation["providerEvidenceSource"] = "BUDGET_LEDGER_SUPPLEMENT"
        for diagnostic in generation.get("diagnostics", []):
            # 同阶段调用标识用于关联,不把 Spring 拒绝改写成供应商失败。
            diagnostic["providerCalls"] = [
                {key: attempt.get(key) for key in ("attemptId", "internalCallId")}
                for attempt in report["attempts"]
                if attempt.get("generationId") == generation["generationId"]
                and attempt.get("role") == diagnostic["role"]
            ]
    report.update(
        authorizationId=ledger["authorizationId"],
        springRejections=[
            {
                "ticketId": str(ticket_id),
                "code": event_type.removeprefix("AGENT_COMMAND_REJECTED_"),
                "occurredAt": occurred_at.isoformat(),
            }
            for ticket_id, event_type, occurred_at in rejection_rows
        ],
        intakeResults=[
            {key: value for key, value in call.items() if key != "evidence"}
            for call in intake_calls
        ],
        generationResults=[
            {key: value for key, value in generation.items() if key != "provider_call_evidence"}
            for generation in generations
        ],
        notes=[
            "范围为本轮专属隔离验收数据库的全部入单调用和调查代次。",
            "金额单位为微元人民币;程序估算、供应商结算及未完成预留分别列示。",
            "null 表示证据未知;known 字段仅统计已知部分,不能代替总量。",
            "checkpoint 只提供调用计量证据,不能代替浏览器产品路径验收。",
            "springRejections 来自本轮隔离数据库的工单审计,不推断对应代次或供应商调用。",
        ],
    )
    return report


def _main() -> None:
    parser = argparse.ArgumentParser(description="汇总本轮核心验收的调用、用量及预算证据")
    parser.add_argument("--ledger-path", required=True, type=Path)
    parser.add_argument("--report-path", required=True, type=Path)
    arguments = parser.parse_args()
    report = collect_core_metrics(arguments.ledger_path)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    arguments.report_path.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    _main()
