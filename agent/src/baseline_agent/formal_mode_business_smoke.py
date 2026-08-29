from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import psycopg

_SUCCESS_TEMPLATE = "ORDER-DELAY-001"
_WAIT_SECONDS = 90


def _expect(response: httpx.Response, status: int) -> None:
    if response.status_code != status:
        raise RuntimeError(f"formal-mode business request failed with HTTP {response.status_code}")


def _login(client: httpx.Client, spring_url: str) -> None:
    anonymous = client.get(f"{spring_url}/api/auth/csrf")
    _expect(anonymous, 200)
    token = anonymous.json()
    login = client.post(
        f"{spring_url}/api/auth/login",
        headers={token["headerName"]: token["token"]},
        data={"username": "customer-demo", "password": "local-demo-password"},
    )
    _expect(login, 204)
    current = client.get(f"{spring_url}/api/auth/csrf")
    _expect(current, 200)
    current_token = current.json()
    client.headers[current_token["headerName"]] = current_token["token"]


def _clone_order(connection: psycopg.Connection[Any], order_reference: str) -> None:
    connection.execute(
        "insert into synthetic_order ("
        "order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds, "
        "paid, cancelled, fully_refunded, existing_compensation, policy_version, "
        "available_compensation_amount) "
        "select %s, customer_id, paid_amount, currency, delay_hours, delay_seconds, "
        "paid, cancelled, fully_refunded, existing_compensation, policy_version, "
        "available_compensation_amount from synthetic_order where order_reference = %s",
        (order_reference, _SUCCESS_TEMPLATE),
    )


def _wait_for_terminal(connection_uri: str, ticket_id: str) -> dict[str, object]:
    deadline = time.monotonic() + _WAIT_SECONDS
    last_status: tuple[object, object] | None = None
    while time.monotonic() < deadline:
        with psycopg.connect(connection_uri) as connection:
            row = connection.execute(
                "select g.status, s.status, t.lifecycle_state, t.handling_mode, "
                "t.human_handoff_reason_code, "
                "(select count(*) from compensation_proposal_revision p where p.ticket_id = t.id), "
                "(select count(*) from agent_human_handoff_request h where h.ticket_id = t.id), "
                "g.thread_id, "
                "(select count(*) from investigation_fact f where f.generation_id = g.id), "
                "(select count(*) from agent_command_request c where c.generation_id = g.id) "
                "from agent_processing_generation g "
                "join agent_submission s on s.generation_id = g.id "
                "join support_ticket t on t.id = g.ticket_id "
                "where g.ticket_id = %s::uuid",
                (ticket_id,),
            ).fetchone()
            if row:
                last_status = (row[0], row[1])
            if row and row[0] in {"COMPLETED", "HANDED_OFF"} and row[1] == "COMPLETED":
                return {
                    "generationStatus": row[0],
                    "submissionStatus": row[1],
                    "lifecycleState": row[2],
                    "handlingMode": row[3],
                    "handoffReasonCode": row[4],
                    "proposalCount": row[5],
                    "handoffRequestCount": row[6],
                    "threadId": str(row[7]),
                    "authoritativeFactCount": row[8],
                    "agentCommandCount": row[9],
                }
        time.sleep(0.25)
    raise RuntimeError(f"formal-mode generation did not reach a terminal state: {last_status}")


def _read_autonomous_checkpoint(thread_id: str) -> dict[str, object]:
    agent_url = os.environ["AGENT_SERVER_URL"]
    response = httpx.get(
        f"{agent_url}/threads/{thread_id}/state",
        headers={"Authorization": f"Bearer {os.environ['SPRING_TO_AGENT_TOKEN']}"},
        timeout=20,
    )
    _expect(response, 200)
    values = response.json().get("values")
    if not isinstance(values, dict):
        raise RuntimeError("formal-mode checkpoint has no controlled values")
    return values


