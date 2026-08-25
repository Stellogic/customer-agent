from __future__ import annotations

import argparse
import json
import os
import time
import uuid
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
                "(select count(*) from agent_human_handoff_request h where h.ticket_id = t.id) "
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
                }
        time.sleep(0.25)
    raise RuntimeError(f"formal-mode generation did not reach a terminal state: {last_status}")


def _run(expectation: str, run_id: str) -> dict[str, object]:
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

    if expectation == "success":
        if state != {
            "generationStatus": "COMPLETED",
            "submissionStatus": "COMPLETED",
            "lifecycleState": "INVESTIGATING",
            "handlingMode": "AGENT",
            "handoffReasonCode": None,
            "proposalCount": 1,
            "handoffRequestCount": 0,
        }:
            raise RuntimeError(
                "formal Flash judgment did not reach the Spring-authoritative result"
            )
        if projection["messages"][-1]["author"] != "AGENT":
            raise RuntimeError("formal Flash success did not publish the controlled Agent result")
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

    return {
        "schemaVersion": "issue-127-formal-business-smoke-v1",
        "expectation": expectation,
        "model": "deepseek-v4-flash",
        "modelMode": "deepseek-formal",
        "boundedProviderAttempts": 2,
        "result": "PASSED",
    }


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect", choices=["success", "handoff"], required=True)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args()
    if not arguments.run_id.isalnum():
        raise SystemExit("controlled run id is required")
    print(json.dumps(_run(arguments.expect, arguments.run_id), sort_keys=True))


if __name__ == "__main__":
    _main()
