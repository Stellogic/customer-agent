# pyright: reportOptionalSubscript=false
import datetime
import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from functools import cache

import httpx
import psycopg


def expect_status(response: httpx.Response, expected: int) -> None:
    if response.status_code != expected:
        raise AssertionError(f"expected {expected}, got {response.status_code}: {response.text}")


def start_authorized_sse(url: str, headers: dict[str, str], cursor: str):
    connected = threading.Event()

    def observe_until_closed() -> bool:
        with httpx.Client(timeout=20.0) as stream_client:
            with stream_client.stream(
                "GET", url, headers={**headers, "Last-Event-ID": cursor}
            ) as response:
                expect_status(response, 200)
                for line in response.iter_lines():
                    if line == ":connected":
                        connected.set()
            return True

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(observe_until_closed)
    if not connected.wait(timeout=5):
        executor.shutdown(wait=False, cancel_futures=True)
        raise AssertionError("approval SSE did not establish")
    return executor, future


def login_human(
    client: httpx.Client,
    spring_url: str,
    username: str,
    expected_capabilities: list[str],
) -> tuple[str, str]:
    anonymous_csrf = client.get(f"{spring_url}/api/auth/csrf")
    expect_status(anonymous_csrf, 200)
    anonymous_token = anonymous_csrf.json()
    login = client.post(
        f"{spring_url}/api/auth/login",
        headers={anonymous_token["headerName"]: anonymous_token["token"]},
        data={"username": username, "password": "local-demo-password"},
    )
    expect_status(login, 204)
    current_csrf = client.get(f"{spring_url}/api/auth/csrf")
    expect_status(current_csrf, 200)
    current_token = current_csrf.json()
    client.headers[current_token["headerName"]] = current_token["token"]
    session = client.get(f"{spring_url}/api/auth/session")
    expect_status(session, 200)
    assert session.json()["id"] == username
    assert session.json()["capabilities"] == expected_capabilities
    return current_token["headerName"], current_token["token"]


@cache
def customer_session_headers(spring_url: str) -> tuple[tuple[str, str], ...]:
    with httpx.Client(timeout=20.0) as client:
        csrf_header = login_human(client, spring_url, "customer-demo", ["CUSTOMER_HELP_ACCESS"])
        session_id = client.cookies.get("JSESSIONID")
        assert session_id is not None
        return csrf_header, ("Cookie", f"JSESSIONID={session_id}")


@cache
def support_session_headers(spring_url: str) -> tuple[tuple[str, str], ...]:
    with httpx.Client(timeout=20.0) as client:
        csrf_header = login_human(client, spring_url, "support-demo", ["SUPPORT_WORKBENCH_ACCESS"])
        session_id = client.cookies.get("JSESSIONID")
        assert session_id is not None
        return csrf_header, ("Cookie", f"JSESSIONID={session_id}")


@cache
def approver_session_headers(spring_url: str) -> tuple[tuple[str, str], ...]:
    with httpx.Client(timeout=20.0) as client:
        csrf_header = login_human(
            client, spring_url, "approver-demo", ["APPROVAL_WORKBENCH_ACCESS"]
        )
        session_id = client.cookies.get("JSESSIONID")
        assert session_id is not None
        return csrf_header, ("Cookie", f"JSESSIONID={session_id}")


@contextmanager
def customer_browser_client(spring_url: str) -> Iterator[httpx.Client]:
    customer_headers = dict(customer_session_headers(spring_url))
    support_headers = dict(support_session_headers(spring_url))
    approver_headers = dict(approver_session_headers(spring_url))

    def authorize_human_request(request: httpx.Request) -> None:
        if request.url.path.startswith("/api/customer/"):
            request.headers.update(customer_headers)
        if request.url.path.startswith("/api/support/"):
            request.headers.update(support_headers)
        if request.url.path.startswith("/api/approver/"):
            request.headers.update(approver_headers)

    with httpx.Client(
        timeout=20.0,
        event_hooks={"request": [authorize_human_request]},
    ) as client:
        yield client