def _verify_autonomous_actions(
    state: dict[str, object], expected_mode: str, expect_customer_communication: bool
) -> dict[str, object]:
    values = _read_autonomous_checkpoint(str(state["threadId"]))
    if values.get("model_mode") != expected_mode:
        raise RuntimeError("formal autonomous action mode was not used")
    actions = values.get("investigation_actions")
    if not isinstance(actions, list):
        raise RuntimeError("formal autonomous action records are missing")
    action_types = [action.get("actionType") for action in actions if isinstance(action, dict)]
    required = {
        "CONFIRM_ORDER",
        "READ_LOGISTICS",
        "READ_PAYMENT_AND_REFUNDS",
        "READ_COMPENSATION_AND_PENDING_ACTIONS",
        "READ_APPLICABLE_POLICY",
        "READ_ORDER_RULES",
        "SUBMIT_CONCLUSION",
    }
    if len(action_types) != len(required) or set(action_types) != required:
        raise RuntimeError(f"formal autonomous action set is incomplete: {action_types}")
    if any(
        not isinstance(action, dict)
        or set(action) != {"actionType", "evidenceReferences", "resultCode"}
        for action in actions
    ):
        raise RuntimeError("formal autonomous action record exceeded the controlled schema")
    run_evidence = values.get("investigation_run_evidence")
    if (
        not isinstance(run_evidence, dict)
        or set(run_evidence)
        != {
            "outcome",
            "failureClassification",
            "providerAttempts",
            "toolRounds",
            "tokens",
            "costMicros",
            "modelCalls",
        }
        or run_evidence["outcome"] != "CONCLUSION_SUBMITTED"
        or run_evidence["failureClassification"] != ""
        or run_evidence["toolRounds"] != 5
        or not isinstance(run_evidence["providerAttempts"], int)
        or not 1 <= run_evidence["providerAttempts"] <= 6
        or not isinstance(run_evidence["tokens"], int)
        or not 1 <= run_evidence["tokens"] <= 12_000
        or not isinstance(run_evidence["costMicros"], int)
        or not 1 <= run_evidence["costMicros"] <= 100_000
    ):
        raise RuntimeError("formal autonomous run evidence is incomplete")
    model_calls = run_evidence["modelCalls"]
    if (
        not isinstance(model_calls, list)
        or len(model_calls) != 6
        or [call.get("callNumber") for call in model_calls if isinstance(call, dict)]
        != list(range(1, 7))
        or sum(call.get("providerAttempts", 0) for call in model_calls if isinstance(call, dict))
        != run_evidence["providerAttempts"]
    ):
        raise RuntimeError("formal autonomous per-call evidence is incomplete")
    judgment_evidence = values.get("investigation_judgment_evidence")
    if (
        not isinstance(judgment_evidence, dict)
        or set(judgment_evidence)
        != {
            "logicalCalls",
            "providerAttempts",
            "tokens",
            "costMicros",
            "failureClassification",
        }
        or judgment_evidence["logicalCalls"] != 1
        or not isinstance(judgment_evidence["providerAttempts"], int)
        or judgment_evidence["providerAttempts"] != 1
        or judgment_evidence["failureClassification"] != ""
    ):
        raise RuntimeError("formal judgment call evidence is incomplete")
    communication_evidence = values.get("customer_communication_evidence")
    if expect_customer_communication:
        if (
            not isinstance(communication_evidence, dict)
            or set(communication_evidence)
            != {
                "logicalCalls",
                "providerAttempts",
                "tokens",
                "costMicros",
                "durationMs",
                "failureClassification",
            }
            or communication_evidence["logicalCalls"] != 1
            or not isinstance(communication_evidence["providerAttempts"], int)
            or not 1 <= communication_evidence["providerAttempts"] <= 2
            or not isinstance(communication_evidence["durationMs"], int)
            or communication_evidence["durationMs"] < 0
            or communication_evidence["failureClassification"] != ""
        ):
            raise RuntimeError("formal customer communication evidence is incomplete")
    else:
        communication_evidence = {
            "logicalCalls": 0,
            "providerAttempts": 0,
            "tokens": 0,
            "costMicros": 0,
            "durationMs": 0,
            "failureClassification": "",
        }
    total_logical_calls = (
        len(model_calls)
        + judgment_evidence["logicalCalls"]
        + communication_evidence["logicalCalls"]
    )
    total_provider_attempts = (
        run_evidence["providerAttempts"]
        + judgment_evidence["providerAttempts"]
        + communication_evidence["providerAttempts"]
    )
    estimated_cost_micros = (
        run_evidence["costMicros"]
        + judgment_evidence["costMicros"]
        + communication_evidence["costMicros"]
    )
    logical_limit = 8 if expect_customer_communication else 7
    attempt_limit = 9 if expect_customer_communication else 7
    if total_logical_calls > logical_limit or total_provider_attempts > attempt_limit:
        raise RuntimeError("formal provider call hard limit was exceeded")
    serialized = json.dumps(values, ensure_ascii=False)
    for forbidden in ("reasoning", "rawModel", "rawTool", "providerPayload", "api_key"):
        if forbidden.lower() in serialized.lower():
            raise RuntimeError("formal autonomous checkpoint leaked forbidden provider data")
    return {
        "modelMode": values["model_mode"],
        "actionOrder": action_types,
        "actionRun": run_evidence,
        "judgmentRun": judgment_evidence,
        "customerCommunicationRun": communication_evidence,
        "totalLogicalCalls": total_logical_calls,
        "totalProviderAttempts": total_provider_attempts,
        "estimatedCostMicros": estimated_cost_micros,
    }


