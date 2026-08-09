import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg


def expect_status(response: httpx.Response, expected: int) -> None:
    if response.status_code != expected:
        raise AssertionError(f"expected {expected}, got {response.status_code}: {response.text}")


def main() -> None:
    agent_url = os.environ["AGENT_SERVER_URL"]
    spring_url = os.environ["SPRING_INTERNAL_URL"]
    spring_headers = {"Authorization": f"Bearer {os.environ['SPRING_TO_AGENT_TOKEN']}"}
    executor_headers = {"Authorization": f"Bearer {os.environ['EXECUTOR_MACHINE_TOKEN']}"}

    with httpx.Client(timeout=20.0) as client:
        thread_response = client.post(f"{agent_url}/threads", headers=spring_headers, json={})
        expect_status(thread_response, 200)
        thread_id = thread_response.json()["thread_id"]
        run_response = client.post(
            f"{agent_url}/threads/{thread_id}/runs/wait",
            headers=spring_headers,
            json={"assistant_id": "baseline_agent", "input": {"requested_by": "spring"}},
        )
        expect_status(run_response, 200)
        result = run_response.json()
        assert result["spring_probe"]["identity"] == "agent"

        denied_agent = client.post(f"{agent_url}/threads", headers=executor_headers, json={})
        expect_status(denied_agent, 401)
        allowed_executor = client.get(
            f"{spring_url}/internal/capabilities/executor/probe", headers=executor_headers
        )
        expect_status(allowed_executor, 200)
        denied_executor = client.get(
            f"{spring_url}/internal/capabilities/agent/probe", headers=executor_headers
        )
        expect_status(denied_executor, 403)

    request_id = f"smoke-{uuid.uuid4()}"
    ticket_payload = {
        "orderReference": "ORDER-DELAY-001",
        "description": "合成订单物流已经延迟多日",
    }
    ticket_headers = {
        "X-Synthetic-Customer-Id": "customer-demo",
        "Idempotency-Key": request_id,
    }

    def create_ticket(_: int) -> httpx.Response:
        with httpx.Client(timeout=20.0) as concurrent_client:
            return concurrent_client.post(
                f"{spring_url}/api/customer/tickets", headers=ticket_headers, json=ticket_payload
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        create_responses = list(pool.map(create_ticket, range(8)))
    create_statuses = sorted(response.status_code for response in create_responses)
    assert create_statuses == [200] * 7 + [201], [
        (response.status_code, response.text) for response in create_responses
    ]
    ticket_ids = {response.json()["ticketId"] for response in create_responses}
    assert len(ticket_ids) == 1
    ticket_id = ticket_ids.pop()

    with httpx.Client(timeout=20.0) as client:
        conflict = client.post(
            f"{spring_url}/api/customer/tickets",
            headers=ticket_headers,
            json={**ticket_payload, "description": "同一请求身份下的不同参数"},
        )
        expect_status(conflict, 409)
        assert conflict.json()["code"] == "REQUEST_ID_CONFLICT"

        snapshot = client.get(
            f"{spring_url}/api/customer/tickets/{ticket_id}",
            headers={"X-Synthetic-Customer-Id": "customer-demo"},
        )
        expect_status(snapshot, 200)
        public_projection = snapshot.json()
        assert public_projection["view"] == "CUSTOMER_PUBLIC"
        assert public_projection["cursor"] == "customer-public-v1:2"
        assert public_projection["ticket"]["lifecycleState"] == "INVESTIGATING"
        assert public_projection["ticket"]["handlingMode"] == "AGENT"
        assert public_projection["ticket"]["firstRespondedAt"]
        assert len(public_projection["messages"]) == 2
        assert [message["author"] for message in public_projection["messages"]] == ["CUSTOMER", "SUPPORT"]
        forbidden_fields = (
            "internalNote", "investigationFact", "proposal", "approval", "threadId",
            "runId", "checkpoint", "toolPayload",
        )
        serialized_projection = json.dumps(public_projection)
        assert not any(field in serialized_projection for field in forbidden_fields)

        denied_snapshot = client.get(
            f"{spring_url}/api/customer/tickets/{ticket_id}",
            headers={"X-Synthetic-Customer-Id": "customer-other-demo"},
        )
        expect_status(denied_snapshot, 404)

        with client.stream(
            "GET",
            f"{spring_url}/api/customer/tickets/{ticket_id}/events",
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
                "Last-Event-ID": "customer-public-v1:0",
            },
        ) as events:
            expect_status(events, 200)
            assert events.headers["content-type"].startswith("text/event-stream")
            event_lines = []
            for line in events.iter_lines():
                event_lines.append(line)
                if line == ":connected":
                    break
            event_stream = "\n".join(event_lines)
            assert "id:customer-public-v1:1" in event_stream
            assert "id:customer-public-v1:2" in event_stream
            assert not any(field in event_stream for field in forbidden_fields)

        restored = client.get(
            f"{spring_url}/api/customer/tickets/{ticket_id}",
            headers={"X-Synthetic-Customer-Id": "customer-demo"},
        )
        expect_status(restored, 200)
        assert restored.json() == public_projection

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute("select current_database(), current_user").fetchone() == (
            "customer_agent",
            "spring_app",
        )
        ticket_uuid = uuid.UUID(ticket_id)
        assert connection.execute(
            "select lifecycle_state, handling_mode, first_responded_at is not null from support_ticket where id = %s",
            (ticket_uuid,),
        ).fetchone() == ("INVESTIGATING", "AGENT", True)
        assert connection.execute(
            "select count(*) from customer_ticket_request where ticket_id = %s", (ticket_uuid,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "select count(*) from public_message where ticket_id = %s", (ticket_uuid,)
        ).fetchone()[0] == 2
        assert connection.execute(
            "select count(*) from audit_event where ticket_id = %s", (ticket_uuid,)
        ).fetchone()[0] >= 2

    no_compensation_request = f"issue-14-{uuid.uuid4()}"
    no_compensation_payload = {
        "orderReference": "ORDER-DELAY-UNDER-24",
        "description": "合成订单物流延迟不足二十四小时",
    }
    no_compensation_headers = {
        "X-Synthetic-Customer-Id": "customer-demo",
        "Idempotency-Key": no_compensation_request,
    }
    with httpx.Client(timeout=20.0) as client:
        accepted = client.post(
            f"{spring_url}/api/customer/tickets",
            headers=no_compensation_headers,
            json=no_compensation_payload,
        )
        expect_status(accepted, 201)
        assert accepted.json()["accepted"] is True
        resolved_ticket_id = accepted.json()["ticketId"]
        resolved_projection = None
        for _ in range(60):
            snapshot = client.get(
                f"{spring_url}/api/customer/tickets/{resolved_ticket_id}",
                headers={"X-Synthetic-Customer-Id": "customer-demo"},
            )
            expect_status(snapshot, 200)
            resolved_projection = snapshot.json()
            if resolved_projection["ticket"]["lifecycleState"] == "RESOLVED":
                break
            time.sleep(0.5)
        assert resolved_projection is not None
        assert resolved_projection["ticket"]["lifecycleState"] == "RESOLVED", resolved_projection
        assert resolved_projection["ticket"]["handlingMode"] == "AGENT"
        assert resolved_projection["ticket"]["createdAt"] == "2026-08-09T14:00:00Z"
        assert len(resolved_projection["messages"]) == 3
        assert resolved_projection["messages"][-1]["author"] == "AGENT"
        assert "不足 24 小时" in resolved_projection["messages"][-1]["body"]
        serialized_projection = json.dumps(resolved_projection)
        assert not any(field in serialized_projection for field in forbidden_fields)

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        resolved_uuid = uuid.UUID(resolved_ticket_id)
        generation = connection.execute(
            "select g.id, g.thread_id, g.status, s.submission_request_id, s.status "
            "from agent_processing_generation g join agent_submission s on s.generation_id = g.id "
            "where g.ticket_id = %s",
            (resolved_uuid,),
        ).fetchone()
        assert generation is not None
        assert generation[2] == "COMPLETED"
        assert generation[4] == "COMPLETED"
        assert connection.execute(
            "select count(*) from investigation_fact where generation_id = %s", (generation[0],)
        ).fetchone()[0] == 5
        assert connection.execute(
            "select count(*) from agent_command_request where generation_id = %s", (generation[0],)
        ).fetchone()[0] == 1
        assert connection.execute(
            "select count(*) from public_message where ticket_id = %s", (resolved_uuid,)
        ).fetchone()[0] == 3
        generation_id = str(generation[0])
        generation_thread_id = str(generation[1])
        submission_request_id = str(generation[3])

    with httpx.Client(timeout=20.0) as client:
        runs = client.get(
            f"{agent_url}/threads/{generation_thread_id}/runs?limit=100",
            headers=spring_headers,
        )
        expect_status(runs, 200)
        matching_runs = [
            run for run in runs.json()
            if run.get("metadata", {}).get("submission_request_id") == submission_request_id
        ]
        assert len(matching_runs) == 1, matching_runs

        scoped_headers = {
            "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
            "X-Agent-Generation-Id": generation_id,
            "X-Agent-Operation": "READ_INVESTIGATION_FACTS",
        }
        stale = client.get(
            f"{spring_url}/internal/agent/tickets/{resolved_ticket_id}/generations/{generation_id}/facts",
            headers=scoped_headers,
        )
        expect_status(stale, 403)

        conflict = client.post(
            f"{spring_url}/internal/agent/tickets/{resolved_ticket_id}/generations/{generation_id}/conclusions",
            headers={
                **scoped_headers,
                "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                "Idempotency-Key": f"{generation_id}:submit-conclusion",
            },
            json={
                "compensationRequired": False,
                "reasonCode": "DELAY_UNDER_24_HOURS",
                "delayHours": 22,
                "orderReference": "ORDER-DELAY-UNDER-24",
                "evidenceRefs": [
                    "order:ORDER-DELAY-UNDER-24",
                    "logistics:ORDER-DELAY-UNDER-24",
                ],
            },
        )
        expect_status(conflict, 409)

        wrong_ticket_replay = client.post(
            f"{spring_url}/internal/agent/tickets/{ticket_id}/generations/{generation_id}/conclusions",
            headers={
                **scoped_headers,
                "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                "Idempotency-Key": f"{generation_id}:submit-conclusion",
            },
            json={
                "compensationRequired": False,
                "reasonCode": "DELAY_UNDER_24_HOURS",
                "delayHours": 23,
                "orderReference": "ORDER-DELAY-UNDER-24",
                "evidenceRefs": [
                    "order:ORDER-DELAY-UNDER-24",
                    "logistics:ORDER-DELAY-UNDER-24",
                ],
            },
        )
        expect_status(wrong_ticket_replay, 403)

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select count(*) from audit_event where ticket_id = %s", (resolved_uuid,)
        ).fetchone()[0] >= 8
    with psycopg.connect(os.environ["AGENT_DATABASE_URI"]) as connection:
        assert connection.execute("select current_database(), current_user").fetchone() == (
            "agent_checkpoint",
            "agent_runtime",
        )
        checkpoint_count = connection.execute("select count(*) from checkpoints").fetchone()[0]
        assert checkpoint_count > 0

    for uri, forbidden_database in (
        (os.environ["SPRING_CROSS_DATABASE_URI"], "agent_checkpoint"),
        (os.environ["AGENT_CROSS_DATABASE_URI"], "customer_agent"),
    ):
        try:
            psycopg.connect(uri).close()
        except psycopg.OperationalError:
            continue
        raise AssertionError(f"cross-database connection unexpectedly succeeded: {forbidden_database}")

    print(json.dumps({
        "status": "UP",
        "thread_id": thread_id,
        "checkpoint_count": checkpoint_count,
        "ticket_id": ticket_id,
        "resolved_ticket_id": resolved_ticket_id,
        "concurrent_replays": 7,
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"smoke failed: {error}", file=sys.stderr)
        raise