@contextmanager
def isolated_customer_browser_client(spring_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(timeout=20.0) as client:
        login_human(client, spring_url, "customer-demo", ["CUSTOMER_HELP_ACCESS"])
        yield client


def main() -> None:
    agent_url = os.environ["AGENT_SERVER_URL"]
    spring_url = os.environ["SPRING_INTERNAL_URL"]
    spring_headers = {"Authorization": f"Bearer {os.environ['SPRING_TO_AGENT_TOKEN']}"}
    executor_headers = {"Authorization": f"Bearer {os.environ['EXECUTOR_MACHINE_TOKEN']}"}

    customer_session_headers(spring_url)
    support_session_headers(spring_url)
    approver_session_headers(spring_url)

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

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        delay_fact_constraints = connection.execute(
            "select conname from pg_constraint where convalidated "
            "and conname in ("
            "'approval_evidence_proposal_delay_fkey', "
            "'synthetic_order_delay_representations_consistent', "
            "'compensation_proposal_delay_representations_consistent', "
            "'compensation_proposal_revision_delay_identity', "
            "'approval_evidence_delay_representations_consistent') order by conname"
        ).fetchall()
        assert delay_fact_constraints == [
            ("approval_evidence_delay_representations_consistent",),
            ("approval_evidence_proposal_delay_fkey",),
            ("compensation_proposal_delay_representations_consistent",),
            ("compensation_proposal_revision_delay_identity",),
            ("synthetic_order_delay_representations_consistent",),
        ]
        assert connection.execute(
            "select convalidated from pg_constraint "
            "where conname = 'synthetic_order_paid_amount_check'"
        ).fetchone() == (True,)

    request_id = f"smoke-{uuid.uuid4()}"
    ticket_payload = {
        "orderReference": "ORDER-INTAKE-ONLY",
        "description": "合成订单物流已经延迟多日",
    }
    ticket_headers = {
        "Idempotency-Key": request_id,
    }

    def create_ticket(_: int) -> httpx.Response:
        with customer_browser_client(spring_url) as concurrent_client:
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

    other_customer_ticket_id = uuid.uuid4()
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "insert into support_ticket "
            "(id, customer_id, order_reference, description, lifecycle_state, handling_mode, "
            "created_at, first_responded_at) values (%s, 'customer-other-demo', "
            "'ORDER-INTAKE-ONLY', 'other customer boundary', 'INVESTIGATING', 'HUMAN', "
            "current_timestamp, current_timestamp)",
            (other_customer_ticket_id,),
        )

    with httpx.Client(timeout=20.0) as anonymous_client:
        forged_anonymous = anonymous_client.get(
            f"{spring_url}/api/customer/tickets/{ticket_id}",
        )
        expect_status(forged_anonymous, 401)

    with isolated_customer_browser_client(spring_url) as client:
        conflict = client.post(
            f"{spring_url}/api/customer/tickets",
            headers=ticket_headers,
            json={**ticket_payload, "description": "同一请求身份下的不同参数"},
        )
        expect_status(conflict, 409)
        assert conflict.json()["code"] == "REQUEST_ID_CONFLICT"

        snapshot = client.get(
            f"{spring_url}/api/customer/tickets/{ticket_id}",
        )
        expect_status(snapshot, 200)
        public_projection = snapshot.json()
        assert public_projection["view"] == "CUSTOMER_PUBLIC"
        assert public_projection["cursor"] == "customer-public-v1:2"
        assert public_projection["ticket"]["lifecycleState"] == "INVESTIGATING"
        assert public_projection["ticket"]["handlingMode"] == "AGENT"
        assert public_projection["ticket"]["firstRespondedAt"]
        assert len(public_projection["messages"]) == 2
        assert [message["author"] for message in public_projection["messages"]] == [
            "CUSTOMER",
            "SUPPORT",
        ]
        forbidden_fields = (
            "internalNote",
            "investigationFact",
            "proposal",
            "approval",
            "threadId",
            "runId",
            "checkpoint",
            "toolPayload",
        )
        serialized_projection = json.dumps(public_projection)
        assert not any(field in serialized_projection for field in forbidden_fields)

        denied_snapshot = client.get(
            f"{spring_url}/api/customer/tickets/{other_customer_ticket_id}",
        )
        expect_status(denied_snapshot, 404)
        denied_handoff = client.post(
            f"{spring_url}/api/customer/tickets/{other_customer_ticket_id}/human-handoff",
            headers={
                "Idempotency-Key": f"other-customer-handoff-{uuid.uuid4()}",
            },
            json={"reasonCode": "CUSTOMER_REQUESTED"},
        )
        expect_status(denied_handoff, 404)

        with client.stream(
            "GET",
            f"{spring_url}/api/customer/tickets/{ticket_id}/events",
            headers={
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
        )
        expect_status(restored, 200)
        assert restored.json() == public_projection

        logout = client.post(f"{spring_url}/api/auth/logout")
        expect_status(logout, 204)
        rejected_reconnect = client.get(
            f"{spring_url}/api/customer/tickets/{ticket_id}/events",
            headers={
                "Last-Event-ID": public_projection["cursor"],
            },
        )
        expect_status(rejected_reconnect, 401)

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
        assert (
            connection.execute(
                "select count(*) from customer_ticket_request where ticket_id = %s", (ticket_uuid,)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "select count(*) from public_message where ticket_id = %s", (ticket_uuid,)
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "select count(*) from audit_event where ticket_id = %s", (ticket_uuid,)
            ).fetchone()[0]
            >= 2
        )

    no_compensation_request = f"issue-14-{uuid.uuid4()}"
    no_compensation_payload = {
        "orderReference": "ORDER-DELAY-UNDER-24",
        "description": "合成订单物流延迟不足二十四小时",
    }
    no_compensation_headers = {
        "Idempotency-Key": no_compensation_request,
    }
    with customer_browser_client(spring_url) as client:
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
        assert (
            connection.execute(
                "select count(*) from investigation_fact where generation_id = %s", (generation[0],)
            ).fetchone()[0]
            == 6
        )
        assert (
            connection.execute(
                "select count(*) from agent_command_request where generation_id = %s",
                (generation[0],),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "select count(*) from public_message where ticket_id = %s", (resolved_uuid,)
            ).fetchone()[0]
            == 3
        )
        generation_id = str(generation[0])
        generation_thread_id = str(generation[1])
        submission_request_id = str(generation[3])

    with customer_browser_client(spring_url) as client:
        runs = client.get(
            f"{agent_url}/threads/{generation_thread_id}/runs?limit=100",
            headers=spring_headers,
        )
        expect_status(runs, 200)
        matching_runs = [
            run
            for run in runs.json()
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
                "delaySeconds": 22 * 60 * 60,
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
                "delaySeconds": 23 * 60 * 60,
                "orderReference": "ORDER-DELAY-UNDER-24",
                "evidenceRefs": [
                    "order:ORDER-DELAY-UNDER-24",
                    "logistics:ORDER-DELAY-UNDER-24",
                ],
            },
        )
        expect_status(wrong_ticket_replay, 403)

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert (
            connection.execute(
                "select count(*) from audit_event where ticket_id = %s", (resolved_uuid,)
            ).fetchone()[0]
            >= 8
        )

    def assert_controlled_ineligible_proposal(order_reference: str) -> None:
        ineligible_ticket_id = uuid.uuid4()
        ineligible_generation_id = uuid.uuid4()
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            connection.execute(
                "insert into support_ticket "
                "(id, customer_id, order_reference, description, lifecycle_state, handling_mode, "
                "created_at, first_responded_at) values "
                "(%s, 'customer-demo', %s, 'non-proposable amount proof', "
                "'INVESTIGATING', 'AGENT', "
                "'2026-08-09T13:55:00Z', '2026-08-09T13:56:00Z')",
                (ineligible_ticket_id, order_reference),
            )
            connection.execute(
                "insert into agent_processing_generation "
                "(id, ticket_id, generation_number, thread_id, status, created_at) "
                "values (%s, %s, 1, %s, 'ACTIVE', '2026-08-09T13:56:00Z')",
                (ineligible_generation_id, ineligible_ticket_id, uuid.uuid4()),
            )

        ineligible_headers = {
            "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
            "X-Agent-Generation-Id": str(ineligible_generation_id),
        }
        with httpx.Client(timeout=20.0) as client:
            facts = client.get(
                f"{spring_url}/internal/agent/tickets/{ineligible_ticket_id}/generations/"
                f"{ineligible_generation_id}/facts",
                headers={
                    **ineligible_headers,
                    "X-Agent-Operation": "READ_INVESTIGATION_FACTS",
                },
            )
            expect_status(facts, 200)
            conclusion = client.post(
                f"{spring_url}/internal/agent/tickets/{ineligible_ticket_id}/generations/"
                f"{ineligible_generation_id}/conclusions",
                headers={
                    **ineligible_headers,
                    "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                    "Idempotency-Key": f"{ineligible_generation_id}:submit-conclusion",
                },
                json={
                    "compensationRequired": True,
                    "reasonCode": "LOGISTICS_DELAY",
                    "delayHours": facts.json()["delayHours"],
                    "delaySeconds": facts.json()["delaySeconds"],
                    "orderReference": order_reference,
                    "evidenceRefs": facts.json()["evidenceRefs"],
                },
            )
            expect_status(conclusion, 422)

        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            assert (
                connection.execute(
                    "select count(*) from compensation_proposal_revision where ticket_id = %s",
                    (ineligible_ticket_id,),
                ).fetchone()[0]
                == 0
            )
            assert (
                connection.execute(
                    "select count(*) from audit_event where ticket_id = %s "
                    "and event_type = "
                    "'AGENT_COMMAND_REJECTED_COMPENSATION_PROPOSAL_INELIGIBLE'",
                    (ineligible_ticket_id,),
                ).fetchone()[0]
                == 1
            )

    assert_controlled_ineligible_proposal("ORDER-DELAY-ZERO-PAID")
    assert_controlled_ineligible_proposal("ORDER-DELAY-ROUNDING-ZERO")

    proposal_request = f"issue-15-{uuid.uuid4()}"
    proposal_order_reference = "ORDER-DELAY-001"
    with customer_browser_client(spring_url) as client:
        accepted = client.post(
            f"{spring_url}/api/customer/tickets",
            headers={
                "Idempotency-Key": proposal_request,
            },
            json={
                "orderReference": proposal_order_reference,
                "description": "合成订单物流延迟八十小时",
            },
        )
        expect_status(accepted, 201)
        proposal_ticket_id = accepted.json()["ticketId"]

    proposal_row = None
    for _ in range(60):
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            proposal_row = connection.execute(
                "select p.id, p.proposal_id, p.revision_number, p.delay_hours, p.delay_seconds, "
                "p.compensation_method, p.amount, p.reason_code, p.policy_version, "
                "p.content_digest, p.status, g.status, s.delay_hours, s.delay_seconds, s.paid_amount, "
                "s.total_available_compensation_amount, s.active_reservation_amount, "
                "s.remaining_available_compensation_amount, jsonb_array_length(s.evidence_references) "
                "from compensation_proposal_revision p "
                "join agent_processing_generation g on g.id = p.generation_id "
                "join approval_evidence_snapshot s on s.proposal_revision_id = p.id "
                "where p.ticket_id = %s",
                (uuid.UUID(proposal_ticket_id),),
            ).fetchone()
        if proposal_row is not None:
            break
        time.sleep(0.5)
    assert proposal_row is not None
    assert proposal_row[2:] == (
        1,
        80,
        288000,
        "SIMULATED_PARTIAL_REFUND",
        Decimal("26.80"),
        "LOGISTICS_DELAY",
        "delay-policy-v1",
        proposal_row[9],
        "PENDING_APPROVAL",
        "COMPLETED",
        80,
        288000,
        Decimal("268.00"),
        Decimal("268.00"),
        Decimal("0.00"),
        Decimal("268.00"),
        2,
    )
    assert len(proposal_row[9]) == 64
    first_revision_id, proposal_id = proposal_row[:2]

    reused_generation = uuid.uuid4()
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "insert into agent_processing_generation "
            "(id, ticket_id, generation_number, thread_id, status, created_at) "
            "values (%s, %s, 2, %s, 'ACTIVE', now())",
            (reused_generation, uuid.UUID(proposal_ticket_id), uuid.uuid4()),
        )
    reused_headers = {
        "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
        "X-Agent-Generation-Id": str(reused_generation),
    }
    with httpx.Client(timeout=20.0) as client:
        reused_facts = client.get(
            f"{spring_url}/internal/agent/tickets/{proposal_ticket_id}/generations/"
            f"{reused_generation}/facts",
            headers={**reused_headers, "X-Agent-Operation": "READ_INVESTIGATION_FACTS"},
        )
        expect_status(reused_facts, 200)
        reused = client.post(
            f"{spring_url}/internal/agent/tickets/{proposal_ticket_id}/generations/"
            f"{reused_generation}/conclusions",
            headers={
                **reused_headers,
                "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                "Idempotency-Key": f"{reused_generation}:submit-conclusion",
            },
            json={
                "compensationRequired": True,
                "reasonCode": "LOGISTICS_DELAY",
                "delayHours": 80,
                "delaySeconds": 288000,
                "orderReference": proposal_order_reference,
                "evidenceRefs": reused_facts.json()["evidenceRefs"],
            },
        )
        expect_status(reused, 200)
        assert reused.json()["proposalRevisionId"] == str(first_revision_id)
        assert reused.json()["proposalRevision"] == 1

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select count(*), min(content_digest), max(content_digest) "
            "from compensation_proposal_revision where ticket_id = %s",
            (uuid.UUID(proposal_ticket_id),),
        ).fetchone() == (1, proposal_row[9], proposal_row[9])

    with customer_browser_client(spring_url) as client:
        customer_view = client.get(
            f"{spring_url}/api/customer/tickets/{proposal_ticket_id}",
        )
        expect_status(customer_view, 200)
        projection = customer_view.json()
        assert projection["ticket"]["lifecycleState"] == "INVESTIGATING"
        assert projection["messages"][-1]["author"] == "AGENT"
        assert "等待人工审批" in projection["messages"][-1]["body"]
        serialized = json.dumps(projection)
        assert not any(field in serialized for field in forbidden_fields)
        assert "26.80" not in serialized and "SIMULATED_PARTIAL_REFUND" not in serialized

    try:
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            connection.execute(
                "update compensation_proposal_revision set amount = 1.00 where id = %s",
                (first_revision_id,),
            )
        raise AssertionError("immutable proposal content unexpectedly changed")
    except psycopg.errors.RaiseException:
        pass

    approver_headers = dict(approver_session_headers(spring_url))
    with httpx.Client(timeout=20.0) as support_client:
        support_client.headers.update(dict(support_session_headers(spring_url)))
        forged_approval = support_client.get(
            f"{spring_url}/api/approver/compensation-proposals",
        )
        expect_status(forged_approval, 403)
    with customer_browser_client(spring_url) as client:
        queue = client.get(
            f"{spring_url}/api/approver/compensation-proposals", headers=approver_headers
        )
        expect_status(queue, 200)
        queue_item = next(
            item for item in queue.json() if item["proposalRevisionId"] == str(first_revision_id)
        )
        assert set(queue_item) == {
            "proposalRevisionId",
            "compensationMethod",
            "amount",
            "submittedAt",
            "expiresAt",
        }

        with httpx.Client(timeout=20.0) as anonymous_client:
            denied = anonymous_client.get(
                f"{spring_url}/api/approver/compensation-proposals",
            )
            expect_status(denied, 401)
        with httpx.Client(timeout=20.0) as anonymous_client:
            approver_customer_detail = anonymous_client.get(
                f"{spring_url}/api/customer/tickets/{proposal_ticket_id}", headers=approver_headers
            )
            expect_status(approver_customer_detail, 403)
        approver_support_detail = client.get(
            f"{spring_url}/api/support/tickets/{proposal_ticket_id}", headers=approver_headers
        )
        expect_status(approver_support_detail, 404)
        approver_execution = client.get(
            f"{spring_url}/internal/capabilities/executor/probe", headers=approver_headers
        )
        expect_status(approver_execution, 400)

    claim_requests = {
        "claim-a": f"issue-20-claim-a-{uuid.uuid4()}",
        "claim-b": f"issue-20-claim-b-{uuid.uuid4()}",
    }

    def claim_concurrently(claimant: str) -> httpx.Response:
        with customer_browser_client(spring_url) as concurrent_client:
            return concurrent_client.post(
                f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/claims",
                headers={
                    "Idempotency-Key": claim_requests[claimant],
                },
                json={"requestedLeaseSeconds": 900},
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        approval_claim_responses = list(executor.map(claim_concurrently, ["claim-a", "claim-b"]))
    assert sorted(response.status_code for response in approval_claim_responses) == [201, 409], [
        (response.status_code, response.text) for response in approval_claim_responses
    ]
    winner_index = next(
        index
        for index, response in enumerate(approval_claim_responses)
        if response.status_code == 201
    )
    winner_claimant = ["claim-a", "claim-b"][winner_index]
    winner_headers = dict(approver_session_headers(spring_url))
    lease_one = approval_claim_responses[winner_index].json()
    assert lease_one["leaseVersion"] == 1 and lease_one["replayed"] is False

    with customer_browser_client(spring_url) as client:
        replay = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/claims",
            headers={**winner_headers, "Idempotency-Key": claim_requests[winner_claimant]},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(replay, 200)
        assert replay.json()["leaseToken"] == lease_one["leaseToken"]
        assert replay.json()["replayed"] is True
        parameter_conflict = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/claims",
            headers={**winner_headers, "Idempotency-Key": claim_requests[winner_claimant]},
            json={"requestedLeaseSeconds": 899},
        )
        expect_status(parameter_conflict, 409)

        lease_headers = {
            **winner_headers,
            "X-Approval-Lease-Token": lease_one["leaseToken"],
            "X-Approval-Lease-Version": str(lease_one["leaseVersion"]),
        }
        approval_view = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers=lease_headers,
        )
        expect_status(approval_view, 200)
        approval_projection = approval_view.json()
        assert approval_projection["view"] == "APPROVAL_VIEW"
        assert approval_projection["schema"] == "approval-view-v1"
        assert approval_projection["cursor"] == "approval-view-v1:1"
        assert approval_projection["contentDigest"] == proposal_row[9]
        assert approval_projection["authoritativeAmount"] == 26.8
        assert approval_projection["orderReference"] == proposal_order_reference
        assert approval_projection["reasonCode"] == "LOGISTICS_DELAY"
        assert approval_projection["delaySeconds"] == 288000
        assert approval_projection["evidenceSnapshot"] == {
            "delaySeconds": 288000,
            "paidAmount": "268.00",
            "totalAvailableCompensationAmount": "268.00",
            "activeReservationAmount": "0.00",
            "remainingAvailableCompensationAmount": "268.00",
        }
        assert approval_projection["leaseToken"] == lease_one["leaseToken"]
        assert [event["eventType"] for event in approval_projection["responsibilityChain"]] == [
            "COMPENSATION_PROPOSAL_REVISION_CREATED",
            "COMPENSATION_PROPOSAL_REVISION_REUSED",
            "APPROVAL_LEASE_CLAIMED",
        ]
        assert approval_projection["responsibilityChain"][2]["leaseVersion"] == 1
        assert not any(
            field in approval_projection
            for field in (
                "ticket",
                "ticketId",
                "customerId",
                "description",
                "publicMessages",
                "internalNotes",
                "execution",
                "generationId",
                "threadId",
                "toolPayload",
            )
        )
        denied_other_approver = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers={
                "X-Approval-Lease-Token": lease_one["leaseToken"],
                "X-Approval-Lease-Version": "1",
            },
        )
        expect_status(denied_other_approver, 200)
        assert denied_other_approver.json()["leaseToken"] == lease_one["leaseToken"]
        denied_old_token = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers={
                **winner_headers,
                "X-Approval-Lease-Token": str(uuid.uuid4()),
                "X-Approval-Lease-Version": "1",
            },
        )
        expect_status(denied_old_token, 409)
        invisible_revision = uuid.uuid4()
        invisible_proposal = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{invisible_revision}/approval-view",
            headers={
                **winner_headers,
                "X-Approval-Lease-Token": str(uuid.uuid4()),
                "X-Approval-Lease-Version": "1",
            },
        )
        expect_status(invisible_proposal, 404)
        incompatible_cursor = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view/events",
            headers={**lease_headers, "Last-Event-ID": "support-workbench-v1:1"},
        )
        expect_status(incompatible_cursor, 409)

        release_request = f"issue-20-release-{uuid.uuid4()}"
        stream_executor, stream_closed = start_authorized_sse(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view/events",
            lease_headers,
            approval_projection["cursor"],
        )
        try:
            released = client.post(
                f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/release",
                headers={**lease_headers, "Idempotency-Key": release_request},
            )
            expect_status(released, 200)
            assert stream_closed.result(timeout=5) is True
        finally:
            stream_executor.shutdown(wait=False, cancel_futures=True)
        assert released.json() == {
            "proposalRevisionId": str(first_revision_id),
            "released": True,
            "replayed": False,
        }
        release_replay = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/release",
            headers={**lease_headers, "Idempotency-Key": release_request},
        )
        expect_status(release_replay, 200)
        assert release_replay.json()["replayed"] is True
        revoked_after_release = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers=lease_headers,
        )
        expect_status(revoked_after_release, 409)
        revoked_stream_after_release = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view/events",
            headers={**lease_headers, "Last-Event-ID": approval_projection["cursor"]},
        )
        expect_status(revoked_stream_after_release, 409)
        rejection_after_release = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/reject",
            headers={**lease_headers, "Idempotency-Key": f"released-reject-{uuid.uuid4()}"},
            json={
                "proposalRevision": proposal_row[2],
                "contentDigest": proposal_row[9],
                "internalReason": "已释放的审批责任不得继续提交决定",
            },
        )
        expect_status(rejection_after_release, 409)

        reclaim_two = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/claims",
            headers={
                "Idempotency-Key": f"issue-20-reclaim-2-{uuid.uuid4()}",
            },
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(reclaim_two, 201)
        lease_two = reclaim_two.json()
        assert lease_two["leaseVersion"] == 2
        stale_release = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/release",
            headers={
                **lease_headers,
                "Idempotency-Key": f"issue-20-stale-release-{uuid.uuid4()}",
            },
        )
        expect_status(stale_release, 409)
        lease_two_headers = {
            **dict(approver_session_headers(spring_url)),
            "X-Approval-Lease-Token": lease_two["leaseToken"],
            "X-Approval-Lease-Version": "2",
        }
        lease_two_view = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers=lease_two_headers,
        )
        expect_status(lease_two_view, 200)
        expiry_stream_executor, expiry_stream_closed = start_authorized_sse(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view/events",
            lease_two_headers,
            lease_two_view.json()["cursor"],
        )

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update approval_lease set claimed_at = '2026-08-09T13:59:59Z', "
            "expires_at = '2026-08-09T14:00:00Z' where proposal_revision_id = %s and lease_version = 2",
            (first_revision_id,),
        )
        proposal_state = connection.execute(
            "select status, expires_at from compensation_proposal_revision where id = %s",
            (first_revision_id,),
        ).fetchone()
        assert proposal_state[0] == "PENDING_APPROVAL"
        assert proposal_state[1].isoformat() == "2026-08-10T14:00:00+00:00"

    with customer_browser_client(spring_url) as client:
        try:
            assert expiry_stream_closed.result(timeout=5) is True
        finally:
            expiry_stream_executor.shutdown(wait=False, cancel_futures=True)
        expired_view = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers=lease_two_headers,
        )
        expect_status(expired_view, 409)
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            assert (
                connection.execute(
                    "select status from approval_lease where proposal_revision_id = %s and lease_version = 2",
                    (first_revision_id,),
                ).fetchone()[0]
                == "EXPIRED"
            )
            assert (
                connection.execute(
                    "select count(*) from audit_event where subject_id = %s "
                    "and event_type = 'APPROVAL_LEASE_EXPIRED' and authorization_version = 2",
                    (first_revision_id,),
                ).fetchone()[0]
                == 1
            )
        reclaim_three = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/claims",
            headers={
                **winner_headers,
                "Idempotency-Key": f"issue-20-reclaim-3-{uuid.uuid4()}",
            },
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(reclaim_three, 201)
        lease_three = reclaim_three.json()
        assert lease_three["leaseVersion"] == 3
        lease_three_headers = {
            **winner_headers,
            "X-Approval-Lease-Token": lease_three["leaseToken"],
            "X-Approval-Lease-Version": "3",
        }
        lease_three_view = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers=lease_three_headers,
        )
        expect_status(lease_three_view, 200)
        assert any(
            event["eventType"] == "APPROVAL_LEASE_EXPIRED" and event["leaseVersion"] == 2
            for event in lease_three_view.json()["responsibilityChain"]
        )
        replacement_stream_executor, replacement_stream_closed = start_authorized_sse(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view/events",
            lease_three_headers,
            lease_three_view.json()["cursor"],
        )

    expired_revision_id = uuid.uuid4()
    expired_lease_token = uuid.uuid4()
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "insert into compensation_proposal_revision "
            "(id, proposal_id, revision_number, ticket_id, order_reference, generation_id, delay_hours, "
            "delay_seconds, compensation_method, amount, reason_code, evidence_references, policy_version, "
            "content_digest, status, created_at, expires_at) values "
            "(%s, %s, 1, %s, 'ORDER-DELAY-UNDER-24', %s, 24, 86400, 'COUPON', 10.00, "
            "'LOGISTICS_DELAY', '[\"order:ORDER-DELAY-UNDER-24\",\"logistics:ORDER-DELAY-UNDER-24\"]', "
            "'delay-policy-v1', %s, 'PENDING_APPROVAL', '2026-08-08T14:00:00Z', '2026-08-09T14:00:00Z')",
            (expired_revision_id, uuid.uuid4(), resolved_uuid, generation[0], "e" * 64),
        )
        connection.execute(
            "insert into approval_evidence_snapshot "
            "(proposal_revision_id, order_reference, delay_hours, delay_seconds, paid_amount, "
            "total_available_compensation_amount, active_reservation_amount, "
            "remaining_available_compensation_amount, paid, cancelled, fully_refunded, "
            "existing_compensation, evidence_references, captured_at) values "
            "(%s, 'ORDER-DELAY-UNDER-24', 24, 86400, 268.00, 268.00, 0.00, 268.00, "
            "true, false, false, false, "
            '\'["order:ORDER-DELAY-UNDER-24","logistics:ORDER-DELAY-UNDER-24"]\', '
            "'2026-08-08T14:00:00Z')",
            (expired_revision_id,),
        )
        connection.execute(
            "insert into approval_lease "
            "(id, proposal_revision_id, approver_id, lease_token, lease_version, status, claimed_at, expires_at) "
            "values (%s, %s, 'approver-demo', %s, 1, 'ACTIVE', "
            "'2026-08-09T13:45:00Z', '2026-08-09T14:15:00Z')",
            (uuid.uuid4(), expired_revision_id, expired_lease_token),
        )

    with customer_browser_client(spring_url) as client:
        claim_at_proposal_expiry = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{expired_revision_id}/claims",
            headers={**approver_headers, "Idempotency-Key": f"expired-claim-{uuid.uuid4()}"},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(claim_at_proposal_expiry, 410)
        queue_at_proposal_expiry = client.get(
            f"{spring_url}/api/approver/compensation-proposals", headers=approver_headers
        )
        expect_status(queue_at_proposal_expiry, 200)
        assert all(
            item["proposalRevisionId"] != str(expired_revision_id)
            for item in queue_at_proposal_expiry.json()
        )
        expired_scope_headers = {
            **approver_headers,
            "X-Approval-Lease-Token": str(expired_lease_token),
            "X-Approval-Lease-Version": "1",
        }
        view_at_proposal_expiry = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{expired_revision_id}/approval-view",
            headers=expired_scope_headers,
        )
        expect_status(view_at_proposal_expiry, 409)
        release_at_proposal_expiry = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{expired_revision_id}/release",
            headers={
                **expired_scope_headers,
                "Idempotency-Key": f"expired-release-{uuid.uuid4()}",
            },
        )
        expect_status(release_at_proposal_expiry, 409)
        reject_at_proposal_expiry = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{expired_revision_id}/reject",
            headers={
                **expired_scope_headers,
                "Idempotency-Key": f"expired-reject-{uuid.uuid4()}",
            },
            json={
                "proposalRevision": 1,
                "contentDigest": "e" * 64,
                "internalReason": "过期边界提交",
            },
        )
        expect_status(reject_at_proposal_expiry, 409)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select p.status, l.status from compensation_proposal_revision p "
            "join approval_lease l on l.proposal_revision_id = p.id where p.id = %s",
            (expired_revision_id,),
        ).fetchone() == ("EXPIRED", "REVOKED")
        expiry_audit = connection.execute(
            "select event_type, occurred_at from audit_event where subject_id = %s "
            "and event_type in ('COMPENSATION_PROPOSAL_REVISION_EXPIRED', 'APPROVAL_LEASE_REVOKED') "
            "order by id",
            (expired_revision_id,),
        ).fetchall()
        assert [
            (event_type, occurred_at.isoformat()) for event_type, occurred_at in expiry_audit
        ] == [
            ("COMPENSATION_PROPOSAL_REVISION_EXPIRED", "2026-08-09T14:00:00+00:00"),
            ("APPROVAL_LEASE_REVOKED", "2026-08-09T14:00:00+00:00"),
        ]

    duplicate_ticket = uuid.uuid4()
    duplicate_generation = uuid.uuid4()
    try:
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            connection.execute(
                "insert into support_ticket (id, customer_id, order_reference, description, lifecycle_state, handling_mode, created_at, first_responded_at) "
                "values (%s, 'customer-demo', %s, 'constraint proof', 'INVESTIGATING', 'AGENT', now(), now())",
                (duplicate_ticket, proposal_order_reference),
            )
            connection.execute(
                "insert into agent_processing_generation (id, ticket_id, generation_number, thread_id, status, created_at) "
                "values (%s, %s, 1, %s, 'ACTIVE', now())",
                (duplicate_generation, duplicate_ticket, uuid.uuid4()),
            )
            connection.execute(
                "insert into compensation_proposal_revision "
                "(id, proposal_id, revision_number, ticket_id, order_reference, generation_id, delay_hours, delay_seconds, compensation_method, amount, reason_code, evidence_references, policy_version, content_digest, status, created_at, expires_at) "
                "select %s, %s, 1, %s, order_reference, %s, delay_hours, delay_seconds, compensation_method, amount, reason_code, evidence_references, policy_version, %s, 'PENDING_APPROVAL', now(), now() + interval '24 hours' "
                "from compensation_proposal_revision where id = %s",
                (
                    uuid.uuid4(),
                    uuid.uuid4(),
                    duplicate_ticket,
                    duplicate_generation,
                    "f" * 64,
                    first_revision_id,
                ),
            )
        raise AssertionError("active intent unique constraint unexpectedly accepted a duplicate")
    except psycopg.errors.UniqueViolation as error:
        assert error.diag.constraint_name == "one_active_logistics_compensation_intent"

    second_generation = uuid.uuid4()

    try:
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            connection.execute(
                "update synthetic_order set delay_hours = 81 where order_reference = %s",
                (proposal_order_reference,),
            )
        raise AssertionError("spring_app unexpectedly changed an authoritative delay fact")
    except psycopg.errors.InsufficientPrivilege:
        pass

    for inconsistent_column, inconsistent_value in (
        ("delay_hours", 81),
        ("delay_seconds", 291600),
    ):
        try:
            with psycopg.connect(os.environ["SPRING_FIXTURE_DATABASE_URI"]) as connection:
                connection.execute(
                    f"update synthetic_order set {inconsistent_column} = %s "
                    "where order_reference = %s",
                    (inconsistent_value, proposal_order_reference),
                )
            raise AssertionError(
                f"fixture role created inconsistent delay fact through {inconsistent_column}"
            )
        except psycopg.errors.CheckViolation as error:
            assert error.diag.constraint_name == (
                "synthetic_order_delay_representations_consistent"
            )

    with psycopg.connect(os.environ["SPRING_FIXTURE_DATABASE_URI"]) as connection:
        connection.execute(
            "update synthetic_order set delay_seconds = 288001 where order_reference = %s",
            (proposal_order_reference,),
        )
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "insert into agent_processing_generation (id, ticket_id, generation_number, thread_id, status, created_at) "
            "values (%s, %s, 3, %s, 'ACTIVE', now())",
            (second_generation, uuid.UUID(proposal_ticket_id), uuid.uuid4()),
        )
    scoped_headers = {
        "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
        "X-Agent-Generation-Id": str(second_generation),
    }
    with customer_browser_client(spring_url) as client:
        facts = client.get(
            f"{spring_url}/internal/agent/tickets/{proposal_ticket_id}/generations/{second_generation}/facts",
            headers={**scoped_headers, "X-Agent-Operation": "READ_INVESTIGATION_FACTS"},
        )
        expect_status(facts, 200)
        evidence_refs = facts.json()["evidenceRefs"]
        replacement = client.post(
            f"{spring_url}/internal/agent/tickets/{proposal_ticket_id}/generations/{second_generation}/conclusions",
            headers={
                **scoped_headers,
                "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                "Idempotency-Key": f"{second_generation}:submit-conclusion",
            },
            json={
                "compensationRequired": True,
                "reasonCode": "LOGISTICS_DELAY",
                "delayHours": 80,
                "delaySeconds": 288001,
                "orderReference": proposal_order_reference,
                "evidenceRefs": evidence_refs,
            },
        )
        expect_status(replacement, 200)
        assert replacement.json()["proposalRevision"] == 2
        assert replacement.json()["proposalStatus"] == "PENDING_APPROVAL"
        try:
            assert replacement_stream_closed.result(timeout=5) is True
        finally:
            replacement_stream_executor.shutdown(wait=False, cancel_futures=True)

        replaced_view = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers=lease_three_headers,
        )
        expect_status(replaced_view, 409)

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        revisions = connection.execute(
            "select proposal_id, revision_number, delay_hours, delay_seconds, amount, status "
            "from compensation_proposal_revision where ticket_id = %s order by revision_number",
            (uuid.UUID(proposal_ticket_id),),
        ).fetchall()
        assert revisions == [
            (proposal_id, 1, 80, 288000, Decimal("26.80"), "SUPERSEDED"),
            (proposal_id, 2, 80, 288001, Decimal("26.80"), "PENDING_APPROVAL"),
        ]
        assert (
            connection.execute(
                "select status from approval_lease where proposal_revision_id = %s and lease_version = 3",
                (first_revision_id,),
            ).fetchone()[0]
            == "REVOKED"
        )
        assert (
            connection.execute(
                "select count(*) from audit_event where ticket_id = %s and event_type in "
                "('APPROVAL_LEASE_CLAIMED', 'APPROVAL_LEASE_RELEASED', 'APPROVAL_LEASE_REVOKED')",
                (uuid.UUID(proposal_ticket_id),),
            ).fetchone()[0]
            == 5
        )

    third_generation = uuid.uuid4()
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update compensation_proposal_revision set status = 'APPROVED' "
            "where ticket_id = %s and revision_number = 2",
            (uuid.UUID(proposal_ticket_id),),
        )
        connection.execute(
            "insert into agent_processing_generation "
            "(id, ticket_id, generation_number, thread_id, status, created_at) "
            "values (%s, %s, 4, %s, 'ACTIVE', now())",
            (third_generation, uuid.UUID(proposal_ticket_id), uuid.uuid4()),
        )
    with psycopg.connect(os.environ["SPRING_FIXTURE_DATABASE_URI"]) as connection:
        connection.execute(
            "update synthetic_order set delay_hours = 82, delay_seconds = 295200 "
            "where order_reference = %s",
            (proposal_order_reference,),
        )
    third_headers = {
        "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
        "X-Agent-Generation-Id": str(third_generation),
    }
    with customer_browser_client(spring_url) as client:
        third_facts = client.get(
            f"{spring_url}/internal/agent/tickets/{proposal_ticket_id}/generations/{third_generation}/facts",
            headers={**third_headers, "X-Agent-Operation": "READ_INVESTIGATION_FACTS"},
        )
        expect_status(third_facts, 200)
        approved_replacement = client.post(
            f"{spring_url}/internal/agent/tickets/{proposal_ticket_id}/generations/{third_generation}/conclusions",
            headers={
                **third_headers,
                "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                "Idempotency-Key": f"{third_generation}:submit-conclusion",
            },
            json={
                "compensationRequired": True,
                "reasonCode": "LOGISTICS_DELAY",
                "delayHours": 82,
                "delaySeconds": 295200,
                "orderReference": proposal_order_reference,
                "evidenceRefs": third_facts.json()["evidenceRefs"],
            },
        )
        expect_status(approved_replacement, 422)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select revision_number, status from compensation_proposal_revision "
            "where ticket_id = %s order by revision_number",
            (uuid.UUID(proposal_ticket_id),),
        ).fetchall() == [(1, "SUPERSEDED"), (2, "APPROVED")]

    def seed_pending_decision_fixture(
        order_reference: str,
        content_digest: str,
        description: str,
        delay_hours: int = 80,
        delay_seconds: int = 288000,
        compensation_method: str = "SIMULATED_PARTIAL_REFUND",
        amount: Decimal = Decimal("26.80"),
        snapshot_delay_seconds: int | None = None,
    ) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        fixture_ticket_id = uuid.uuid4()
        fixture_generation_id = uuid.uuid4()
        fixture_revision_id = uuid.uuid4()
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            connection.execute(
                "insert into support_ticket "
                "(id, customer_id, order_reference, description, lifecycle_state, handling_mode, "
                "created_at, first_responded_at) values "
                "(%s, 'customer-demo', %s, %s, "
                "'INVESTIGATING', 'AGENT', '2026-08-09T13:55:00Z', '2026-08-09T13:56:00Z')",
                (fixture_ticket_id, order_reference, description),
            )
            connection.execute(
                "insert into agent_processing_generation "
                "(id, ticket_id, generation_number, thread_id, status, created_at) "
                "values (%s, %s, 1, %s, 'ACTIVE', '2026-08-09T13:56:00Z')",
                (fixture_generation_id, fixture_ticket_id, uuid.uuid4()),
            )
            connection.execute(
                "insert into compensation_proposal_revision "
                "(id, proposal_id, revision_number, ticket_id, order_reference, generation_id, delay_hours, "
                "delay_seconds, compensation_method, amount, reason_code, evidence_references, policy_version, "
                "content_digest, status, created_at, expires_at) values "
                "(%s, %s, 1, %s, %s, %s, %s, %s, "
                "%s, %s, 'LOGISTICS_DELAY', "
                "jsonb_build_array('order:' || %s, 'logistics:' || %s), "
                "'delay-policy-v1', %s, 'PENDING_APPROVAL', "
                "'2026-08-09T13:57:00Z', '2026-08-10T13:57:00Z')",
                (
                    fixture_revision_id,
                    uuid.uuid4(),
                    fixture_ticket_id,
                    order_reference,
                    fixture_generation_id,
                    delay_hours,
                    delay_seconds,
                    compensation_method,
                    amount,
                    order_reference,
                    order_reference,
                    content_digest,
                ),
            )
            connection.execute(
                "insert into approval_evidence_snapshot "
                "(proposal_revision_id, order_reference, delay_hours, delay_seconds, paid_amount, "
                "total_available_compensation_amount, active_reservation_amount, "
                "remaining_available_compensation_amount, paid, cancelled, fully_refunded, "
                "existing_compensation, evidence_references, captured_at) "
                "select %s, order_reference, %s, %s, paid_amount, available_compensation_amount, "
                "0.00, available_compensation_amount, "
                "paid, cancelled, fully_refunded, existing_compensation, "
                "jsonb_build_array('order:' || order_reference, 'logistics:' || order_reference), "
                "'2026-08-09T13:57:00Z' from synthetic_order where order_reference = %s",
                (
                    fixture_revision_id,
                    delay_hours,
                    delay_seconds if snapshot_delay_seconds is None else snapshot_delay_seconds,
                    order_reference,
                ),
            )
        return fixture_ticket_id, fixture_generation_id, fixture_revision_id

    try:
        seed_pending_decision_fixture(
            "ORDER-DELAY-E2E-NORMAL",
            uuid.uuid4().hex * 2,
            "inconsistent proposal delay proof",
            delay_hours=81,
            delay_seconds=288000,
        )
        raise AssertionError("proposal persisted inconsistent delay representations")
    except psycopg.errors.CheckViolation as error:
        assert error.diag.constraint_name == (
            "compensation_proposal_delay_representations_consistent"
        )

    try:
        seed_pending_decision_fixture(
            "ORDER-DELAY-E2E-NORMAL",
            uuid.uuid4().hex * 2,
            "approval snapshot delay drift proof",
            snapshot_delay_seconds=288001,
        )
        raise AssertionError("approval snapshot delay drifted from its proposal revision")
    except psycopg.errors.ForeignKeyViolation as error:
        assert error.diag.constraint_name == "approval_evidence_proposal_delay_fkey"

    for guarded_amount in (Decimal("0.00"), Decimal("-0.01")):
        try:
            seed_pending_decision_fixture(
                "ORDER-DELAY-E2E-NORMAL",
                uuid.uuid4().hex * 2,
                f"proposal amount guard {guarded_amount}",
                amount=guarded_amount,
            )
            raise AssertionError(f"proposal amount {guarded_amount} unexpectedly persisted")
        except psycopg.errors.CheckViolation as error:
            assert error.diag.constraint_name == "compensation_proposal_revision_amount_check"

    def record_support_participation(
        ticket_id: uuid.UUID, revision_id: uuid.UUID, support_id: str, event_type: str
    ) -> None:
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            participant_proposal_id = connection.execute(
                "select proposal_id from compensation_proposal_revision where id = %s",
                (revision_id,),
            ).fetchone()[0]
            # Production content-action writers must lock before the audit INSERT so a waiter
            # starts that statement with a fresh READ COMMITTED snapshot. Locking only inside
            # the trigger would serialize writers but retain the INSERT statement's old snapshot.
            connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{participant_proposal_id}\nPROPOSAL_SUPPORT_PARTICIPANT_LINEAGE",),
            )
            connection.execute(
                "insert into audit_event "
                "(ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id) "
                "values (%s, %s, %s, clock_timestamp(), "
                "'COMPENSATION_PROPOSAL_REVISION', %s)",
                (ticket_id, event_type, support_id, revision_id),
            )

    participant_digest = "7" * 64
    participant_ticket_id, participant_generation_id, participant_revision_id = (
        seed_pending_decision_fixture(
            "ORDER-DELAY-CANCELLED", participant_digest, "禁止自审继承验收"
        )
    )
    record_support_participation(
        participant_ticket_id,
        participant_revision_id,
        "internal-demo",
        "COMPENSATION_PROPOSAL_REVISION_CREATED_BY_SUPPORT",
    )
    record_support_participation(
        participant_ticket_id,
        participant_revision_id,
        "internal-demo",
        "COMPENSATION_PROPOSAL_REVISION_SUBMITTED_BY_SUPPORT",
    )
    derived_revision_id = uuid.uuid4()
    derived_generation_id = uuid.uuid4()
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        proposal_id = connection.execute(
            "select proposal_id from compensation_proposal_revision where id = %s",
            (participant_revision_id,),
        ).fetchone()[0]
        connection.execute(
            "update compensation_proposal_revision set status = 'SUPERSEDED' where id = %s",
            (participant_revision_id,),
        )
        connection.execute(
            "update agent_processing_generation set status = 'SUPERSEDED' where id = %s",
            (participant_generation_id,),
        )
        connection.execute(
            "insert into agent_processing_generation "
            "(id, ticket_id, generation_number, thread_id, status, created_at) "
            "values (%s, %s, 2, %s, 'ACTIVE', '2026-08-09T13:58:00Z')",
            (derived_generation_id, participant_ticket_id, uuid.uuid4()),
        )
        connection.execute(
            "insert into compensation_proposal_revision "
            "(id, proposal_id, revision_number, ticket_id, order_reference, generation_id, "
            "delay_hours, delay_seconds, compensation_method, amount, reason_code, "
            "evidence_references, policy_version, content_digest, status, created_at, expires_at) "
            "select %s, proposal_id, 2, ticket_id, order_reference, %s, delay_hours, "
            "delay_seconds, compensation_method, amount, reason_code, evidence_references, "
            "policy_version, %s, 'PENDING_APPROVAL', "
            "'2026-08-09T13:58:00Z', '2026-08-10T13:58:00Z' "
            "from compensation_proposal_revision where id = %s",
            (derived_revision_id, derived_generation_id, "8" * 64, participant_revision_id),
        )
        connection.execute(
            "insert into approval_evidence_snapshot "
            "(proposal_revision_id, order_reference, delay_hours, delay_seconds, paid_amount, "
            "total_available_compensation_amount, active_reservation_amount, "
            "remaining_available_compensation_amount, paid, cancelled, fully_refunded, "
            "existing_compensation, evidence_references, captured_at) "
            "select %s, order_reference, delay_hours, delay_seconds, paid_amount, "
            "total_available_compensation_amount, active_reservation_amount, "
            "remaining_available_compensation_amount, paid, cancelled, fully_refunded, "
            "existing_compensation, evidence_references, captured_at "
            "from approval_evidence_snapshot where proposal_revision_id = %s",
            (derived_revision_id, participant_revision_id),
        )
        assert connection.execute(
            "select support_id from compensation_proposal_revision_support_participant "
            "where proposal_revision_id = %s",
            (derived_revision_id,),
        ).fetchall() == [("internal-demo",)]
        assert (
            connection.execute(
                "select count(*) from compensation_proposal_revision_support_participant "
                "where proposal_revision_id = %s and support_id = 'internal-demo'",
                (participant_revision_id,),
            ).fetchone()[0]
            == 1
        )

    lineage_race_revision_id = uuid.uuid4()
    lineage_race_generation_id = uuid.uuid4()
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update compensation_proposal_revision set status = 'SUPERSEDED' where id = %s",
            (derived_revision_id,),
        )
        connection.execute(
            "update agent_processing_generation set status = 'SUPERSEDED' where id = %s",
            (derived_generation_id,),
        )
        connection.execute(
            "insert into agent_processing_generation "
            "(id, ticket_id, generation_number, thread_id, status, created_at) "
            "values (%s, %s, 3, %s, 'ACTIVE', '2026-08-09T13:59:00Z')",
            (lineage_race_generation_id, participant_ticket_id, uuid.uuid4()),
        )

    lineage_barrier = threading.Barrier(2)

    def derive_lineage_revision() -> None:
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            lineage_barrier.wait()
            connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{proposal_id}\nPROPOSAL_SUPPORT_PARTICIPANT_LINEAGE",),
            )
            connection.execute(
                "select id from compensation_proposal_revision where id = %s for update",
                (derived_revision_id,),
            )
            connection.execute(
                "insert into compensation_proposal_revision "
                "(id, proposal_id, revision_number, ticket_id, order_reference, generation_id, "
                "delay_hours, delay_seconds, compensation_method, amount, reason_code, "
                "evidence_references, policy_version, content_digest, status, created_at, "
                "expires_at) "
                "select %s, proposal_id, 3, ticket_id, order_reference, %s, delay_hours, "
                "delay_seconds, compensation_method, amount, reason_code, evidence_references, "
                "policy_version, %s, 'PENDING_APPROVAL', "
                "'2026-08-09T13:59:00Z', '2026-08-10T13:59:00Z' "
                "from compensation_proposal_revision where id = %s",
                (
                    lineage_race_revision_id,
                    lineage_race_generation_id,
                    "9" * 64,
                    derived_revision_id,
                ),
            )

    def append_ancestor_participant() -> None:
        lineage_barrier.wait()
        record_support_participation(
            participant_ticket_id,
            participant_revision_id,
            "late-lineage-support",
            "COMPENSATION_PROPOSAL_REVISION_MODIFIED_BY_SUPPORT",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        derive_future = executor.submit(derive_lineage_revision)
        participant_future = executor.submit(append_ancestor_participant)
        derive_future.result(timeout=20)
        participant_future.result(timeout=20)

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "insert into approval_evidence_snapshot "
            "(proposal_revision_id, order_reference, delay_hours, delay_seconds, paid_amount, "
            "total_available_compensation_amount, active_reservation_amount, "
            "remaining_available_compensation_amount, paid, cancelled, fully_refunded, "
            "existing_compensation, evidence_references, captured_at) "
            "select %s, order_reference, delay_hours, delay_seconds, paid_amount, "
            "total_available_compensation_amount, active_reservation_amount, "
            "remaining_available_compensation_amount, paid, cancelled, fully_refunded, "
            "existing_compensation, evidence_references, captured_at "
            "from approval_evidence_snapshot where proposal_revision_id = %s",
            (lineage_race_revision_id, derived_revision_id),
        )
        assert connection.execute(
            "select support_id from compensation_proposal_revision_support_participant "
            "where proposal_revision_id = %s order by support_id",
            (lineage_race_revision_id,),
        ).fetchall() == [("internal-demo",), ("late-lineage-support",)]
    derived_revision_id = lineage_race_revision_id

    independent_digest = "6" * 64
    independent_ticket_id, _, independent_revision_id = seed_pending_decision_fixture(
        "ORDER-DELAY-UNPAID", independent_digest, "独立提案与负责客服资格验收"
    )
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "insert into support_assignment "
            "(id, ticket_id, support_id, status, assigned_at) "
            "values (%s, %s, 'internal-demo', 'ACTIVE', clock_timestamp())",
            (uuid.uuid4(), independent_ticket_id),
        )
        assert (
            connection.execute(
                "select count(*) from compensation_proposal_revision_support_participant "
                "where proposal_revision_id = %s",
                (independent_revision_id,),
            ).fetchone()[0]
            == 0
        )

    with httpx.Client(timeout=20.0) as dual_client:
        login_human(
            dual_client,
            spring_url,
            "internal-demo",
            ["SUPPORT_WORKBENCH_ACCESS", "APPROVAL_WORKBENCH_ACCESS"],
        )
        dual_queue = dual_client.get(f"{spring_url}/api/approver/compensation-proposals")
        expect_status(dual_queue, 200)
        dual_queue_ids = {item["proposalRevisionId"] for item in dual_queue.json()}
        assert str(derived_revision_id) not in dual_queue_ids
        assert str(independent_revision_id) in dual_queue_ids

        forbidden_claim = dual_client.post(
            f"{spring_url}/api/approver/compensation-proposals/{derived_revision_id}/claims",
            headers={"Idempotency-Key": f"participant-claim-{uuid.uuid4()}"},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(forbidden_claim, 404)

        eligible_claim = dual_client.post(
            f"{spring_url}/api/approver/compensation-proposals/{independent_revision_id}/claims",
            headers={"Idempotency-Key": f"eligible-claim-{uuid.uuid4()}"},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(eligible_claim, 201)
        eligible_lease = eligible_claim.json()
        eligible_rejection_request_id = f"eligible-reject-{uuid.uuid4()}"
        eligible_rejection_url = (
            f"{spring_url}/api/approver/compensation-proposals/{independent_revision_id}/reject"
        )
        eligible_rejection_body = {
            "proposalRevision": 1,
            "contentDigest": independent_digest,
            "internalReason": "未参与提案内容，仍有审批资格",
        }
        eligible_rejection = dual_client.post(
            eligible_rejection_url,
            headers={
                "Idempotency-Key": eligible_rejection_request_id,
                "X-Approval-Lease-Token": eligible_lease["leaseToken"],
                "X-Approval-Lease-Version": str(eligible_lease["leaseVersion"]),
            },
            json=eligible_rejection_body,
        )
        expect_status(eligible_rejection, 200)
        record_support_participation(
            independent_ticket_id,
            independent_revision_id,
            "internal-demo",
            "COMPENSATION_PROPOSAL_REVISION_SUBMITTED_BY_SUPPORT",
        )
        forbidden_decision_replay = dual_client.post(
            eligible_rejection_url,
            headers={
                "Idempotency-Key": eligible_rejection_request_id,
                "X-Approval-Lease-Token": eligible_lease["leaseToken"],
                "X-Approval-Lease-Version": str(eligible_lease["leaseVersion"]),
            },
            json=eligible_rejection_body,
        )
        expect_status(forbidden_decision_replay, 404)

    for decision, order_reference, content_digest in (
        ("approve", "ORDER-DELAY-REFUNDED", "4" * 64),
        ("reject", "ORDER-DELAY-COMPENSATED", "5" * 64),
    ):
        decision_ticket_id, _, decision_revision_id = seed_pending_decision_fixture(
            order_reference, content_digest, f"参与后禁止{decision}验收"
        )
        with httpx.Client(timeout=20.0) as dual_client:
            login_human(
                dual_client,
                spring_url,
                "internal-demo",
                ["SUPPORT_WORKBENCH_ACCESS", "APPROVAL_WORKBENCH_ACCESS"],
            )
            claim_request_id = f"pre-participation-{uuid.uuid4()}"
            claim_url = (
                f"{spring_url}/api/approver/compensation-proposals/{decision_revision_id}/claims"
            )
            claim = dual_client.post(
                claim_url,
                headers={"Idempotency-Key": claim_request_id},
                json={"requestedLeaseSeconds": 900},
            )
            expect_status(claim, 201)
            lease = claim.json()
            record_support_participation(
                decision_ticket_id,
                decision_revision_id,
                "internal-demo",
                "COMPENSATION_PROPOSAL_REVISION_MODIFIED_BY_SUPPORT",
            )
            forbidden_claim_replay = dual_client.post(
                claim_url,
                headers={"Idempotency-Key": claim_request_id},
                json={"requestedLeaseSeconds": 900},
            )
            expect_status(forbidden_claim_replay, 404)
            rejected_decision = dual_client.post(
                f"{spring_url}/api/approver/compensation-proposals/{decision_revision_id}/{decision}",
                headers={
                    "Idempotency-Key": f"post-participation-{uuid.uuid4()}",
                    "X-Approval-Lease-Token": lease["leaseToken"],
                    "X-Approval-Lease-Version": str(lease["leaseVersion"]),
                },
                json={
                    "proposalRevision": 1,
                    "contentDigest": content_digest,
                    **(
                        {"internalReason": "不得自审"}
                        if decision == "reject"
                        else {"internalNote": "不得自审"}
                    ),
                },
            )
            expect_status(rejected_decision, 404)
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            assert (
                connection.execute(
                    "select status from approval_lease where proposal_revision_id = %s",
                    (decision_revision_id,),
                ).fetchone()[0]
                == "REVOKED"
            )
            assert (
                connection.execute(
                    "select count(*) from proposal_decision where proposal_revision_id = %s",
                    (decision_revision_id,),
                ).fetchone()[0]
                == 0
            )
            connection.execute(
                "update compensation_proposal_revision set status = 'SUPERSEDED' where id = %s",
                (decision_revision_id,),
            )

    participant_race_ticket_id, _, race_revision_id = seed_pending_decision_fixture(
        "ORDER-DELAY-LOW-ALLOWANCE", "3" * 64, "参与事实与领取竞争验收"
    )
    participant_claim_barrier = threading.Barrier(2)

    def race_participant_claim() -> int:
        with httpx.Client(timeout=20.0) as dual_client:
            login_human(
                dual_client,
                spring_url,
                "internal-demo",
                ["SUPPORT_WORKBENCH_ACCESS", "APPROVAL_WORKBENCH_ACCESS"],
            )
            participant_claim_barrier.wait()
            return dual_client.post(
                f"{spring_url}/api/approver/compensation-proposals/{race_revision_id}/claims",
                headers={"Idempotency-Key": f"participant-race-{uuid.uuid4()}"},
                json={"requestedLeaseSeconds": 900},
            ).status_code

    def race_participation_fact() -> None:
        participant_claim_barrier.wait()
        record_support_participation(
            participant_race_ticket_id,
            race_revision_id,
            "internal-demo",
            "COMPENSATION_PROPOSAL_REVISION_MODIFIED_BY_SUPPORT",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claim_future = executor.submit(race_participant_claim)
        participant_future = executor.submit(race_participation_fact)
        participant_future.result(timeout=20)
        assert claim_future.result(timeout=20) in (201, 404)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert (
            connection.execute(
                "select count(*) from compensation_proposal_revision_support_participant "
                "where proposal_revision_id = %s and support_id = 'internal-demo'",
                (race_revision_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "select count(*) from approval_lease where proposal_revision_id = %s "
                "and status = 'ACTIVE'",
                (race_revision_id,),
            ).fetchone()[0]
            == 0
        )
        connection.execute(
            "update compensation_proposal_revision set status = 'SUPERSEDED' where id = %s",
            (race_revision_id,),
        )

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert (
            connection.execute(
                "select count(*) from approval_lease where proposal_revision_id = %s",
                (derived_revision_id,),
            ).fetchone()[0]
            == 0
        )
        connection.execute(
            "update compensation_proposal_revision set status = 'SUPERSEDED' where id = %s",
            (derived_revision_id,),
        )

    reserved_request = f"issue-55-{uuid.uuid4()}"
    with customer_browser_client(spring_url) as client:
        reserved_ticket = client.post(
            f"{spring_url}/api/customer/tickets",
            headers={
                "Idempotency-Key": reserved_request,
            },
            json={
                "orderReference": "ORDER-DELAY-APPROVAL-RESERVED",
                "description": "已有额度预占时仍可审批的合成场景",
            },
        )
        expect_status(reserved_ticket, 201)
        reserved_ticket_id = uuid.UUID(reserved_ticket.json()["ticketId"])

    reserved_proposal = None
    for _ in range(60):
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            reserved_proposal = connection.execute(
                "select p.id, p.content_digest, s.total_available_compensation_amount, "
                "s.active_reservation_amount, s.remaining_available_compensation_amount "
                "from compensation_proposal_revision p "
                "join approval_evidence_snapshot s on s.proposal_revision_id = p.id "
                "where p.ticket_id = %s",
                (reserved_ticket_id,),
            ).fetchone()
        if reserved_proposal is not None:
            break
        time.sleep(0.5)
    assert reserved_proposal is not None
    reserved_revision_id, reserved_digest = reserved_proposal[:2]
    assert reserved_proposal[2:] == (
        Decimal("268.00"),
        Decimal("10.00"),
        Decimal("258.00"),
    )

    with customer_browser_client(spring_url) as client:
        reserved_claim = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{reserved_revision_id}/claims",
            headers={
                **approver_headers,
                "Idempotency-Key": f"reserved-claim-{uuid.uuid4()}",
            },
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(reserved_claim, 201)
        reserved_lease = reserved_claim.json()
        reserved_headers = {
            **approver_headers,
            "X-Approval-Lease-Token": reserved_lease["leaseToken"],
            "X-Approval-Lease-Version": str(reserved_lease["leaseVersion"]),
        }
        reserved_view = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{reserved_revision_id}/approval-view",
            headers=reserved_headers,
        )
        expect_status(reserved_view, 200)
        assert reserved_view.json()["evidenceSnapshot"] == {
            "delaySeconds": 288000,
            "paidAmount": "268.00",
            "totalAvailableCompensationAmount": "268.00",
            "activeReservationAmount": "10.00",
            "remainingAvailableCompensationAmount": "258.00",
        }
        reserved_approval = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{reserved_revision_id}/approve",
            headers={
                **reserved_headers,
                "Idempotency-Key": f"reserved-approve-{uuid.uuid4()}",
            },
            json={"proposalRevision": 1, "contentDigest": reserved_digest},
        )
        expect_status(reserved_approval, 200)
        assert reserved_approval.json()["executionStatus"] == "READY"

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select coalesce(sum(amount), 0), count(*) from compensation_reservation "
            "where order_reference = 'ORDER-DELAY-APPROVAL-RESERVED' and status = 'ACTIVE'"
        ).fetchone() == (Decimal("36.80"), 2)
        assert (
            connection.execute(
                "select count(*) from compensation_execution "
                "where order_reference = 'ORDER-DELAY-APPROVAL-RESERVED'"
            ).fetchone()[0]
            == 1
        )

    approval_digest = "9" * 64
    approval_ticket_id, _, approval_revision_id = seed_pending_decision_fixture(
        "ORDER-DELAY-APPROVAL", approval_digest, "审批成功验收"
    )
    with customer_browser_client(spring_url) as client:
        approval_claim = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{approval_revision_id}/claims",
            headers={**approver_headers, "Idempotency-Key": f"approve-claim-{uuid.uuid4()}"},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(approval_claim, 201)
        approval_lease = approval_claim.json()
        approval_headers = {
            **approver_headers,
            "X-Approval-Lease-Token": approval_lease["leaseToken"],
            "X-Approval-Lease-Version": str(approval_lease["leaseVersion"]),
        }
        approval_view_before_decision = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{approval_revision_id}/approval-view",
            headers=approval_headers,
        )
        expect_status(approval_view_before_decision, 200)
        decision_stream_executor, decision_stream_closed = start_authorized_sse(
            f"{spring_url}/api/approver/compensation-proposals/{approval_revision_id}/approval-view/events",
            approval_headers,
            approval_view_before_decision.json()["cursor"],
        )
        approval_url = (
            f"{spring_url}/api/approver/compensation-proposals/{approval_revision_id}/approve"
        )
        approval_body = {
            "proposalRevision": 1,
            "contentDigest": approval_digest,
            "internalNote": "当前事实与政策一致",
        }
        approval_request_id = f"approve-decision-{uuid.uuid4()}"
        approved = client.post(
            approval_url,
            headers={**approval_headers, "Idempotency-Key": approval_request_id},
            json=approval_body,
        )
        expect_status(approved, 200)
        try:
            assert decision_stream_closed.result(timeout=5) is True
        finally:
            decision_stream_executor.shutdown(wait=False, cancel_futures=True)
        approved_payload = approved.json()
        assert approved_payload["decision"] == "APPROVED"
        assert approved_payload["executionStatus"] == "READY"
        assert approved_payload["replayed"] is False
        assert "executionSucceeded" not in approved_payload
        approval_replay = client.post(
            approval_url,
            headers={**approval_headers, "Idempotency-Key": approval_request_id},
            json=approval_body,
        )
        expect_status(approval_replay, 200)
        assert approval_replay.json() == {**approved_payload, "replayed": True}
        approval_conflict = client.post(
            approval_url,
            headers={**approval_headers, "Idempotency-Key": approval_request_id},
            json={**approval_body, "internalNote": "不同参数"},
        )
        expect_status(approval_conflict, 409)
        decided_view = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{approval_revision_id}/approval-view",
            headers=approval_headers,
        )
        expect_status(decided_view, 409)
        reject_after_approval = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{approval_revision_id}/reject",
            headers={**approval_headers, "Idempotency-Key": f"reject-approved-{uuid.uuid4()}"},
            json={
                "proposalRevision": 1,
                "contentDigest": approval_digest,
                "internalReason": "最终批准不可撤销",
            },
        )
        expect_status(reject_after_approval, 409)
        approval_customer = client.get(
            f"{spring_url}/api/customer/tickets/{approval_ticket_id}",
        )
        expect_status(approval_customer, 200)
        approval_customer_payload = approval_customer.json()
        assert approval_customer_payload["messages"][-1] == {
            "author": "SUPPORT",
            "body": "补偿方案已获批准，正在等待补偿处理。",
            "sentAt": "2026-08-09T14:00:00Z",
        }
        assert "SUCCEEDED" not in json.dumps(approval_customer_payload)

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        approval_record = connection.execute(
            "select d.id, d.decision_type, d.internal_reason, p.status, l.status, "
            "r.id, r.status, e.id, e.status, e.idempotency_key, e.amount "
            "from proposal_decision d "
            "join compensation_proposal_revision p on p.id = d.proposal_revision_id "
            "join approval_lease l on l.proposal_revision_id = d.proposal_revision_id "
            "and l.lease_version = d.lease_version "
            "join compensation_reservation r on r.proposal_revision_id = d.proposal_revision_id "
            "join compensation_execution e on e.decision_id = d.id "
            "where d.proposal_revision_id = %s",
            (approval_revision_id,),
        ).fetchone()
        assert approval_record[1:5] == (
            "APPROVED",
            approval_body["internalNote"],
            "APPROVED",
            "DECIDED",
        )
        assert approval_record[6] == "ACTIVE"
        assert str(approval_record[7]) == approved_payload["executionId"]
        assert approval_record[8:] == (
            "READY",
            f"compensation-execution:{approval_revision_id}",
            Decimal("26.80"),
        )
        assert (
            connection.execute(
                "select count(*) from proposal_decision where proposal_revision_id = %s",
                (approval_revision_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "select count(*) from compensation_execution where proposal_revision_id = %s",
                (approval_revision_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "select count(*) from audit_event where subject_id = %s "
                "and event_type = 'COMPENSATION_PROPOSAL_APPROVED'",
                (approval_record[0],),
            ).fetchone()[0]
            == 1
        )

    executor_headers = {"Authorization": f"Bearer {os.environ['EXECUTOR_MACHINE_TOKEN']}"}
    with customer_browser_client(spring_url) as client:
        assignments = client.get(
            f"{spring_url}/internal/compensation-executions", headers=executor_headers
        )
        expect_status(assignments, 200)
        assert any(
            item["executionId"] == approved_payload["executionId"] and item["status"] == "READY"
            for item in assignments.json()
        )
        denied_assignments = client.get(
            f"{spring_url}/internal/compensation-executions",
            headers={"Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}"},
        )
        expect_status(denied_assignments, 403)

    execution_id = approved_payload["executionId"]
    claim_request_ids = [f"execution-claim-{uuid.uuid4()}" for _ in range(2)]
    claim_barrier = threading.Barrier(2)

    def claim_execution(request_id: str) -> httpx.Response:
        claim_barrier.wait()
        with customer_browser_client(spring_url) as client:
            return client.post(
                f"{spring_url}/internal/compensation-executions/{execution_id}/claims",
                headers={**executor_headers, "Idempotency-Key": request_id},
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        execution_claim_responses = list(executor.map(claim_execution, claim_request_ids))
    assert sorted(response.status_code for response in execution_claim_responses) == [201, 409]
    winning_claim_index = next(
        index
        for index, response in enumerate(execution_claim_responses)
        if response.status_code == 201
    )
    winning_claim = execution_claim_responses[winning_claim_index].json()
    winning_claim_request_id = claim_request_ids[winning_claim_index]
    assert winning_claim["status"] == "PROCESSING"
    assert winning_claim["compensationMethod"] == "SIMULATED_PARTIAL_REFUND"
    assert winning_claim["amount"] == 26.80

    with customer_browser_client(spring_url) as client:
        claim_replay = client.post(
            f"{spring_url}/internal/compensation-executions/{execution_id}/claims",
            headers={**executor_headers, "Idempotency-Key": winning_claim_request_id},
        )
        expect_status(claim_replay, 200)
        assert claim_replay.json() == {**winning_claim, "replayed": True}
        claim_identity_conflict = client.post(
            f"{spring_url}/internal/compensation-executions/{uuid.uuid4()}/claims",
            headers={**executor_headers, "Idempotency-Key": winning_claim_request_id},
        )
        expect_status(claim_identity_conflict, 409)
        bound_result = {
            "attemptId": winning_claim["attemptId"],
            "idempotencyKey": winning_claim["idempotencyKey"],
            "parameterDigest": winning_claim["parameterDigest"],
        }
        provider_execution = client.post(
            f"{spring_url}/internal/compensation-simulator/{execution_id}/executions",
            headers={**executor_headers, "Idempotency-Key": winning_claim["idempotencyKey"]},
            json={"parameterDigest": winning_claim["parameterDigest"], "amount": 26.80},
        )
        expect_status(provider_execution, 504)
        unknown_request_id = f"unknown-{execution_id}"
        unknown = client.post(
            f"{spring_url}/internal/compensation-executions/{execution_id}/unknown",
            headers={**executor_headers, "Idempotency-Key": unknown_request_id},
            json=bound_result,
        )
        expect_status(unknown, 200)
        assert unknown.json()["status"] == "UNKNOWN"
        assert unknown.json()["customerMessage"] == "补偿结果正在自动确认中，请勿重复提交。"
        unknown_customer = client.get(
            f"{spring_url}/api/customer/tickets/{approval_ticket_id}",
        )
        expect_status(unknown_customer, 200)
        assert (
            unknown_customer.json()["messages"][-1]["body"]
            == "补偿结果正在自动确认中，请勿重复提交。"
        )
        ordinary_retry = client.post(
            f"{spring_url}/internal/compensation-executions/{execution_id}/claims",
            headers={**executor_headers, "Idempotency-Key": f"forbidden-retry-{uuid.uuid4()}"},
        )
        expect_status(ordinary_retry, 409)
        provider_reconciliation = client.get(
            f"{spring_url}/internal/compensation-simulator/{execution_id}/reconciliation",
            headers={**executor_headers, "Idempotency-Key": winning_claim["idempotencyKey"]},
        )
        expect_status(provider_reconciliation, 200)
        provider_reconciliation_payload = provider_reconciliation.json()
        assert provider_reconciliation_payload["outcome"] == "FOUND"
        assert (
            provider_reconciliation_payload["resultReference"] == f"simulated-refund:{execution_id}"
        )
        forged_reconciliation = client.post(
            f"{spring_url}/internal/compensation-executions/{execution_id}/reconciliations",
            headers={**executor_headers, "Idempotency-Key": f"forged-reconcile-{uuid.uuid4()}"},
            json={
                **provider_reconciliation_payload,
                "queryId": "provider-query:forged",
            },
        )
        expect_status(forged_reconciliation, 409)
        reconciliation_request_id = (
            f"reconcile:{execution_id}:{provider_reconciliation_payload['queryId']}"
        )
        reconciliation_barrier = threading.Barrier(2)

        def submit_same_reconciliation() -> httpx.Response:
            reconciliation_barrier.wait()
            with customer_browser_client(spring_url) as concurrent_client:
                return concurrent_client.post(
                    f"{spring_url}/internal/compensation-executions/{execution_id}/reconciliations",
                    headers={**executor_headers, "Idempotency-Key": reconciliation_request_id},
                    json=provider_reconciliation_payload,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent_reconciliations = list(
                executor.map(lambda _: submit_same_reconciliation(), range(2))
            )
        assert [response.status_code for response in concurrent_reconciliations] == [200, 200]
        assert sorted(response.json()["replayed"] for response in concurrent_reconciliations) == [
            False,
            True,
        ]
        succeeded_payload = next(
            response.json()
            for response in concurrent_reconciliations
            if not response.json()["replayed"]
        )
        assert succeeded_payload["status"] == "SUCCEEDED"
        assert succeeded_payload["customerMessage"] == (
            "已完成 26.80 CNY 模拟部分退款，退回原支付方式（尾号 4242）。"
        )
        reconciliation_replay = client.post(
            f"{spring_url}/internal/compensation-executions/{execution_id}/reconciliations",
            headers={**executor_headers, "Idempotency-Key": reconciliation_request_id},
            json=provider_reconciliation_payload,
        )
        expect_status(reconciliation_replay, 200)
        assert reconciliation_replay.json() == {**succeeded_payload, "replayed": True}
        reconciliation_redelivery = client.post(
            f"{spring_url}/internal/compensation-executions/{execution_id}/reconciliations",
            headers={**executor_headers, "Idempotency-Key": f"redelivered-{uuid.uuid4()}"},
            json=provider_reconciliation_payload,
        )
        expect_status(reconciliation_redelivery, 200)
        assert reconciliation_redelivery.json() == {**succeeded_payload, "replayed": True}
        terminal_claim_request_id = f"terminal-claim-{uuid.uuid4()}"
        terminal_claim = client.post(
            f"{spring_url}/internal/compensation-executions/{execution_id}/claims",
            headers={**executor_headers, "Idempotency-Key": terminal_claim_request_id},
        )
        expect_status(terminal_claim, 200)
        assert terminal_claim.json()["status"] == "SUCCEEDED"
        terminal_claim_identity_conflict = client.post(
            f"{spring_url}/internal/compensation-executions/{uuid.uuid4()}/claims",
            headers={**executor_headers, "Idempotency-Key": terminal_claim_request_id},
        )
        expect_status(terminal_claim_identity_conflict, 409)
        execution_customer = client.get(
            f"{spring_url}/api/customer/tickets/{approval_ticket_id}",
        )
        expect_status(execution_customer, 200)
        execution_customer_payload = execution_customer.json()
        assert execution_customer_payload["ticket"]["lifecycleState"] == "RESOLVED"
        assert (
            execution_customer_payload["messages"][-1]["body"]
            == succeeded_payload["customerMessage"]
        )
        customer_projection_text = json.dumps(execution_customer_payload, ensure_ascii=False)
        assert execution_id not in customer_projection_text
        assert winning_claim["idempotencyKey"] not in customer_projection_text
        assert winning_claim["parameterDigest"] not in customer_projection_text

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select e.status, r.status, o.existing_compensation "
            "from compensation_execution e "
            "join compensation_reservation r on r.id = e.reservation_id "
            "join synthetic_order o on o.order_reference = e.order_reference where e.id = %s",
            (uuid.UUID(execution_id),),
        ).fetchone() == ("SUCCEEDED", "CONSUMED", True)
        assert (
            connection.execute(
                "select count(*) from compensation_execution_attempt where execution_id = %s",
                (uuid.UUID(execution_id),),
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "select count(*) from compensation_execution_result where execution_id = %s",
                (uuid.UUID(execution_id),),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "select count(*) from simulated_partial_refund where execution_id = %s",
                (uuid.UUID(execution_id),),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "select count(*) from simulated_compensation_provider_operation where execution_id = %s",
                (uuid.UUID(execution_id),),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "select count(*) from audit_event where ticket_id = %s and "
                "event_type in ('COMPENSATION_EXECUTION_SUCCEEDED', 'TICKET_RESOLVED')",
                (approval_ticket_id,),
            ).fetchone()[0]
            == 2
        )

    def approve_partial_execution(order_reference: str) -> tuple[str, str, dict[str, object]]:
        digest = uuid.uuid4().hex * 2
        ticket, _, revision = seed_pending_decision_fixture(
            order_reference,
            digest,
            f"{order_reference} 对账验收",
            80,
            288000,
            "SIMULATED_PARTIAL_REFUND",
            Decimal("26.80"),
        )
        with customer_browser_client(spring_url) as client:
            lease_response = client.post(
                f"{spring_url}/api/approver/compensation-proposals/{revision}/claims",
                headers={**approver_headers, "Idempotency-Key": f"reconcile-claim-{uuid.uuid4()}"},
                json={"requestedLeaseSeconds": 900},
            )
            expect_status(lease_response, 201)
            lease = lease_response.json()
            approval_response = client.post(
                f"{spring_url}/api/approver/compensation-proposals/{revision}/approve",
                headers={
                    **approver_headers,
                    "X-Approval-Lease-Token": lease["leaseToken"],
                    "X-Approval-Lease-Version": str(lease["leaseVersion"]),
                    "Idempotency-Key": f"reconcile-approve-{uuid.uuid4()}",
                },
                json={"proposalRevision": 1, "contentDigest": digest},
            )
            expect_status(approval_response, 200)
            scenario_execution_id = approval_response.json()["executionId"]
            claim_response = client.post(
                f"{spring_url}/internal/compensation-executions/{scenario_execution_id}/claims",
                headers={**executor_headers, "Idempotency-Key": f"scenario-claim-{uuid.uuid4()}"},
            )
            expect_status(claim_response, 201)
        return scenario_execution_id, str(ticket), claim_response.json()

    def report_unknown(
        client: httpx.Client, scenario_execution_id: str, claim: dict[str, object]
    ) -> None:
        unknown_response = client.post(
            f"{spring_url}/internal/compensation-executions/{scenario_execution_id}/unknown",
            headers={
                **executor_headers,
                "Idempotency-Key": f"scenario-unknown-{scenario_execution_id}",
            },
            json={
                "attemptId": claim["attemptId"],
                "idempotencyKey": claim["idempotencyKey"],
                "parameterDigest": claim["parameterDigest"],
            },
        )
        expect_status(unknown_response, 200)
        assert unknown_response.json()["status"] == "UNKNOWN"

    before_failure_id, _, before_failure_claim = approve_partial_execution(
        "ORDER-DELAY-EXECUTION-BEFORE-FAILURE"
    )
    not_found_id, _, not_found_claim = approve_partial_execution("ORDER-DELAY-EXECUTION-NOT-FOUND")
    persistent_unknown_id, _, persistent_unknown_claim = approve_partial_execution(
        "ORDER-DELAY-EXECUTION-UNKNOWN"
    )
    with customer_browser_client(spring_url) as client:
        before_failure_provider = client.post(
            f"{spring_url}/internal/compensation-simulator/{before_failure_id}/executions",
            headers={
                **executor_headers,
                "Idempotency-Key": str(before_failure_claim["idempotencyKey"]),
                "X-Simulation-Scenario": "BEFORE_EFFECT_FAILURE",
            },
            json={"parameterDigest": before_failure_claim["parameterDigest"], "amount": 26.80},
        )
        expect_status(before_failure_provider, 200)
        assert before_failure_provider.json()["outcome"] == "CONFIRMED_NOT_OCCURRED"
        before_failure = client.post(
            f"{spring_url}/internal/compensation-executions/{before_failure_id}/failures",
            headers={**executor_headers, "Idempotency-Key": f"failure-{before_failure_id}"},
            json={
                "attemptId": before_failure_claim["attemptId"],
                "idempotencyKey": before_failure_claim["idempotencyKey"],
                "parameterDigest": before_failure_claim["parameterDigest"],
            },
        )
        expect_status(before_failure, 200)
        assert before_failure.json()["status"] == "FAILED"

        for scenario_execution_id, claim, scenario, expected in (
            (not_found_id, not_found_claim, "RECONCILIATION_NOT_FOUND", "NOT_FOUND"),
            (persistent_unknown_id, persistent_unknown_claim, "RECONCILIATION_UNKNOWN", "UNKNOWN"),
        ):
            provider = client.post(
                f"{spring_url}/internal/compensation-simulator/{scenario_execution_id}/executions",
                headers={
                    **executor_headers,
                    "Idempotency-Key": str(claim["idempotencyKey"]),
                    "X-Simulation-Scenario": scenario,
                },
                json={"parameterDigest": claim["parameterDigest"], "amount": 26.80},
            )
            expect_status(provider, 504)
            report_unknown(client, scenario_execution_id, claim)
            reconciliation_rounds = 3 if expected == "UNKNOWN" else 1
            for _ in range(reconciliation_rounds):
                query = client.get(
                    f"{spring_url}/internal/compensation-simulator/{scenario_execution_id}/reconciliation",
                    headers={**executor_headers, "Idempotency-Key": str(claim["idempotencyKey"])},
                )
                expect_status(query, 200)
                assert query.json()["outcome"] == expected
                reconciled_scenario = client.post(
                    f"{spring_url}/internal/compensation-executions/{scenario_execution_id}/reconciliations",
                    headers={
                        **executor_headers,
                        "Idempotency-Key": f"scenario-reconcile-{uuid.uuid4()}",
                    },
                    json=query.json(),
                )
                expect_status(reconciled_scenario, 200)
                assert reconciled_scenario.json()["status"] == (
                    "UNKNOWN" if expected == "UNKNOWN" else "FAILED"
                )

        exhausted_query = client.get(
            f"{spring_url}/internal/compensation-simulator/{persistent_unknown_id}/reconciliation",
            headers={
                **executor_headers,
                "Idempotency-Key": str(persistent_unknown_claim["idempotencyKey"]),
            },
        )
        expect_status(exhausted_query, 200)
        exhausted_reconciliation = client.post(
            f"{spring_url}/internal/compensation-executions/{persistent_unknown_id}/reconciliations",
            headers={**executor_headers, "Idempotency-Key": f"scenario-reconcile-{uuid.uuid4()}"},
            json=exhausted_query.json(),
        )
        expect_status(exhausted_reconciliation, 409)

        assignments_after_budget = client.get(
            f"{spring_url}/internal/compensation-executions",
            headers=executor_headers,
        )
        expect_status(assignments_after_budget, 200)
        assert not any(
            item["executionId"] == persistent_unknown_id for item in assignments_after_budget.json()
        )

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select e.status, r.status from compensation_execution e "
            "join compensation_reservation r on r.id = e.reservation_id where e.id = %s",
            (uuid.UUID(before_failure_id),),
        ).fetchone() == ("FAILED", "RELEASED")
        assert connection.execute(
            "select e.status, r.status from compensation_execution e "
            "join compensation_reservation r on r.id = e.reservation_id where e.id = %s",
            (uuid.UUID(not_found_id),),
        ).fetchone() == ("FAILED", "RELEASED")
        assert connection.execute(
            "select e.status, r.status, e.reconciliation_count from compensation_execution e "
            "join compensation_reservation r on r.id = e.reservation_id where e.id = %s",
            (uuid.UUID(persistent_unknown_id),),
        ).fetchone() == ("UNKNOWN", "ACTIVE", 3)
        assert (
            connection.execute(
                "select count(*) from domain_operation_alert where execution_id = %s",
                (uuid.UUID(persistent_unknown_id),),
            ).fetchone()[0]
            == 1
        )

    def assert_success_sla_projection(ticket: uuid.UUID) -> None:
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            assert connection.execute(
                "select objective, fact_type, elapsed_seconds, occurred_at from ticket_sla_fact "
                "where ticket_id = %s order by objective, fact_type",
                (ticket,),
            ).fetchall() == [
                (
                    "RESOLUTION",
                    "BREACH",
                    86400,
                    datetime.datetime.fromisoformat("2026-08-09T14:00:00+00:00"),
                ),
                (
                    "RESOLUTION",
                    "WARNING",
                    86400,
                    datetime.datetime.fromisoformat("2026-08-09T14:00:00+00:00"),
                ),
            ]
            assert (
                connection.execute(
                    "select count(*) from audit_event where ticket_id = %s "
                    "and event_type in ('SLA_RESOLUTION_WARNING', 'SLA_RESOLUTION_BREACH')",
                    (ticket,),
                ).fetchone()[0]
                == 2
            )
            assert (
                connection.execute(
                    "select count(*) from support_sla_notification where ticket_id = %s "
                    "and objective = 'RESOLUTION' and fact_type = 'WARNING'",
                    (ticket,),
                ).fetchone()[0]
                == 1
            )
            assert (
                connection.execute(
                    "select count(*) from shared_support_queue_entry where ticket_id = %s "
                    "and reason_code = 'SLA_BREACH'",
                    (ticket,),
                ).fetchone()[0]
                == 1
            )

    def approve_and_execute_coupon(
        order_reference: str, delay_hours: int, delay_seconds: int, amount: Decimal
    ) -> tuple[str, str]:
        digest = uuid.uuid4().hex * 2
        ticket, _, revision = seed_pending_decision_fixture(
            order_reference,
            digest,
            f"{amount} CNY 优惠券执行验收",
            delay_hours,
            delay_seconds,
            "COUPON",
            amount,
        )
        with customer_browser_client(spring_url) as client:
            lease_response = client.post(
                f"{spring_url}/api/approver/compensation-proposals/{revision}/claims",
                headers={**approver_headers, "Idempotency-Key": f"coupon-claim-{uuid.uuid4()}"},
                json={"requestedLeaseSeconds": 900},
            )
            expect_status(lease_response, 201)
            lease = lease_response.json()
            approval_response = client.post(
                f"{spring_url}/api/approver/compensation-proposals/{revision}/approve",
                headers={
                    **approver_headers,
                    "X-Approval-Lease-Token": lease["leaseToken"],
                    "X-Approval-Lease-Version": str(lease["leaseVersion"]),
                    "Idempotency-Key": f"coupon-approve-{uuid.uuid4()}",
                },
                json={"proposalRevision": 1, "contentDigest": digest},
            )
            expect_status(approval_response, 200)
            coupon_execution_id = approval_response.json()["executionId"]
            coupon_claim = client.post(
                f"{spring_url}/internal/compensation-executions/{coupon_execution_id}/claims",
                headers={**executor_headers, "Idempotency-Key": f"coupon-execute-{uuid.uuid4()}"},
            )
            expect_status(coupon_claim, 201)
            coupon_claim_payload = coupon_claim.json()
            with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
                connection.execute(
                    "update support_ticket set resolution_elapsed_seconds = 86400, "
                    "resolution_running_since = null where id = %s",
                    (ticket,),
                )
                connection.execute(
                    "insert into support_assignment "
                    "(id, ticket_id, support_id, status, assigned_at) "
                    "values (%s, %s, 'support-demo', 'ACTIVE', '2026-08-09T14:00:00Z')",
                    (uuid.uuid4(), ticket),
                )
            success_request_id = f"coupon-result-{uuid.uuid4()}"
            coupon_success = client.post(
                f"{spring_url}/internal/compensation-executions/{coupon_execution_id}/success",
                headers={**executor_headers, "Idempotency-Key": success_request_id},
                json={
                    "attemptId": coupon_claim_payload["attemptId"],
                    "idempotencyKey": coupon_claim_payload["idempotencyKey"],
                    "parameterDigest": coupon_claim_payload["parameterDigest"],
                },
            )
            expect_status(coupon_success, 200)
            expected_message = f"已发放 {amount:.2f} CNY 优惠券。"
            assert coupon_success.json()["customerMessage"] == expected_message
            assert_success_sla_projection(ticket)
            same_request_parameter_conflict = client.post(
                f"{spring_url}/internal/compensation-executions/{coupon_execution_id}/success",
                headers={**executor_headers, "Idempotency-Key": success_request_id},
                json={
                    "attemptId": str(uuid.uuid4()),
                    "idempotencyKey": coupon_claim_payload["idempotencyKey"],
                    "parameterDigest": coupon_claim_payload["parameterDigest"],
                },
            )
            expect_status(same_request_parameter_conflict, 409)
            terminal_barrier = threading.Barrier(2)

            def redeliver_terminal_success(attempt_id: str) -> httpx.Response:
                terminal_barrier.wait()
                with customer_browser_client(spring_url) as terminal_client:
                    return terminal_client.post(
                        f"{spring_url}/internal/compensation-executions/"
                        f"{coupon_execution_id}/success",
                        headers={
                            **executor_headers,
                            "Idempotency-Key": f"coupon-terminal-{uuid.uuid4()}",
                        },
                        json={
                            "attemptId": attempt_id,
                            "idempotencyKey": coupon_claim_payload["idempotencyKey"],
                            "parameterDigest": coupon_claim_payload["parameterDigest"],
                        },
                    )

            with ThreadPoolExecutor(max_workers=2) as terminal_executor:
                terminal_success_replay, terminal_attempt_conflict = terminal_executor.map(
                    redeliver_terminal_success,
                    [coupon_claim_payload["attemptId"], str(uuid.uuid4())],
                )
            expect_status(terminal_success_replay, 200)
            expect_status(terminal_attempt_conflict, 409)
            assert terminal_success_replay.json() == {**coupon_success.json(), "replayed": True}
            assert_success_sla_projection(ticket)
            customer = client.get(
                f"{spring_url}/api/customer/tickets/{ticket}",
            )
            expect_status(customer, 200)
            assert customer.json()["ticket"]["lifecycleState"] == "RESOLVED"
            assert customer.json()["messages"][-1]["body"] == expected_message
        return coupon_execution_id, str(ticket)

    coupon_10_execution_id, coupon_10_ticket_id = approve_and_execute_coupon(
        "ORDER-DELAY-EXECUTION-10", 24, 86400, Decimal("10.00")
    )
    coupon_20_execution_id, coupon_20_ticket_id = approve_and_execute_coupon(
        "ORDER-DELAY-EXECUTION-20", 48, 172800, Decimal("20.00")
    )
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select amount from simulated_coupon where execution_id in (%s, %s) order by amount",
            (uuid.UUID(coupon_10_execution_id), uuid.UUID(coupon_20_execution_id)),
        ).fetchall() == [(Decimal("10.00"),), (Decimal("20.00"),)]

    auto_digest = uuid.uuid4().hex * 2
    auto_ticket_id, _, auto_revision_id = seed_pending_decision_fixture(
        "ORDER-DELAY-EXECUTOR-AUTO",
        auto_digest,
        "常驻执行器自动消费验收",
        24,
        86400,
        "COUPON",
        Decimal("10.00"),
    )
    with customer_browser_client(spring_url) as client:
        auto_lease_response = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{auto_revision_id}/claims",
            headers={**approver_headers, "Idempotency-Key": f"auto-claim-{uuid.uuid4()}"},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(auto_lease_response, 201)
        auto_lease = auto_lease_response.json()
        auto_approval = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{auto_revision_id}/approve",
            headers={
                **approver_headers,
                "X-Approval-Lease-Token": auto_lease["leaseToken"],
                "X-Approval-Lease-Version": str(auto_lease["leaseVersion"]),
                "Idempotency-Key": f"auto-approve-{uuid.uuid4()}",
            },
            json={"proposalRevision": 1, "contentDigest": auto_digest},
        )
        expect_status(auto_approval, 200)
        auto_execution_id = auto_approval.json()["executionId"]
        assert auto_approval.json()["executionStatus"] == "READY"

    drift_digest = "8" * 64
    drift_ticket_id, _, drift_revision_id = seed_pending_decision_fixture(
        "ORDER-DELAY-APPROVAL-DRIFT", drift_digest, "审批事实漂移验收"
    )
    with customer_browser_client(spring_url) as client:
        drift_claim = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{drift_revision_id}/claims",
            headers={**approver_headers, "Idempotency-Key": f"drift-claim-{uuid.uuid4()}"},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(drift_claim, 201)
        drift_lease = drift_claim.json()

    def approve_while_order_writer_holds_lock() -> httpx.Response:
        with customer_browser_client(spring_url) as concurrent_client:
            return concurrent_client.post(
                f"{spring_url}/api/approver/compensation-proposals/{drift_revision_id}/approve",
                headers={
                    **approver_headers,
                    "X-Approval-Lease-Token": drift_lease["leaseToken"],
                    "X-Approval-Lease-Version": str(drift_lease["leaseVersion"]),
                    "Idempotency-Key": f"drift-approve-{uuid.uuid4()}",
                },
                json={"proposalRevision": 1, "contentDigest": drift_digest},
            )

    with psycopg.connect(os.environ["SPRING_FIXTURE_DATABASE_URI"]) as connection:
        connection.execute(
            "update synthetic_order set delay_hours = 81, delay_seconds = 291600 "
            "where order_reference = 'ORDER-DELAY-APPROVAL-DRIFT'"
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            drift_future = executor.submit(approve_while_order_writer_holds_lock)
            time.sleep(0.25)
            assert not drift_future.done(), (
                "approval did not wait for the authoritative order writer"
            )
            connection.commit()
            drift_approval = drift_future.result()
    expect_status(drift_approval, 409)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select p.status, l.status from compensation_proposal_revision p "
            "join approval_lease l on l.proposal_revision_id = p.id where p.id = %s",
            (drift_revision_id,),
        ).fetchone() == ("SUPERSEDED", "REVOKED")
        assert (
            connection.execute(
                "select count(*) from proposal_decision where proposal_revision_id = %s",
                (drift_revision_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "select count(*) from compensation_execution where proposal_revision_id = %s",
                (drift_revision_id,),
            ).fetchone()[0]
            == 0
        )

    proposal_race_scopes = []
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        for index in range(2):
            candidate_ticket_id = uuid.uuid4()
            candidate_generation_id = uuid.uuid4()
            candidate_revision_id = uuid.uuid4()
            connection.execute(
                "insert into support_ticket "
                "(id, customer_id, order_reference, description, lifecycle_state, handling_mode, "
                "created_at, first_responded_at) values "
                "(%s, 'customer-demo', 'ORDER-DELAY-PROPOSAL-RACE', %s, "
                "'INVESTIGATING', 'AGENT', '2026-08-09T13:55:00Z', '2026-08-09T13:56:00Z')",
                (candidate_ticket_id, f"并发提案 {index}"),
            )
            connection.execute(
                "insert into agent_processing_generation "
                "(id, ticket_id, generation_number, thread_id, status, created_at) "
                "values (%s, %s, 1, %s, 'COMPLETED', '2026-08-09T13:56:00Z')",
                (candidate_generation_id, candidate_ticket_id, uuid.uuid4()),
            )
            proposal_race_scopes.append(
                (candidate_ticket_id, candidate_generation_id, candidate_revision_id)
            )
    proposal_barrier = threading.Barrier(2)

    def create_competing_proposal(scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID]) -> str:
        candidate_ticket_id, candidate_generation_id, candidate_revision_id = scope
        try:
            with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
                proposal_barrier.wait()
                connection.execute(
                    "insert into compensation_proposal_revision "
                    "(id, proposal_id, revision_number, ticket_id, order_reference, generation_id, "
                    "delay_hours, delay_seconds, compensation_method, amount, reason_code, "
                    "evidence_references, policy_version, content_digest, status, created_at, expires_at) "
                    "values (%s, %s, 1, %s, 'ORDER-DELAY-PROPOSAL-RACE', %s, 80, 288000, "
                    "'SIMULATED_PARTIAL_REFUND', 26.80, 'LOGISTICS_DELAY', "
                    '\'["order:ORDER-DELAY-PROPOSAL-RACE","logistics:ORDER-DELAY-PROPOSAL-RACE"]\', '
                    "'delay-policy-v1', %s, 'PENDING_APPROVAL', "
                    "'2026-08-09T13:57:00Z', '2026-08-10T13:57:00Z')",
                    (
                        candidate_revision_id,
                        uuid.uuid4(),
                        candidate_ticket_id,
                        candidate_generation_id,
                        candidate_revision_id.hex * 2,
                    ),
                )
            return "accepted"
        except psycopg.errors.UniqueViolation as error:
            constraint_name = error.diag.constraint_name
            assert constraint_name is not None
            return constraint_name

    with ThreadPoolExecutor(max_workers=2) as executor:
        proposal_race_results = list(executor.map(create_competing_proposal, proposal_race_scopes))
    assert sorted(proposal_race_results) == ["accepted", "one_active_logistics_compensation_intent"]

    race_digest = "7" * 64
    _, _, race_revision_id = seed_pending_decision_fixture(
        "ORDER-DELAY-APPROVAL-RACE", race_digest, "批准驳回竞争验收"
    )
    with customer_browser_client(spring_url) as client:
        race_claim = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{race_revision_id}/claims",
            headers={**approver_headers, "Idempotency-Key": f"race-claim-{uuid.uuid4()}"},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(race_claim, 201)
    race_lease = race_claim.json()
    race_headers = {
        **approver_headers,
        "X-Approval-Lease-Token": race_lease["leaseToken"],
        "X-Approval-Lease-Version": str(race_lease["leaseVersion"]),
    }
    decision_barrier = threading.Barrier(2)

    def submit_racing_decision(decision: str) -> httpx.Response:
        decision_barrier.wait()
        with customer_browser_client(spring_url) as concurrent_client:
            return concurrent_client.post(
                f"{spring_url}/api/approver/compensation-proposals/{race_revision_id}/{decision}",
                headers={**race_headers, "Idempotency-Key": f"race-{decision}-{uuid.uuid4()}"},
                json={
                    "proposalRevision": 1,
                    "contentDigest": race_digest,
                    **({"internalReason": "并发驳回"} if decision == "reject" else {}),
                },
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        race_responses = list(executor.map(submit_racing_decision, ["approve", "reject"]))
    assert sorted(response.status_code for response in race_responses) == [200, 409], [
        (response.status_code, response.text) for response in race_responses
    ]
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        race_decision = connection.execute(
            "select decision_type from proposal_decision where proposal_revision_id = %s",
            (race_revision_id,),
        ).fetchone()[0]
        assert race_decision in ("APPROVED", "REJECTED")
        assert (
            connection.execute(
                "select count(*) from proposal_decision where proposal_revision_id = %s",
                (race_revision_id,),
            ).fetchone()[0]
            == 1
        )
        assert connection.execute(
            "select count(*) from compensation_execution where proposal_revision_id = %s",
            (race_revision_id,),
        ).fetchone()[0] == (1 if race_decision == "APPROVED" else 0)

    rejection_digest = "a" * 64
    rejection_ticket_id, _rejection_generation_id, rejection_revision_id = (
        seed_pending_decision_fixture("ORDER-DELAY-CANCELLED", rejection_digest, "审批驳回验收")
    )

    with customer_browser_client(spring_url) as client:
        rejection_claim = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{rejection_revision_id}/claims",
            headers={**approver_headers, "Idempotency-Key": f"reject-claim-{uuid.uuid4()}"},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(rejection_claim, 201)
        rejection_lease = rejection_claim.json()
        rejection_headers = {
            **approver_headers,
            "X-Approval-Lease-Token": rejection_lease["leaseToken"],
            "X-Approval-Lease-Version": str(rejection_lease["leaseVersion"]),
        }
        rejection_url = (
            f"{spring_url}/api/approver/compensation-proposals/{rejection_revision_id}/reject"
        )
        old_revision = client.post(
            rejection_url,
            headers={**rejection_headers, "Idempotency-Key": f"old-revision-{uuid.uuid4()}"},
            json={
                "proposalRevision": 2,
                "contentDigest": rejection_digest,
                "internalReason": "旧版本页面",
            },
        )
        expect_status(old_revision, 409)
        wrong_digest = client.post(
            rejection_url,
            headers={**rejection_headers, "Idempotency-Key": f"wrong-digest-{uuid.uuid4()}"},
            json={
                "proposalRevision": 1,
                "contentDigest": "b" * 64,
                "internalReason": "摘要不匹配",
            },
        )
        expect_status(wrong_digest, 409)
        empty_reason = client.post(
            rejection_url,
            headers={**rejection_headers, "Idempotency-Key": f"empty-reason-{uuid.uuid4()}"},
            json={
                "proposalRevision": 1,
                "contentDigest": rejection_digest,
                "internalReason": "   ",
            },
        )
        expect_status(empty_reason, 400)

        rejection_view_before_decision = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{rejection_revision_id}/approval-view",
            headers=rejection_headers,
        )
        expect_status(rejection_view_before_decision, 200)
        rejection_stream_executor, rejection_stream_closed = start_authorized_sse(
            f"{spring_url}/api/approver/compensation-proposals/{rejection_revision_id}/approval-view/events",
            rejection_headers,
            rejection_view_before_decision.json()["cursor"],
        )

        rejection_body = {
            "proposalRevision": 1,
            "contentDigest": rejection_digest,
            "internalReason": "审批证据不足，需要客服继续核实",
        }
        rejection_request_id = f"reject-decision-{uuid.uuid4()}"
        rejection_request_ids = [rejection_request_id, rejection_request_id]

        def reject_concurrently(request_id: str) -> httpx.Response:
            with customer_browser_client(spring_url) as concurrent_client:
                return concurrent_client.post(
                    rejection_url,
                    headers={**rejection_headers, "Idempotency-Key": request_id},
                    json=rejection_body,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            rejection_responses = list(executor.map(reject_concurrently, rejection_request_ids))
        assert sorted(response.status_code for response in rejection_responses) == [200, 200], [
            (response.status_code, response.text) for response in rejection_responses
        ]
        assert sorted(response.json()["replayed"] for response in rejection_responses) == [
            False,
            True,
        ]
        try:
            assert rejection_stream_closed.result(timeout=5) is True
        finally:
            rejection_stream_executor.shutdown(wait=False, cancel_futures=True)
        rejection_winner_index = next(
            index
            for index, response in enumerate(rejection_responses)
            if response.json()["replayed"] is False
        )
        rejected = rejection_responses[rejection_winner_index]
        assert rejected.json() == {
            "proposalRevisionId": str(rejection_revision_id),
            "proposalRevision": 1,
            "decision": "REJECTED",
            "replayed": False,
        }
        rejection_replay = client.post(
            rejection_url,
            headers={**rejection_headers, "Idempotency-Key": rejection_request_id},
            json=rejection_body,
        )
        expect_status(rejection_replay, 200)
        assert rejection_replay.json()["replayed"] is True
        rejection_conflict = client.post(
            rejection_url,
            headers={**rejection_headers, "Idempotency-Key": rejection_request_id},
            json={**rejection_body, "internalReason": "不同理由"},
        )
        expect_status(rejection_conflict, 409)
        cross_decision_conflict = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{rejection_revision_id}/approve",
            headers={**rejection_headers, "Idempotency-Key": rejection_request_id},
            json={"proposalRevision": 1, "contentDigest": rejection_digest},
        )
        expect_status(cross_decision_conflict, 409)
        stale_page_reject = client.post(
            rejection_url,
            headers={**rejection_headers, "Idempotency-Key": f"stale-page-{uuid.uuid4()}"},
            json=rejection_body,
        )
        expect_status(stale_page_reject, 409)
        rejected_view = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{rejection_revision_id}/approval-view",
            headers=rejection_headers,
        )
        expect_status(rejected_view, 409)
        rejection_customer = client.get(
            f"{spring_url}/api/customer/tickets/{rejection_ticket_id}",
        )
        expect_status(rejection_customer, 200)
        rejection_projection = rejection_customer.json()
        assert rejection_projection["ticket"]["handlingMode"] == "HUMAN"
        assert rejection_projection["ticket"]["lifecycleState"] == "INVESTIGATING"
        assert rejection_projection["messages"][-1]["body"] == (
            "为继续妥善处理，此工单已转由客服跟进。客服将在此工单中与您联系。"
        )
        rejection_public_json = json.dumps(rejection_projection, ensure_ascii=False)
        assert rejection_body["internalReason"] not in rejection_public_json
        assert "APPROVAL_REJECTED" not in rejection_public_json
        rejection_queue = client.get(
            f"{spring_url}/api/support/queue",
        )
        expect_status(rejection_queue, 200)
        rejection_queue_item = next(
            item for item in rejection_queue.json() if item["ticketId"] == str(rejection_ticket_id)
        )
        assert rejection_queue_item["reasonCodes"] == ["APPROVAL_REJECTED_HANDOFF"]
        assert "internalReason" not in rejection_queue_item

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        rejection_record = connection.execute(
            "select d.id, d.decision_type, d.internal_reason, p.status, l.status, "
            "t.handling_mode, t.human_handoff_reason_code, g.status "
            "from proposal_decision d "
            "join compensation_proposal_revision p on p.id = d.proposal_revision_id "
            "join approval_lease l on l.proposal_revision_id = d.proposal_revision_id "
            "and l.lease_version = d.lease_version "
            "join support_ticket t on t.id = p.ticket_id "
            "join agent_processing_generation g on g.id = p.generation_id "
            "where d.proposal_revision_id = %s",
            (rejection_revision_id,),
        ).fetchone()
        assert rejection_record[1:] == (
            "REJECTED",
            rejection_body["internalReason"],
            "REJECTED",
            "DECIDED",
            "HUMAN",
            "APPROVAL_REJECTED",
            "HANDED_OFF",
        )
        assert (
            connection.execute(
                "select count(*) from compensation_reservation where order_reference = 'ORDER-DELAY-CANCELLED'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "select count(*) from audit_event where subject_type = 'PROPOSAL_DECISION' "
                "and subject_id = %s and event_type = 'COMPENSATION_PROPOSAL_REJECTED'",
                (rejection_record[0],),
            ).fetchone()[0]
            == 1
        )

    boundary_digest = "c" * 64
    boundary_ticket_id, _, boundary_revision_id = seed_pending_decision_fixture(
        "ORDER-DELAY-REFUNDED", boundary_digest, "审批租约到期边界验收"
    )
    boundary_token = uuid.uuid4()
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "insert into approval_lease "
            "(id, proposal_revision_id, approver_id, lease_token, lease_version, status, "
            "claimed_at, expires_at) values "
            "(%s, %s, 'approver-demo', %s, 1, 'ACTIVE', "
            "'2026-08-09T13:59:59Z', '2026-08-09T14:00:00Z')",
            (uuid.uuid4(), boundary_revision_id, boundary_token),
        )
    with customer_browser_client(spring_url) as client:
        boundary_rejection = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{boundary_revision_id}/reject",
            headers={
                **approver_headers,
                "X-Approval-Lease-Token": str(boundary_token),
                "X-Approval-Lease-Version": "1",
                "Idempotency-Key": f"boundary-reject-{uuid.uuid4()}",
            },
            json={
                "proposalRevision": 1,
                "contentDigest": boundary_digest,
                "internalReason": "租约恰在服务器时间到期",
            },
        )
        expect_status(boundary_rejection, 409)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert (
            connection.execute(
                "select status from approval_lease where proposal_revision_id = %s and lease_version = 1",
                (boundary_revision_id,),
            ).fetchone()[0]
            == "EXPIRED"
        )
        assert (
            connection.execute(
                "select count(*) from proposal_decision where proposal_revision_id = %s",
                (boundary_revision_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "select handling_mode from support_ticket where id = %s", (boundary_ticket_id,)
            ).fetchone()[0]
            == "AGENT"
        )

    reservation_barrier = threading.Barrier(2)

    def reserve_concurrently() -> str:
        try:
            with psycopg.connect(os.environ["SPRING_FIXTURE_DATABASE_URI"]) as connection:
                reservation_barrier.wait()
                connection.execute(
                    "insert into compensation_reservation "
                    "(id, order_reference, amount, status, created_at) "
                    "values (%s, 'ORDER-DELAY-CONCURRENT-RESERVATION', 20.00, 'ACTIVE', now())",
                    (uuid.uuid4(),),
                )
            return "accepted"
        except psycopg.errors.CheckViolation as error:
            constraint_name = error.diag.constraint_name
            assert constraint_name is not None
            return constraint_name

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservation_results = list(executor.map(lambda _: reserve_concurrently(), range(2)))
    assert sorted(reservation_results) == ["accepted", "compensation_reservation_capacity"]

    rejection_cases = {
        "ORDER-DELAY-CANCELLED": "UNSUPPORTED_SCENARIO",
        "ORDER-DELAY-UNPAID": "UNSUPPORTED_SCENARIO",
        "ORDER-DELAY-REFUNDED": "UNSUPPORTED_SCENARIO",
        "ORDER-DELAY-COMPENSATED": "UNSUPPORTED_SCENARIO",
        "ORDER-DELAY-LOW-ALLOWANCE": "FACT_CONFLICT",
        "ORDER-DELAY-RESERVED": "FACT_CONFLICT",
    }
    rejected_ticket_ids = []
    with customer_browser_client(spring_url) as client:
        for order_reference, expected_reason in rejection_cases.items():
            response = client.post(
                f"{spring_url}/api/customer/tickets",
                headers={
                    "Idempotency-Key": f"reject-{uuid.uuid4()}",
                },
                json={"orderReference": order_reference, "description": "不合法补偿提案验收"},
            )
            expect_status(response, 201)
            rejected_id = uuid.UUID(response.json()["ticketId"])
            rejected_ticket_ids.append(rejected_id)
            observed = False
            proposal_count = 0
            for _ in range(40):
                with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
                    observed = connection.execute(
                        "select exists(select 1 from agent_human_handoff_request "
                        "where ticket_id = %s and reason_code = %s)",
                        (rejected_id, expected_reason),
                    ).fetchone()[0]
                    proposal_count = connection.execute(
                        "select count(*) from compensation_proposal_revision where ticket_id = %s",
                        (rejected_id,),
                    ).fetchone()[0]
                if observed:
                    break
                time.sleep(0.25)
            assert observed and proposal_count == 0, (order_reference, expected_reason)

    def create_ambiguous_ticket(label: str) -> tuple[str, dict]:
        with customer_browser_client(spring_url) as client:
            response = client.post(
                f"{spring_url}/api/customer/tickets",
                headers={
                    "Idempotency-Key": f"clarification-{label}-{uuid.uuid4()}",
                },
                json={
                    "orderReference": "ORDER-DELAY-AMBIGUOUS",
                    "description": f"需要确认订单 {label}",
                },
            )
            expect_status(response, 201)
            created_id = response.json()["ticketId"]
            for _ in range(80):
                projection_response = client.get(
                    f"{spring_url}/api/customer/tickets/{created_id}",
                )
                expect_status(projection_response, 200)
                projection = projection_response.json()
                if (
                    projection["ticket"]["lifecycleState"] == "WAITING_FOR_CUSTOMER"
                    and projection["clarification"]
                ):
                    return created_id, projection
                time.sleep(0.25)
        raise AssertionError("clarification request was not published")

    clarification_ticket_id, clarification_projection = create_ambiguous_ticket("primary")
    clarification_request_id = clarification_projection["clarification"]["id"]
    assert clarification_projection["clarification"]["promptCode"] == "ORDER_CONFIRMATION_CODE"
    serialized_clarification = json.dumps(clarification_projection)
    assert not any(field in serialized_clarification for field in forbidden_fields)
    resume_request_id = str(uuid.uuid4())
    reply_message_id = f"message-{uuid.uuid4()}"
    reply_url = (
        f"{spring_url}/api/customer/tickets/{clarification_ticket_id}/clarifications/"
        f"{clarification_request_id}/replies"
    )
    with customer_browser_client(spring_url) as client:
        invalid = client.post(
            reply_url,
            headers={
                "Idempotency-Key": f"invalid-{uuid.uuid4()}",
                "X-Resume-Request-Id": str(uuid.uuid4()),
            },
            json={"answer": "unrelated input"},
        )
        expect_status(invalid, 422)
        accepted_reply = client.post(
            reply_url,
            headers={
                "Idempotency-Key": reply_message_id,
                "X-Resume-Request-Id": resume_request_id,
            },
            json={"answer": "A"},
        )
        expect_status(accepted_reply, 202)
        duplicate_reply = client.post(
            reply_url,
            headers={
                "Idempotency-Key": reply_message_id,
                "X-Resume-Request-Id": resume_request_id,
            },
            json={"answer": "A"},
        )
        expect_status(duplicate_reply, 200)
        assert duplicate_reply.json()["replayed"] is True
        conflicting_reuse = client.post(
            reply_url,
            headers={
                "Idempotency-Key": reply_message_id,
                "X-Resume-Request-Id": resume_request_id,
            },
            json={"answer": "B"},
        )
        expect_status(conflicting_reuse, 409)
        stale_reply = client.post(
            reply_url,
            headers={
                "Idempotency-Key": f"stale-{uuid.uuid4()}",
                "X-Resume-Request-Id": str(uuid.uuid4()),
            },
            json={"answer": "A"},
        )
        expect_status(stale_reply, 409)

        resume_status = None
        for _ in range(80):
            queried = client.get(
                f"{spring_url}/api/customer/tickets/{clarification_ticket_id}/clarification-resumes/{resume_request_id}",
            )
            expect_status(queried, 200)
            resume_status = queried.json()["status"]
            if resume_status in {"SUBMITTED", "COMPLETED"}:
                break
            time.sleep(0.25)
        assert resume_status in {"SUBMITTED", "COMPLETED"}

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        clarification_generation = connection.execute(
            "select g.id, g.thread_id, t.resolution_elapsed_seconds, t.resolution_running_since "
            "from agent_processing_generation g join support_ticket t on t.id = g.ticket_id "
            "where g.ticket_id = %s",
            (uuid.UUID(clarification_ticket_id),),
        ).fetchone()
        assert clarification_generation is not None
        assert clarification_generation[2] >= 0 and clarification_generation[3] is not None
        assert (
            connection.execute(
                "select count(*) from agent_resume_request where generation_id = %s",
                (clarification_generation[0],),
            ).fetchone()[0]
            == 1
        )

    with customer_browser_client(spring_url) as client:
        runs = client.get(
            f"{agent_url}/threads/{clarification_generation[1]}/runs?limit=100",
            headers=spring_headers,
        )
        expect_status(runs, 200)
        run_metadata = [run.get("metadata", {}) for run in runs.json()]
        assert sum("submission_request_id" in metadata for metadata in run_metadata) == 1
        assert (
            sum(metadata.get("resume_request_id") == resume_request_id for metadata in run_metadata)
            == 1
        )

    concurrent_ticket_id, concurrent_projection = create_ambiguous_ticket("concurrent")
    concurrent_request_id = concurrent_projection["clarification"]["id"]
    reply_barrier = threading.Barrier(2)

    def reply_concurrently(answer: str) -> int:
        reply_barrier.wait()
        with customer_browser_client(spring_url) as client:
            response = client.post(
                f"{spring_url}/api/customer/tickets/{concurrent_ticket_id}/clarifications/{concurrent_request_id}/replies",
                headers={
                    "Idempotency-Key": f"concurrent-message-{uuid.uuid4()}",
                    "X-Resume-Request-Id": str(uuid.uuid4()),
                },
                json={"answer": answer},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent_reply_statuses = list(executor.map(reply_concurrently, ["A", "B"]))
    assert sorted(concurrent_reply_statuses) == [202, 409]

    handoff_ticket_id, handoff_projection = create_ambiguous_ticket("human-handoff")
    handoff_clarification_id = handoff_projection["clarification"]["id"]
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        handoff_generation_row = connection.execute(
            "select g.id, c.request_key from agent_processing_generation g "
            "join customer_clarification_request c on c.generation_id = g.id "
            "where g.ticket_id = %s and g.status = 'ACTIVE'",
            (uuid.UUID(handoff_ticket_id),),
        ).fetchone()
        assert handoff_generation_row is not None
        handoff_generation_id, handoff_clarification_request_key = handoff_generation_row
        lifecycle_before_handoff = connection.execute(
            "select lifecycle_state from support_ticket where id = %s",
            (uuid.UUID(handoff_ticket_id),),
        ).fetchone()[0]

    handoff_request_id = f"handoff-{uuid.uuid4()}"
    handoff_url = f"{spring_url}/api/customer/tickets/{handoff_ticket_id}/human-handoff"
    handoff_headers = {
        "Idempotency-Key": handoff_request_id,
    }
    with customer_browser_client(spring_url) as client:
        handoff = client.post(
            handoff_url,
            headers=handoff_headers,
            json={"reasonCode": "CUSTOMER_REQUESTED"},
        )
        expect_status(handoff, 202)
        assert handoff.json() == {
            "requestId": handoff_request_id,
            "handlingMode": "HUMAN",
            "replayed": False,
        }
        duplicate_handoff = client.post(
            handoff_url,
            headers=handoff_headers,
            json={"reasonCode": "CUSTOMER_REQUESTED"},
        )
        expect_status(duplicate_handoff, 200)
        assert duplicate_handoff.json()["replayed"] is True
        conflicting_handoff = client.post(
            handoff_url,
            headers=handoff_headers,
            json={"reasonCode": "DIFFERENT_REASON"},
        )
        expect_status(conflicting_handoff, 409)
        handoff_status = client.get(
            f"{spring_url}/api/customer/tickets/{handoff_ticket_id}/human-handoff-requests/{handoff_request_id}",
        )
        expect_status(handoff_status, 200)
        restored_handoff = client.get(
            f"{spring_url}/api/customer/tickets/{handoff_ticket_id}",
        )
        expect_status(restored_handoff, 200)
        handoff_public = restored_handoff.json()
        assert handoff_public["ticket"]["handlingMode"] == "HUMAN"
        assert handoff_public["ticket"]["lifecycleState"] == lifecycle_before_handoff
        assert handoff_public["clarification"] is None
        assert handoff_public["messages"][-1]["body"] == (
            "已按您的要求转由客服继续处理。客服将在此工单中与您联系。"
        )
        assert "CUSTOMER_REQUESTED" not in json.dumps(handoff_public)

        stale_reply_after_handoff = client.post(
            f"{spring_url}/api/customer/tickets/{handoff_ticket_id}/clarifications/"
            f"{handoff_clarification_id}/replies",
            headers={
                "Idempotency-Key": f"late-reply-{uuid.uuid4()}",
                "X-Resume-Request-Id": str(uuid.uuid4()),
            },
            json={"answer": "A"},
        )
        expect_status(stale_reply_after_handoff, 409)
        agent_capability_headers = {
            "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
            "X-Agent-Generation-Id": str(handoff_generation_id),
            "X-Agent-Operation": "READ_INVESTIGATION_FACTS",
        }
        late_facts = client.get(
            f"{spring_url}/internal/agent/tickets/{handoff_ticket_id}/generations/"
            f"{handoff_generation_id}/facts",
            headers=agent_capability_headers,
        )
        expect_status(late_facts, 403)
        late_clarification = client.post(
            f"{spring_url}/internal/agent/tickets/{handoff_ticket_id}/generations/"
            f"{handoff_generation_id}/clarifications",
            headers={
                "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
                "X-Agent-Generation-Id": str(handoff_generation_id),
                "X-Agent-Operation": "CREATE_CUSTOMER_CLARIFICATION",
                "Idempotency-Key": f"late-clarification-{uuid.uuid4()}",
            },
            json={"reasonCode": "ORDER_AMBIGUOUS"},
        )
        expect_status(late_clarification, 403)
        replayed_clarification_after_handoff = client.post(
            f"{spring_url}/internal/agent/tickets/{handoff_ticket_id}/generations/"
            f"{handoff_generation_id}/clarifications",
            headers={
                "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
                "X-Agent-Generation-Id": str(handoff_generation_id),
                "X-Agent-Operation": "CREATE_CUSTOMER_CLARIFICATION",
                "Idempotency-Key": handoff_clarification_request_key,
            },
            json={"reasonCode": "ORDER_AMBIGUOUS"},
        )
        expect_status(replayed_clarification_after_handoff, 403)
        late_conclusion = client.post(
            f"{spring_url}/internal/agent/tickets/{handoff_ticket_id}/generations/"
            f"{handoff_generation_id}/conclusions",
            headers={
                "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
                "X-Agent-Generation-Id": str(handoff_generation_id),
                "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                "Idempotency-Key": f"late-conclusion-{uuid.uuid4()}",
            },
            json={
                "compensationRequired": False,
                "reasonCode": "DELAY_UNDER_24_HOURS",
                "delayHours": 23,
                "delaySeconds": 82800,
                "orderReference": "ORDER-DELAY-AMBIGUOUS-A",
                "evidenceRefs": [
                    "order:ORDER-DELAY-AMBIGUOUS-A",
                    "logistics:ORDER-DELAY-AMBIGUOUS-A",
                ],
            },
        )
        expect_status(late_conclusion, 403)

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        handoff_state = connection.execute(
            "select lifecycle_state, handling_mode, customer_human_preference, human_handoff_reason_code "
            "from support_ticket where id = %s",
            (uuid.UUID(handoff_ticket_id),),
        ).fetchone()
        assert handoff_state == (lifecycle_before_handoff, "HUMAN", True, "CUSTOMER_REQUESTED")
        assert (
            connection.execute(
                "select status from agent_processing_generation where id = %s",
                (handoff_generation_id,),
            ).fetchone()[0]
            == "HANDED_OFF"
        )
        assert (
            connection.execute(
                "select status from customer_clarification_request where id = %s",
                (uuid.UUID(handoff_clarification_id),),
            ).fetchone()[0]
            == "INVALIDATED"
        )
        assert (
            connection.execute(
                "select count(*) from customer_human_handoff_request where ticket_id = %s",
                (uuid.UUID(handoff_ticket_id),),
            ).fetchone()[0]
            == 1
        )
        handoff_summary = connection.execute(
            "select investigation_summary from customer_human_handoff_request where ticket_id = %s",
            (uuid.UUID(handoff_ticket_id),),
        ).fetchone()[0]
        assert handoff_summary["generationId"] == str(handoff_generation_id)
        assert isinstance(handoff_summary["facts"], list)
        assert (
            connection.execute(
                "select count(*) from audit_event where ticket_id = %s and event_type in ("
                "'CUSTOMER_HUMAN_HANDOFF_REQUEST_RECORDED', 'CUSTOMER_HUMAN_PREFERENCE_RECORDED', "
                "'AGENT_GENERATION_HANDED_OFF', 'SHARED_SUPPORT_QUEUE_ENTERED')",
                (uuid.UUID(handoff_ticket_id),),
            ).fetchone()[0]
            == 4
        )
        assert (
            connection.execute(
                "select count(*) from audit_event where ticket_id = %s and ("
                "event_type = 'AGENT_COMMAND_REJECTED_STALE_OR_OUT_OF_SCOPE_GENERATION' or "
                "event_type = 'CLARIFICATION_REJECTED_STALE_CLARIFICATION_GENERATION')",
                (uuid.UUID(handoff_ticket_id),),
            ).fetchone()[0]
            >= 4
        )
        assert connection.execute(
            "select count(*) from public_message where ticket_id = %s",
            (uuid.UUID(handoff_ticket_id),),
        ).fetchone()[0] == len(handoff_public["messages"])

    agent_handoff_ticket_id, _ = create_ambiguous_ticket("agent-human-handoff")
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        agent_handoff_generation_id = connection.execute(
            "select id from agent_processing_generation where ticket_id = %s and status = 'ACTIVE'",
            (uuid.UUID(agent_handoff_ticket_id),),
        ).fetchone()[0]
        agent_handoff_lifecycle = connection.execute(
            "select lifecycle_state from support_ticket where id = %s",
            (uuid.UUID(agent_handoff_ticket_id),),
        ).fetchone()[0]
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "insert into investigation_fact "
            "(generation_id, fact_type, fact_value, evidence_reference, recorded_at) values "
            "(%s, 'ORDER', 'ORDER-DELAY-AMBIGUOUS-A', 'order:ORDER-DELAY-AMBIGUOUS-A', now()), "
            "(%s, 'LOGISTICS_DELAY_SECONDS', '288000', 'logistics:ORDER-DELAY-AMBIGUOUS-A', now())",
            (agent_handoff_generation_id, agent_handoff_generation_id),
        )
    agent_handoff_request_id = f"{agent_handoff_generation_id}:human-handoff:FACT_CONFLICT"
    agent_handoff_url = (
        f"{spring_url}/internal/agent/tickets/{agent_handoff_ticket_id}/generations/"
        f"{agent_handoff_generation_id}/human-handoff"
    )
    agent_handoff_headers = {
        "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
        "X-Agent-Generation-Id": str(agent_handoff_generation_id),
        "X-Agent-Operation": "REQUEST_HUMAN_HANDOFF",
        "Idempotency-Key": agent_handoff_request_id,
    }
    agent_handoff_body = {
        "reasonCode": "FACT_CONFLICT",
        "summary": {
            "conclusionCode": "INVESTIGATION_COULD_NOT_CONTINUE",
            "facts": [
                {
                    "type": "ORDER",
                    "value": "ORDER-DELAY-AMBIGUOUS-A",
                    "evidenceReference": "order:ORDER-DELAY-AMBIGUOUS-A",
                },
                {
                    "type": "LOGISTICS_DELAY_SECONDS",
                    "value": "288000",
                    "evidenceReference": "logistics:ORDER-DELAY-AMBIGUOUS-A",
                },
            ],
        },
    }
    with customer_browser_client(spring_url) as client:
        forged_summary = client.post(
            agent_handoff_url,
            headers={**agent_handoff_headers, "Idempotency-Key": f"forged-{uuid.uuid4()}"},
            json={
                **agent_handoff_body,
                "summary": {
                    "conclusionCode": "INVESTIGATION_COULD_NOT_CONTINUE",
                    "facts": [
                        {
                            "type": "ORDER",
                            "value": "raw payload fragment",
                            "evidenceReference": "order:forged",
                        }
                    ],
                },
            },
        )
        expect_status(forged_summary, 422)
        agent_handoff = client.post(
            agent_handoff_url, headers=agent_handoff_headers, json=agent_handoff_body
        )
        expect_status(agent_handoff, 202)
        assert agent_handoff.json() == {
            "requestId": agent_handoff_request_id,
            "handlingMode": "HUMAN",
            "reasonCode": "FACT_CONFLICT",
            "replayed": False,
        }
        historical_replay = client.post(
            agent_handoff_url, headers=agent_handoff_headers, json=agent_handoff_body
        )
        expect_status(historical_replay, 202)
        assert historical_replay.json()["replayed"] is True
        conflicting_replay = client.post(
            agent_handoff_url,
            headers=agent_handoff_headers,
            json={**agent_handoff_body, "reasonCode": "UNSUPPORTED_SCENARIO"},
        )
        expect_status(conflicting_replay, 409)
        stale_new_handoff = client.post(
            agent_handoff_url,
            headers={
                **agent_handoff_headers,
                "Idempotency-Key": f"late-agent-handoff-{uuid.uuid4()}",
            },
            json=agent_handoff_body,
        )
        expect_status(stale_new_handoff, 403)
        agent_handoff_public_response = client.get(
            f"{spring_url}/api/customer/tickets/{agent_handoff_ticket_id}",
        )
        expect_status(agent_handoff_public_response, 200)
        agent_handoff_public = agent_handoff_public_response.json()
        assert agent_handoff_public["ticket"]["handlingMode"] == "HUMAN"
        assert agent_handoff_public["ticket"]["lifecycleState"] == agent_handoff_lifecycle
        assert agent_handoff_public["messages"][-1]["body"] == (
            "为确保处理安全，此工单已转由客服继续调查。客服将在此工单中与您联系。"
        )
        agent_handoff_public_json = json.dumps(agent_handoff_public)
        assert "FACT_CONFLICT" not in agent_handoff_public_json
        assert "INVESTIGATION_COULD_NOT_CONTINUE" not in agent_handoff_public_json
        agent_handoff_queue_response = client.get(
            f"{spring_url}/api/support/queue",
        )
        expect_status(agent_handoff_queue_response, 200)
        agent_handoff_queue_item = next(
            item
            for item in agent_handoff_queue_response.json()
            if item["ticketId"] == agent_handoff_ticket_id
        )
        assert agent_handoff_queue_item["reasonCodes"] == ["AGENT_HUMAN_HANDOFF"]
        assert "summary" not in agent_handoff_queue_item

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select lifecycle_state, handling_mode, customer_human_preference, human_handoff_reason_code "
            "from support_ticket where id = %s",
            (uuid.UUID(agent_handoff_ticket_id),),
        ).fetchone() == (agent_handoff_lifecycle, "HUMAN", False, "FACT_CONFLICT")
        assert (
            connection.execute(
                "select status from agent_processing_generation where id = %s",
                (agent_handoff_generation_id,),
            ).fetchone()[0]
            == "HANDED_OFF"
        )
        stored_handoff = connection.execute(
            "select reason_code, investigation_summary from agent_human_handoff_request "
            "where generation_id = %s and request_id = %s",
            (agent_handoff_generation_id, agent_handoff_request_id),
        ).fetchone()
        assert stored_handoff is not None
        stored_reason, stored_summary = stored_handoff
        assert stored_reason == "FACT_CONFLICT"
        assert stored_summary == agent_handoff_body["summary"]
        serialized_summary = json.dumps(stored_summary)
        assert "payload" not in serialized_summary and "stack" not in serialized_summary

    concurrent_agent_handoff_ticket_id, _ = create_ambiguous_ticket("concurrent-agent-handoff")
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        concurrent_agent_handoff_generation = connection.execute(
            "select id from agent_processing_generation where ticket_id = %s and status = 'ACTIVE'",
            (uuid.UUID(concurrent_agent_handoff_ticket_id),),
        ).fetchone()[0]
    concurrent_agent_handoff_url = (
        f"{spring_url}/internal/agent/tickets/{concurrent_agent_handoff_ticket_id}/generations/"
        f"{concurrent_agent_handoff_generation}/human-handoff"
    )

    def concurrent_agent_handoff(reason: str) -> int:
        with customer_browser_client(spring_url) as concurrent_client:
            response = concurrent_client.post(
                concurrent_agent_handoff_url,
                headers={
                    "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
                    "X-Agent-Generation-Id": str(concurrent_agent_handoff_generation),
                    "X-Agent-Operation": "REQUEST_HUMAN_HANDOFF",
                    "Idempotency-Key": f"{concurrent_agent_handoff_generation}:human-handoff:{reason}",
                },
                json={
                    "reasonCode": reason,
                    "summary": {
                        "conclusionCode": "INVESTIGATION_COULD_NOT_CONTINUE",
                        "facts": [],
                    },
                },
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent_agent_handoff_statuses = list(
            executor.map(concurrent_agent_handoff, ["FACT_CONFLICT", "UNSUPPORTED_SCENARIO"])
        )
    assert sorted(concurrent_agent_handoff_statuses) == [202, 403]
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert (
            connection.execute(
                "select count(*) from agent_human_handoff_request where ticket_id = %s",
                (uuid.UUID(concurrent_agent_handoff_ticket_id),),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "select count(*) from public_message where ticket_id = %s and body = %s",
                (
                    uuid.UUID(concurrent_agent_handoff_ticket_id),
                    "为确保处理安全，此工单已转由客服继续调查。客服将在此工单中与您联系。",
                ),
            ).fetchone()[0]
            == 1
        )

    resolved_handoff_request_id = f"resolved-handoff-{uuid.uuid4()}"
    with customer_browser_client(spring_url) as client:
        resolved_handoff = client.post(
            f"{spring_url}/api/customer/tickets/{resolved_ticket_id}/human-handoff",
            headers={
                "Idempotency-Key": resolved_handoff_request_id,
            },
            json={"reasonCode": "CUSTOMER_REQUESTED"},
        )
        expect_status(resolved_handoff, 202)
        replayed_conclusion_after_handoff = client.post(
            f"{spring_url}/internal/agent/tickets/{resolved_ticket_id}/generations/{generation_id}/conclusions",
            headers={
                "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
                "X-Agent-Generation-Id": generation_id,
                "X-Agent-Operation": "SUBMIT_INVESTIGATION_CONCLUSION",
                "Idempotency-Key": f"{generation_id}:submit-conclusion",
            },
            json={
                "compensationRequired": False,
                "reasonCode": "DELAY_UNDER_24_HOURS",
                "delayHours": 23,
                "delaySeconds": 82800,
                "orderReference": "ORDER-DELAY-UNDER-24",
                "evidenceRefs": [
                    "order:ORDER-DELAY-UNDER-24",
                    "logistics:ORDER-DELAY-UNDER-24",
                ],
            },
        )
        expect_status(replayed_conclusion_after_handoff, 403)

    race_ticket_id, race_projection = create_ambiguous_ticket("handoff-reply-race")
    race_clarification_id = race_projection["clarification"]["id"]
    race_handoff_id = f"race-handoff-{uuid.uuid4()}"
    race_barrier = threading.Barrier(2)

    def request_handoff_during_reply() -> int:
        race_barrier.wait()
        with customer_browser_client(spring_url) as client:
            response = client.post(
                f"{spring_url}/api/customer/tickets/{race_ticket_id}/human-handoff",
                headers={
                    "Idempotency-Key": race_handoff_id,
                },
                json={"reasonCode": "CUSTOMER_REQUESTED"},
            )
            return response.status_code

    def reply_during_handoff() -> int:
        race_barrier.wait()
        with customer_browser_client(spring_url) as client:
            response = client.post(
                f"{spring_url}/api/customer/tickets/{race_ticket_id}/clarifications/"
                f"{race_clarification_id}/replies",
                headers={
                    "Idempotency-Key": f"race-reply-{uuid.uuid4()}",
                    "X-Resume-Request-Id": str(uuid.uuid4()),
                },
                json={"answer": "A"},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        handoff_future = executor.submit(request_handoff_during_reply)
        reply_future = executor.submit(reply_during_handoff)
        race_statuses = (handoff_future.result(), reply_future.result())
    assert race_statuses[0] == 202
    assert race_statuses[1] in {202, 409}
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select handling_mode, customer_human_preference from support_ticket where id = %s",
            (uuid.UUID(race_ticket_id),),
        ).fetchone() == ("HUMAN", True)
        assert (
            connection.execute(
                "select count(*) from agent_processing_generation where ticket_id = %s and status = 'ACTIVE'",
                (uuid.UUID(race_ticket_id),),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "select count(*) from customer_clarification_request where id = %s and status = 'OPEN'",
                (uuid.UUID(race_clarification_id),),
            ).fetchone()[0]
            == 0
        )

    superseded_ticket_id, superseded_projection = create_ambiguous_ticket("superseded")
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update agent_processing_generation set status = 'SUPERSEDED' where ticket_id = %s and status = 'ACTIVE'",
            (uuid.UUID(superseded_ticket_id),),
        )
    with customer_browser_client(spring_url) as client:
        superseded = client.post(
            f"{spring_url}/api/customer/tickets/{superseded_ticket_id}/clarifications/"
            f"{superseded_projection['clarification']['id']}/replies",
            headers={
                "Idempotency-Key": f"superseded-{uuid.uuid4()}",
                "X-Resume-Request-Id": str(uuid.uuid4()),
            },
            json={"answer": "A"},
        )
        expect_status(superseded, 409)
    replacement_generation_id = uuid.uuid4()
    replacement_thread_id = uuid.uuid4()
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert (
            connection.execute(
                "select status from customer_clarification_request where id = %s",
                (uuid.UUID(superseded_projection["clarification"]["id"]),),
            ).fetchone()[0]
            == "INVALIDATED"
        )
        connection.execute(
            "update support_ticket set lifecycle_state = 'INVESTIGATING' where id = %s",
            (uuid.UUID(superseded_ticket_id),),
        )
        connection.execute(
            "insert into agent_processing_generation "
            "(id, ticket_id, generation_number, thread_id, status, created_at) "
            "values (%s, %s, 2, %s, 'ACTIVE', now())",
            (replacement_generation_id, uuid.UUID(superseded_ticket_id), replacement_thread_id),
        )
    with customer_browser_client(spring_url) as client:
        replacement_request = client.post(
            f"{spring_url}/internal/agent/tickets/{superseded_ticket_id}/generations/"
            f"{replacement_generation_id}/clarifications",
            headers={
                "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
                "X-Agent-Generation-Id": str(replacement_generation_id),
                "X-Agent-Operation": "CREATE_CUSTOMER_CLARIFICATION",
                "Idempotency-Key": f"{replacement_generation_id}:order-disambiguation",
            },
            json={"reasonCode": "ORDER_AMBIGUOUS"},
        )
        expect_status(replacement_request, 200)
        assert (
            replacement_request.json()["clarificationRequestId"]
            != superseded_projection["clarification"]["id"]
        )

    human_ticket_id, human_projection = create_ambiguous_ticket("human-preference")
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update support_ticket set customer_human_preference = true where id = %s",
            (uuid.UUID(human_ticket_id),),
        )
        assert (
            connection.execute(
                "select status from customer_clarification_request where id = %s",
                (uuid.UUID(human_projection["clarification"]["id"]),),
            ).fetchone()[0]
            == "INVALIDATED"
        )
    with customer_browser_client(spring_url) as client:
        human_preference = client.post(
            f"{spring_url}/api/customer/tickets/{human_ticket_id}/clarifications/"
            f"{human_projection['clarification']['id']}/replies",
            headers={
                "Idempotency-Key": f"human-pref-{uuid.uuid4()}",
                "X-Resume-Request-Id": str(uuid.uuid4()),
            },
            json={"answer": "A"},
        )
        expect_status(human_preference, 409)

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update support_ticket set customer_human_preference = false, handling_mode = 'HUMAN' where id = %s",
            (uuid.UUID(human_ticket_id),),
        )
    with customer_browser_client(spring_url) as client:
        handed_off = client.post(
            f"{spring_url}/api/customer/tickets/{human_ticket_id}/clarifications/"
            f"{human_projection['clarification']['id']}/replies",
            headers={
                "Idempotency-Key": f"human-mode-{uuid.uuid4()}",
                "X-Resume-Request-Id": str(uuid.uuid4()),
            },
            json={"answer": "A"},
        )
        expect_status(handed_off, 409)

    fixed_now = "2026-08-09T14:00:00Z"
    first_warning_headers = {
        "Idempotency-Key": f"sla-first-warning-{uuid.uuid4()}",
    }
    with customer_browser_client(spring_url) as client:
        first_warning_response = client.post(
            f"{spring_url}/api/customer/tickets",
            headers=first_warning_headers,
            json={"orderReference": "ORDER-INTAKE-ONLY", "description": "首次响应边界验收"},
        )
        expect_status(first_warning_response, 201)
        first_warning_ticket_id = uuid.UUID(first_warning_response.json()["ticketId"])

    ticket_uuid = uuid.UUID(ticket_id)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "insert into support_assignment (id, ticket_id, support_id, status, assigned_at) "
            "values (%s, %s, 'support-demo', 'ACTIVE', %s)",
            (uuid.uuid4(), ticket_uuid, fixed_now),
        )
        connection.execute(
            "update support_ticket set created_at = %s::timestamptz - interval '15 minutes', "
            "first_responded_at = %s, lifecycle_state = 'WAITING_FOR_CUSTOMER', "
            "resolution_elapsed_seconds = 86399, resolution_running_since = null where id = %s",
            (fixed_now, fixed_now, ticket_uuid),
        )
        connection.execute(
            "update support_ticket set created_at = %s::timestamptz - interval '12 minutes', "
            "first_responded_at = %s, lifecycle_state = 'WAITING_FOR_CUSTOMER', "
            "resolution_elapsed_seconds = 69120, resolution_running_since = null where id = %s",
            (fixed_now, fixed_now, first_warning_ticket_id),
        )

    first_warning_facts = []
    resolution_warning_facts = []
    paused_resolution_breach = -1
    for _ in range(40):
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            first_warning_facts = connection.execute(
                "select fact_type from ticket_sla_fact where ticket_id = %s and objective = 'FIRST_RESPONSE'",
                (first_warning_ticket_id,),
            ).fetchall()
            resolution_warning_facts = connection.execute(
                "select fact_type from ticket_sla_fact where ticket_id = %s and objective = 'RESOLUTION'",
                (first_warning_ticket_id,),
            ).fetchall()
            paused_resolution_breach = connection.execute(
                "select count(*) from ticket_sla_fact where ticket_id = %s "
                "and objective = 'RESOLUTION' and fact_type = 'BREACH'",
                (ticket_uuid,),
            ).fetchone()[0]
        if first_warning_facts:
            break
        time.sleep(0.25)
    assert first_warning_facts == [("WARNING",)]
    assert resolution_warning_facts == [("WARNING",)]
    assert paused_resolution_breach == 0

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update support_ticket set lifecycle_state = 'WAITING_FOR_EXTERNAL', "
            "resolution_running_since = %s::timestamptz - interval '1 second' where id = %s",
            (fixed_now, ticket_uuid),
        )

    sla_facts = []
    for _ in range(40):
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            sla_facts = connection.execute(
                "select objective, fact_type from ticket_sla_fact where ticket_id = %s "
                "order by objective, fact_type",
                (ticket_uuid,),
            ).fetchall()
        if len(sla_facts) == 4:
            break
        time.sleep(0.25)
    assert sla_facts == [
        ("FIRST_RESPONSE", "BREACH"),
        ("FIRST_RESPONSE", "WARNING"),
        ("RESOLUTION", "BREACH"),
        ("RESOLUTION", "WARNING"),
    ]

    with customer_browser_client(spring_url) as client:
        notifications = client.get(
            f"{spring_url}/api/support/sla/notifications",
        )
        expect_status(notifications, 200)
        assert {
            item["objective"] for item in notifications.json() if item["ticketId"] == ticket_id
        } == {"FIRST_RESPONSE", "RESOLUTION"}
        escalations = client.get(
            f"{spring_url}/api/support/escalations",
        )
        expect_status(escalations, 200)
        queue_item = next(item for item in escalations.json() if item["ticketId"] == ticket_id)
        assert queue_item["lifecycleState"] == "WAITING_FOR_EXTERNAL"
        assert queue_item["handlingMode"] == "AGENT"
        assert queue_item["reasonCode"] == "SLA_BREACH"
        assert set(queue_item["breachedObjectives"]) == {"FIRST_RESPONSE", "RESOLUTION"}
        assert not any(
            field in queue_item
            for field in (
                "customerId",
                "orderReference",
                "description",
                "messages",
                "investigationFacts",
            )
        )
        workbench_before_handoff = client.get(
            f"{spring_url}/api/support/workbench/snapshot",
        )
        expect_status(workbench_before_handoff, 200)
        workbench_before_handoff = workbench_before_handoff.json()
        assert workbench_before_handoff["view"] == "SUPPORT_WORKBENCH"
        assert workbench_before_handoff["schema"] == "support-workbench-v1"
        workbench_cursor = workbench_before_handoff["cursor"]
        sla_handoff_request_id = f"sla-handoff-{uuid.uuid4()}"
        sla_handoff = client.post(
            f"{spring_url}/api/customer/tickets/{ticket_id}/human-handoff",
            headers={
                "Idempotency-Key": sla_handoff_request_id,
            },
            json={"reasonCode": "CUSTOMER_REQUESTED"},
        )
        expect_status(sla_handoff, 202)
        shared_queue = client.get(
            f"{spring_url}/api/support/queue",
        )
        expect_status(shared_queue, 200)
        combined_queue_item = next(
            item for item in shared_queue.json() if item["ticketId"] == ticket_id
        )
        assert set(combined_queue_item["reasonCodes"]) == {
            "SLA_BREACH",
            "CUSTOMER_REQUESTED_HANDOFF",
        }
        assert combined_queue_item["handlingMode"] == "HUMAN"
        escalations_after_handoff = client.get(
            f"{spring_url}/api/support/escalations",
        )
        expect_status(escalations_after_handoff, 200)
        assert sum(item["ticketId"] == ticket_id for item in escalations_after_handoff.json()) == 1
        workbench_after_handoff = client.get(
            f"{spring_url}/api/support/workbench/snapshot",
        )
        expect_status(workbench_after_handoff, 200)
        assert workbench_after_handoff.headers["cache-control"] == "no-store"
        workbench_after_handoff = workbench_after_handoff.json()
        shared_workbench_item = next(
            item for item in workbench_after_handoff["sharedQueue"] if item["ticketId"] == ticket_id
        )
        escalation_workbench_item = next(
            item
            for item in workbench_after_handoff["escalationQueue"]
            if item["ticketId"] == ticket_id
        )
        assert shared_workbench_item["handlingMode"] == "HUMAN"
        assert escalation_workbench_item["handlingMode"] == "HUMAN"
        assert set(shared_workbench_item) == {
            "ticketId",
            "lifecycleState",
            "handlingMode",
            "enteredAt",
        }
        assert not any(
            field in json.dumps(workbench_after_handoff)
            for field in (
                "reasonCode",
                "investigationSummary",
                "customerId",
                "orderReference",
                "description",
                "messages",
            )
        )
        with client.stream(
            "GET",
            f"{spring_url}/api/support/workbench/events",
            headers={
                "Last-Event-ID": workbench_cursor,
            },
        ) as stream:
            expect_status(stream, 200)
            replay_lines = []
            for line in stream.iter_lines():
                replay_lines.append(line)
                if line == "" and any(
                    part.startswith("id:support-workbench-v1:") for part in replay_lines
                ):
                    break
        assert any(part == "event:QUEUE_TICKET_UPSERTED" for part in replay_lines)
        assert any('"view":"SUPPORT_WORKBENCH"' in part for part in replay_lines)
        assigned_detail = client.get(
            f"{spring_url}/api/support/workbench/tickets/{ticket_id}",
        )
        expect_status(assigned_detail, 200)
        assert assigned_detail.headers["cache-control"] == "no-store"
        assert assigned_detail.json()["ticketId"] == ticket_id
        assert "publicConversation" in assigned_detail.json()
        assert "investigationFacts" in assigned_detail.json()
        assert "businessTimeline" in assigned_detail.json()
        with isolated_customer_browser_client(spring_url) as customer_client:
            denied_queue = customer_client.get(
                f"{spring_url}/api/support/escalations",
            )
            expect_status(denied_queue, 403)
        denied_workbench = httpx.get(
            f"{spring_url}/api/support/workbench/snapshot",
            timeout=20.0,
        )
        expect_status(denied_workbench, 401)
        unassigned_workbench_detail = client.get(
            f"{spring_url}/api/support/workbench/tickets/{first_warning_ticket_id}",
        )
        expect_status(unassigned_workbench_detail, 404)
        assert unassigned_workbench_detail.headers["cache-control"] == "no-store"
        unassigned_detail = client.get(
            f"{spring_url}/api/support/tickets/{first_warning_ticket_id}",
        )
        expect_status(unassigned_detail, 404)

        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            connection.execute(
                "insert into shared_support_queue_entry (ticket_id, reason_code, entered_at) "
                "values (%s, 'SLA_BREACH', clock_timestamp())",
                (first_warning_ticket_id,),
            )

        support_headers = dict(support_session_headers(spring_url))
        support_cookie = {"Cookie": support_headers["Cookie"]}
        missing_csrf_claim = httpx.post(
            f"{spring_url}/api/support/workbench/tickets/{first_warning_ticket_id}/claims",
            headers=support_cookie,
            timeout=20.0,
        )
        expect_status(missing_csrf_claim, 403)
        forged_claim = client.post(
            f"{spring_url}/api/support/workbench/tickets/{first_warning_ticket_id}/claims",
        )
        expect_status(forged_claim, 201)
        assert forged_claim.json() == {
            "ticketId": str(first_warning_ticket_id),
            "supportId": "support-demo",
            "replayed": False,
        }
        replayed_claim = client.post(
            f"{spring_url}/api/support/workbench/tickets/{first_warning_ticket_id}/claims"
        )
        expect_status(replayed_claim, 200)
        assert replayed_claim.json()["replayed"] is True
        assigned_after_claim = client.get(
            f"{spring_url}/api/support/workbench/tickets/{first_warning_ticket_id}"
        )
        expect_status(assigned_after_claim, 200)
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            assignment = connection.execute(
                "select support_id, status from support_assignment "
                "where ticket_id = %s order by assigned_at desc limit 1",
                (first_warning_ticket_id,),
            ).fetchone()
            queued_after_claim = connection.execute(
                "select count(*) from shared_support_queue_entry where ticket_id = %s",
                (first_warning_ticket_id,),
            ).fetchone()
            assert assignment == ("support-demo", "ACTIVE")
            assert queued_after_claim == (0,)
            connection.execute(
                "update support_assignment set status = 'REVOKED', revoked_at = clock_timestamp() "
                "where ticket_id = %s and status = 'ACTIVE'",
                (first_warning_ticket_id,),
            )
        revoked_detail = client.get(
            f"{spring_url}/api/support/workbench/tickets/{first_warning_ticket_id}"
        )
        expect_status(revoked_detail, 404)

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        removal_ticket_id = first_warning_ticket_id
        connection.execute(
            "insert into shared_support_queue_entry (ticket_id, reason_code, entered_at) "
            "values (%s, 'SLA_BREACH', %s)",
            (removal_ticket_id, fixed_now),
        )
        connection.execute(
            "delete from shared_support_queue_entry where ticket_id = %s",
            (removal_ticket_id,),
        )
    with customer_browser_client(spring_url) as client:
        workbench_after_removal = client.get(
            f"{spring_url}/api/support/workbench/snapshot",
        )
        expect_status(workbench_after_removal, 200)
        assert not any(
            item["ticketId"] == str(removal_ticket_id)
            for queue_name in ("sharedQueue", "escalationQueue")
            for item in workbench_after_removal.json()[queue_name]
        )

    immediate_ticket_id, immediate_projection = create_ambiguous_ticket("sla-resume-boundary")
    immediate_request_id = immediate_projection["clarification"]["id"]
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update support_ticket set resolution_elapsed_seconds = 86400, "
            "resolution_running_since = null where id = %s",
            (uuid.UUID(immediate_ticket_id),),
        )
    with customer_browser_client(spring_url) as client:
        immediate_reply = client.post(
            f"{spring_url}/api/customer/tickets/{immediate_ticket_id}/clarifications/"
            f"{immediate_request_id}/replies",
            headers={
                "Idempotency-Key": f"sla-resume-message-{uuid.uuid4()}",
                "X-Resume-Request-Id": str(uuid.uuid4()),
            },
            json={"answer": "A"},
        )
        expect_status(immediate_reply, 202)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert (
            connection.execute(
                "select count(*) from ticket_sla_fact where ticket_id = %s "
                "and objective = 'RESOLUTION' and fact_type = 'BREACH'",
                (uuid.UUID(immediate_ticket_id),),
            ).fetchone()[0]
            == 1
        )

    time.sleep(1.5)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert (
            connection.execute(
                "select count(*) from ticket_sla_fact where ticket_id = %s", (ticket_uuid,)
            ).fetchone()[0]
            == 4
        )
        assert (
            connection.execute(
                "select count(*) from audit_event where ticket_id = %s and event_type like 'SLA_%%'",
                (ticket_uuid,),
            ).fetchone()[0]
            == 4
        )
        assert connection.execute(
            "select lifecycle_state, handling_mode, resolution_elapsed_seconds from support_ticket where id = %s",
            (ticket_uuid,),
        ).fetchone() == ("WAITING_FOR_EXTERNAL", "HUMAN", 86399)

    with customer_browser_client(spring_url) as client:
        concurrent_state_response = client.post(
            f"{spring_url}/api/customer/tickets",
            headers={
                "Idempotency-Key": f"sla-concurrent-state-{uuid.uuid4()}",
            },
            json={"orderReference": "ORDER-INTAKE-ONLY", "description": "并发状态变化验收"},
        )
        expect_status(concurrent_state_response, 201)
        concurrent_state_ticket_id = uuid.UUID(concurrent_state_response.json()["ticketId"])
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "select id from support_ticket where id = %s for update",
            (concurrent_state_ticket_id,),
        )
        connection.execute(
            "update support_ticket set lifecycle_state = 'WAITING_FOR_EXTERNAL', "
            "resolution_elapsed_seconds = 86400, resolution_running_since = null where id = %s",
            (concurrent_state_ticket_id,),
        )
        time.sleep(1.25)
        connection.execute(
            "update support_ticket set lifecycle_state = 'RESOLVED', resolved_at = %s, "
            "close_due_at = %s::timestamptz + interval '72 hours' where id = %s",
            (fixed_now, fixed_now, concurrent_state_ticket_id),
        )
    time.sleep(1.25)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select lifecycle_state, resolution_elapsed_seconds from support_ticket where id = %s",
            (concurrent_state_ticket_id,),
        ).fetchone() == ("RESOLVED", 86400)
        assert (
            connection.execute(
                "select count(*) from ticket_sla_fact where ticket_id = %s and objective = 'RESOLUTION'",
                (concurrent_state_ticket_id,),
            ).fetchone()[0]
            == 2
        )
        connection.execute(
            "update support_ticket set lifecycle_state = 'INVESTIGATING', "
            "resolution_running_since = %s, resolved_at = null, close_due_at = null where id = %s",
            (fixed_now, concurrent_state_ticket_id),
        )
    time.sleep(1.25)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select lifecycle_state, resolution_elapsed_seconds, resolution_running_since is not null "
            "from support_ticket where id = %s",
            (concurrent_state_ticket_id,),
        ).fetchone() == ("INVESTIGATING", 86400, True)
        assert (
            connection.execute(
                "select count(*) from ticket_sla_fact where ticket_id = %s and objective = 'RESOLUTION'",
                (concurrent_state_ticket_id,),
            ).fetchone()[0]
            == 2
        )
    try:
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            connection.execute(
                "update support_ticket set resolution_elapsed_seconds = 0 where id = %s",
                (concurrent_state_ticket_id,),
            )
        raise AssertionError("resolution elapsed time unexpectedly reset on reopen")
    except psycopg.errors.CheckViolation as error:
        assert error.diag.constraint_name == "resolution_elapsed_seconds_monotonic"

    def create_closure_fixture(suffix: str, resolved_at, handling_mode: str = "HUMAN"):
        with customer_browser_client(spring_url) as client:
            response = client.post(
                f"{spring_url}/api/customer/tickets",
                headers={
                    "Idempotency-Key": f"issue-28-{suffix}-{uuid.uuid4()}",
                },
                json={
                    "orderReference": "ORDER-INTAKE-ONLY",
                    "description": f"关闭等待期验收 {suffix}",
                },
            )
            expect_status(response, 201)
            fixture_id = uuid.UUID(response.json()["ticketId"])
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            connection.execute(
                "update support_ticket set lifecycle_state = 'RESOLVED', handling_mode = %s, "
                "resolution_elapsed_seconds = 3600, resolution_running_since = null, "
                "resolved_at = %s, close_due_at = %s::timestamptz + interval '72 hours' where id = %s",
                (handling_mode, resolved_at, resolved_at, fixture_id),
            )
        return fixture_id

    closure_now = datetime.datetime.fromisoformat(fixed_now.replace("Z", "+00:00"))
    before_boundary_id = create_closure_fixture(
        "before-boundary",
        closure_now - datetime.timedelta(hours=72) + datetime.timedelta(microseconds=1),
        "AGENT",
    )
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        before_first_response = connection.execute(
            "select first_responded_at from support_ticket where id = %s", (before_boundary_id,)
        ).fetchone()[0]
        before_generation = connection.execute(
            "select generation_number, thread_id from agent_processing_generation where ticket_id = %s",
            (before_boundary_id,),
        ).fetchone()
    with customer_browser_client(spring_url) as client:
        reopened = client.post(
            f"{spring_url}/api/customer/tickets/{before_boundary_id}/replies",
            headers={
                "Idempotency-Key": "issue-28-before-boundary-message",
            },
            json={
                "orderReference": "ORDER-INTAKE-ONLY",
                "issueKind": "LOGISTICS_DELAY",
                "message": "原问题仍未解决",
            },
        )
        expect_status(reopened, 200)
        assert reopened.json() == {
            "ticketId": str(before_boundary_id),
            "outcome": "REOPENED",
            "replayed": False,
        }
        reopened_replay = client.post(
            f"{spring_url}/api/customer/tickets/{before_boundary_id}/replies",
            headers={
                "Idempotency-Key": "issue-28-before-boundary-message",
            },
            json={
                "orderReference": "ORDER-INTAKE-ONLY",
                "issueKind": "LOGISTICS_DELAY",
                "message": "原问题仍未解决",
            },
        )
        expect_status(reopened_replay, 200)
        assert reopened_replay.json()["replayed"] is True
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        reopened_state = connection.execute(
            "select lifecycle_state, resolution_elapsed_seconds, first_responded_at, "
            "resolved_at is null, close_due_at is null from support_ticket where id = %s",
            (before_boundary_id,),
        ).fetchone()
        assert reopened_state == ("INVESTIGATING", 3600, before_first_response, True, True)
        generations = connection.execute(
            "select generation_number, thread_id from agent_processing_generation "
            "where ticket_id = %s order by generation_number",
            (before_boundary_id,),
        ).fetchall()
        assert len(generations) == 2
        assert generations[0] == before_generation
        assert generations[1][0] == before_generation[0] + 1
        assert generations[1][1] != before_generation[1]
        assert (
            connection.execute(
                "select count(*) from customer_reply_request where customer_id = 'customer-demo' "
                "and message_id = 'issue-28-before-boundary-message'",
            ).fetchone()[0]
            == 1
        )

    different_issue_id = create_closure_fixture(
        "different-issue", closure_now - datetime.timedelta(hours=1)
    )
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        original_message_count = connection.execute(
            "select count(*) from public_message where ticket_id = %s", (different_issue_id,)
        ).fetchone()[0]
    with customer_browser_client(spring_url) as client:
        different = client.post(
            f"{spring_url}/api/customer/tickets/{different_issue_id}/replies",
            headers={
                "Idempotency-Key": "issue-28-different-message",
            },
            json={
                "orderReference": "ORDER-INTAKE-ONLY",
                "issueKind": "OTHER",
                "message": "同一订单的另一个问题",
            },
        )
        expect_status(different, 201)
        different_linked_id = uuid.UUID(different.json()["ticketId"])
        conflict = client.post(
            f"{spring_url}/api/customer/tickets/{different_issue_id}/replies",
            headers={
                "Idempotency-Key": "issue-28-different-message",
            },
            json={
                "orderReference": "ORDER-INTAKE-ONLY",
                "issueKind": "OTHER",
                "message": "复用身份但改变内容",
            },
        )
        expect_status(conflict, 409)
        assert conflict.json()["code"] == "MESSAGE_ID_CONFLICT"
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert (
            connection.execute(
                "select lifecycle_state from support_ticket where id = %s", (different_issue_id,)
            ).fetchone()[0]
            == "RESOLVED"
        )
        assert (
            connection.execute(
                "select count(*) from public_message where ticket_id = %s", (different_issue_id,)
            ).fetchone()[0]
            == original_message_count
        )
        assert connection.execute(
            "select follow_up_of, issue_kind, handling_mode from support_ticket where id = %s",
            (different_linked_id,),
        ).fetchone() == (different_issue_id, "OTHER", "HUMAN")
        assert (
            connection.execute(
                "select count(*) from agent_processing_generation where ticket_id = %s",
                (different_linked_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "select count(*) from shared_support_queue_entry where ticket_id = %s "
                "and reason_code = 'UNSUPPORTED_ISSUE'",
                (different_linked_id,),
            ).fetchone()[0]
            == 1
        )

    exact_boundary_id = create_closure_fixture(
        "exact-boundary", closure_now - datetime.timedelta(hours=1)
    )
    queue_reasons_before_close = [
        "SLA_BREACH",
        "CUSTOMER_REQUESTED_HANDOFF",
        "AGENT_HUMAN_HANDOFF",
    ]
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "insert into shared_support_queue_entry (ticket_id, reason_code, entered_at) "
            "select %s, reason_code, %s from unnest(%s::text[]) reason_code",
            (exact_boundary_id, closure_now, queue_reasons_before_close),
        )
    with customer_browser_client(spring_url) as client:
        queue_before_close = client.get(
            f"{spring_url}/api/support/workbench/snapshot",
        )
        expect_status(queue_before_close, 200)
        queue_before_close_payload = queue_before_close.json()
        assert str(exact_boundary_id) in {
            item["ticketId"] for item in queue_before_close_payload["sharedQueue"]
        }
        queue_cursor_before_close = queue_before_close_payload["cursor"]

    queue_stream_connected = threading.Event()

    def observe_live_queue_removal() -> str:
        with (
            customer_browser_client(spring_url) as stream_client,
            stream_client.stream(
                "GET",
                f"{spring_url}/api/support/workbench/events",
                headers={
                    "Last-Event-ID": queue_cursor_before_close,
                },
            ) as queue_events,
        ):
            expect_status(queue_events, 200)
            queue_event_block = []
            for line in queue_events.iter_lines():
                if line == ":connected":
                    queue_stream_connected.set()
                if line:
                    queue_event_block.append(line)
                    continue
                rendered_event = "\n".join(queue_event_block)
                if (
                    "event:QUEUE_TICKET_REMOVED" in rendered_event
                    and str(exact_boundary_id) in rendered_event
                ):
                    return rendered_event
                queue_event_block = []
        raise AssertionError("live support queue stream closed before ticket removal")

    queue_stream_pool = ThreadPoolExecutor(max_workers=1)
    queue_stream_future = queue_stream_pool.submit(observe_live_queue_removal)
    assert queue_stream_connected.wait(timeout=5), "support queue SSE did not establish"
    boundary_headers = {
        "Idempotency-Key": "issue-28-exact-boundary-message",
    }
    boundary_payload = {
        "orderReference": "ORDER-INTAKE-ONLY",
        "issueKind": "LOGISTICS_DELAY",
        "message": "边界时刻回复",
    }

    def reply_at_boundary(_: int):
        with customer_browser_client(spring_url) as concurrent_client:
            return concurrent_client.post(
                f"{spring_url}/api/customer/tickets/{exact_boundary_id}/replies",
                headers=boundary_headers,
                json=boundary_payload,
            )

    authority_key = f"{exact_boundary_id}\nBUSINESS_AUTHORITY"
    lock_connection = psycopg.connect(os.environ["SPRING_DATABASE_URI"])
    lock_connection.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (authority_key,))
    lock_connection.execute(
        "update support_ticket set resolved_at = %s, "
        "close_due_at = %s::timestamptz + interval '72 hours' where id = %s",
        (
            closure_now - datetime.timedelta(hours=72),
            closure_now - datetime.timedelta(hours=72),
            exact_boundary_id,
        ),
    )
    lock_connection.commit()
    boundary_pool = ThreadPoolExecutor(max_workers=1)
    boundary_future = boundary_pool.submit(reply_at_boundary, 0)
    blocked_authority_writers = 0
    for _ in range(40):
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as observation:
            blocked_authority_writers = observation.execute(
                "select count(*) from pg_locks where locktype = 'advisory' and not granted"
            ).fetchone()[0]
        if blocked_authority_writers >= 2:
            break
        time.sleep(0.25)
    unlocked = lock_connection.execute(
        "select pg_advisory_unlock(hashtextextended(%s, 0))", (authority_key,)
    ).fetchone()[0]
    lock_connection.commit()
    lock_connection.close()
    boundary_responses = [boundary_future.result(timeout=20)]
    boundary_pool.shutdown()
    assert unlocked is True
    assert blocked_authority_writers >= 2, blocked_authority_writers
    with ThreadPoolExecutor(max_workers=7) as replay_pool:
        boundary_responses.extend(replay_pool.map(reply_at_boundary, range(1, 8)))
    assert sorted(response.status_code for response in boundary_responses) == [200] * 7 + [201]
    boundary_result_ids = {response.json()["ticketId"] for response in boundary_responses}
    assert len(boundary_result_ids) == 1
    boundary_linked_id = uuid.UUID(boundary_result_ids.pop())
    time.sleep(1.5)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert (
            connection.execute(
                "select lifecycle_state from support_ticket where id = %s", (exact_boundary_id,)
            ).fetchone()[0]
            == "CLOSED"
        )
        assert (
            connection.execute(
                "select count(*) from audit_event where ticket_id = %s and event_type = 'TICKET_CLOSED'",
                (exact_boundary_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "select follow_up_of from support_ticket where id = %s", (boundary_linked_id,)
            ).fetchone()[0]
            == exact_boundary_id
        )
        assert (
            connection.execute(
                "select count(*) from customer_reply_request where original_ticket_id = %s "
                "and message_id = 'issue-28-exact-boundary-message'",
                (exact_boundary_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "select count(*) from shared_support_queue_entry where ticket_id = %s",
                (exact_boundary_id,),
            ).fetchone()[0]
            == 0
        )

    with customer_browser_client(spring_url) as client:
        queue_after_close = client.get(
            f"{spring_url}/api/support/workbench/snapshot",
        )
        expect_status(queue_after_close, 200)
        assert str(exact_boundary_id) not in {
            item["ticketId"] for item in queue_after_close.json()["sharedQueue"]
        }
    queue_event_stream = queue_stream_future.result(timeout=10)
    queue_stream_pool.shutdown()
    assert "event:QUEUE_TICKET_REMOVED" in queue_event_stream
    assert str(exact_boundary_id) in queue_event_stream

    with customer_browser_client(spring_url) as client:
        closed_follow_up = client.post(
            f"{spring_url}/api/customer/tickets/{exact_boundary_id}/replies",
            headers={
                "Idempotency-Key": "issue-28-closed-message",
            },
            json={
                "orderReference": "ORDER-INTAKE-ONLY",
                "issueKind": "LOGISTICS_DELAY",
                "message": "关闭后的后续回复",
            },
        )
        expect_status(closed_follow_up, 201)
        closed_follow_up_id = uuid.UUID(closed_follow_up.json()["ticketId"])
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert (
            connection.execute(
                "select follow_up_of from support_ticket where id = %s", (closed_follow_up_id,)
            ).fetchone()[0]
            == exact_boundary_id
        )
        assert (
            connection.execute(
                "select lifecycle_state from support_ticket where id = %s", (exact_boundary_id,)
            ).fetchone()[0]
            == "CLOSED"
        )

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
        raise AssertionError(
            f"cross-database connection unexpectedly succeeded: {forbidden_database}"
        )

    print(
        json.dumps(
            {
                "status": "UP",
                "thread_id": thread_id,
                "checkpoint_count": checkpoint_count,
                "ticket_id": ticket_id,
                "resolved_ticket_id": resolved_ticket_id,
                "proposal_ticket_id": proposal_ticket_id,
                "proposal_revision_count": 2,
                "rejected_proposal_count": len(rejected_ticket_ids),
                "concurrent_reservation_results": reservation_results,
                "concurrent_clarification_reply_statuses": concurrent_reply_statuses,
                "human_handoff_ticket_id": handoff_ticket_id,
                "agent_handoff_ticket_id": agent_handoff_ticket_id,
                "concurrent_agent_handoff_statuses": concurrent_agent_handoff_statuses,
                "handoff_reply_race_statuses": race_statuses,
                "clarification_resume_status": resume_status,
                "sla_fact_count": len(sla_facts),
                "sla_resume_immediate": True,
                "concurrent_replays": 7,
                "approval_claim_statuses": sorted(
                    response.status_code for response in approval_claim_responses
                ),
                "approval_lease_versions": [1, 2, 3],
                "approval_replacement_revoked": True,
                "approval_rejection_ticket_id": str(rejection_ticket_id),
                "approval_rejection_replayed": True,
                "concurrent_rejection_statuses": sorted(
                    response.status_code for response in rejection_responses
                ),
                "approval_execution_id": approved_payload["executionId"],
                "execution_claim_statuses": sorted(
                    response.status_code for response in execution_claim_responses
                ),
                "execution_success_replayed": True,
                "coupon_10_execution_id": coupon_10_execution_id,
                "coupon_10_ticket_id": coupon_10_ticket_id,
                "coupon_20_execution_id": coupon_20_execution_id,
                "coupon_20_ticket_id": coupon_20_ticket_id,
                "partial_refund_ticket_id": str(approval_ticket_id),
                "automatic_executor_execution_id": auto_execution_id,
                "automatic_executor_ticket_id": str(auto_ticket_id),
                "approval_fact_drift_invalidated": str(drift_ticket_id),
                "concurrent_proposal_intent_results": sorted(proposal_race_results),
                "approve_reject_statuses": sorted(
                    response.status_code for response in race_responses
                ),
                "approve_reject_winner": race_decision,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"smoke failed: {error}", file=sys.stderr)
        raise