def _validate_success_state(state: dict[str, object]) -> None:
    expected = {
        "generationStatus": "COMPLETED",
        "submissionStatus": "COMPLETED",
        "lifecycleState": "INVESTIGATING",
        "handlingMode": "AGENT",
        "handoffReasonCode": None,
        "proposalCount": 1,
        "handoffRequestCount": 0,
        "authoritativeFactCount": 8,
        "agentCommandCount": 6,
    }
    actual = {name: state.get(name) for name in expected}
    if actual != expected:
        rendered = ", ".join(f"{name}={actual[name]}" for name in expected)
        raise RuntimeError(f"formal Spring terminal state mismatch: {rendered}")


def _run(
    expectation: str,
    run_id: str,
    expected_action_model_mode: str | None,
    expected_customer_communication_mode: str | None,
) -> dict[str, object]:
    spring_url = os.environ["SPRING_INTERNAL_URL"]
    connection_uri = os.environ["SPRING_FORMAL_DATABASE_URI"]
    order_reference = f"I127-{run_id}-{expectation}".upper()
    with psycopg.connect(connection_uri) as connection:
        _clone_order(connection, order_reference)
    with httpx.Client(timeout=20) as client:
        _login(client, spring_url)
        response = client.post(
            f"{spring_url}/api/customer/tickets",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "orderReference": order_reference,
                "description": "合成客服工单正式 Flash 调查验收",
            },
        )
        _expect(response, 201)
        ticket_id = response.json()["ticketId"]
        state = _wait_for_terminal(connection_uri, ticket_id)
        projection_response = client.get(f"{spring_url}/api/customer/tickets/{ticket_id}")
        _expect(projection_response, 200)
        projection = projection_response.json()

    checkpoint_evidence: dict[str, object] | None = None
    if expectation == "success":
        _validate_success_state(state)
        if projection["messages"][-1]["author"] != "AGENT":
            raise RuntimeError("formal Flash success did not publish the controlled Agent result")
        if expected_action_model_mode is not None:
            checkpoint_evidence = _verify_autonomous_actions(
                state,
                expected_action_model_mode,
                expected_customer_communication_mode is not None,
            )
    elif expectation == "handoff":
        if (
            state["generationStatus"] != "HANDED_OFF"
            or state["handlingMode"] != "HUMAN"
            or state["handoffReasonCode"] != "INVALID_MODEL_OUTPUT"
            or state["proposalCount"] != 0
            or state["handoffRequestCount"] != 1
        ):
            raise RuntimeError("formal provider failure did not fail closed to human handling")
        if projection["messages"][-1]["body"] != (
            "为确保处理安全，此工单已转由客服继续调查。客服将在此工单中与您联系。"
        ):
            raise RuntimeError("formal provider failure did not publish the controlled handoff")
        public_projection = json.dumps(projection, ensure_ascii=False)
        if "INVALID_MODEL_OUTPUT" in public_projection or "MODEL_CALL_FAILED" in public_projection:
            raise RuntimeError("formal provider failure leaked an internal reason")
    else:
        raise ValueError("unsupported formal-mode expectation")

    sanitized_spring_state = {key: value for key, value in state.items() if key != "threadId"}
    public_failure = ""
    if checkpoint_evidence is not None:
        action_run = checkpoint_evidence.get("actionRun")
        if isinstance(action_run, dict) and isinstance(
            action_run.get("failureClassification"), str
        ):
            public_failure = action_run["failureClassification"]
    return {
        "schemaVersion": (
            "issue-129-formal-customer-communication-acceptance-v1"
            if expected_customer_communication_mode is not None
            else "issue-128-formal-autonomous-acceptance-v1"
        ),
        "expectation": expectation,
        "model": "deepseek-v4-flash",
        "modelMode": "deepseek-formal",
        "boundedProviderAttempts": 2,
        "actionModelMode": expected_action_model_mode or "deterministic-action-model-v1",
        "customerCommunicationModelMode": (
            expected_customer_communication_mode or "fixed-fake-customer-communication-v1"
        ),
        "springState": sanitized_spring_state,
        "checkpointEvidence": checkpoint_evidence,
        "publicFailureClassification": public_failure,
        "publicHandoffReason": state["handoffReasonCode"] or "",
        "result": "PASSED",
    }


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect", choices=["success", "handoff"], required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-action-model-mode")
    parser.add_argument("--expected-customer-communication-mode")
    parser.add_argument("--report-path")
    arguments = parser.parse_args()
    if not arguments.run_id.isalnum():
        raise SystemExit("controlled run id is required")
    report = _run(
        arguments.expect,
        arguments.run_id,
        arguments.expected_action_model_mode,
        arguments.expected_customer_communication_mode,
    )
    if arguments.report_path:
        Path(arguments.report_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    _main()
