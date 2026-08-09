import json
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

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
        "orderReference": "ORDER-INTAKE-ONLY",
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
        assert connection.execute(
            "select count(*) from audit_event where ticket_id = %s", (resolved_uuid,)
        ).fetchone()[0] >= 8

    proposal_request = f"issue-15-{uuid.uuid4()}"
    proposal_order_reference = "ORDER-DELAY-001"
    with httpx.Client(timeout=20.0) as client:
        accepted = client.post(
            f"{spring_url}/api/customer/tickets",
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
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
                "s.available_compensation_amount, jsonb_array_length(s.evidence_references) "
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
        1, 80, 288000, "SIMULATED_PARTIAL_REFUND", Decimal("26.80"), "LOGISTICS_DELAY",
        "delay-policy-v1", proposal_row[9], "PENDING_APPROVAL", "COMPLETED",
        80, 288000, Decimal("268.00"), Decimal("268.00"), 2,
    )
    assert len(proposal_row[9]) == 64
    first_revision_id, proposal_id = proposal_row[:2]

    with httpx.Client(timeout=20.0) as client:
        customer_view = client.get(
            f"{spring_url}/api/customer/tickets/{proposal_ticket_id}",
            headers={"X-Synthetic-Customer-Id": "customer-demo"},
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
                "(id, proposal_id, revision_number, ticket_id, order_reference, generation_id, delay_hours, delay_seconds, compensation_method, amount, reason_code, evidence_references, policy_version, content_digest, status, created_at) "
                "select %s, %s, 1, %s, order_reference, %s, delay_hours, delay_seconds, compensation_method, amount, reason_code, evidence_references, policy_version, %s, 'PENDING_APPROVAL', now() "
                "from compensation_proposal_revision where id = %s",
                (uuid.uuid4(), uuid.uuid4(), duplicate_ticket, duplicate_generation, "f" * 64, first_revision_id),
            )
        raise AssertionError("active intent unique constraint unexpectedly accepted a duplicate")
    except psycopg.errors.UniqueViolation as error:
        assert error.diag.constraint_name == "one_active_logistics_compensation_intent"

    second_generation = uuid.uuid4()
    with psycopg.connect(os.environ["SPRING_FIXTURE_DATABASE_URI"]) as connection:
        connection.execute(
            "update synthetic_order set delay_hours = 81, delay_seconds = 291600 "
            "where order_reference = %s",
            (proposal_order_reference,),
        )
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "insert into agent_processing_generation (id, ticket_id, generation_number, thread_id, status, created_at) "
            "values (%s, %s, 2, %s, 'ACTIVE', now())",
            (second_generation, uuid.UUID(proposal_ticket_id), uuid.uuid4()),
        )
    scoped_headers = {
        "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
        "X-Agent-Generation-Id": str(second_generation),
    }
    with httpx.Client(timeout=20.0) as client:
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
                "delayHours": 81,
                "delaySeconds": 291600,
                "orderReference": proposal_order_reference,
                "evidenceRefs": evidence_refs,
                "suggestedMethod": "COUPON",
                "suggestedAmount": "999999.99",
            },
        )
        expect_status(replacement, 200)
        assert replacement.json()["proposalRevision"] == 2
        assert replacement.json()["proposalStatus"] == "PENDING_APPROVAL"

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        revisions = connection.execute(
            "select proposal_id, revision_number, delay_hours, delay_seconds, amount, status "
            "from compensation_proposal_revision where ticket_id = %s order by revision_number",
            (uuid.UUID(proposal_ticket_id),),
        ).fetchall()
        assert revisions == [
            (proposal_id, 1, 80, 288000, Decimal("26.80"), "SUPERSEDED"),
            (proposal_id, 2, 81, 291600, Decimal("26.80"), "PENDING_APPROVAL"),
        ]

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
            "values (%s, %s, 3, %s, 'ACTIVE', now())",
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
    with httpx.Client(timeout=20.0) as client:
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
                "suggestedMethod": "COUPON",
                "suggestedAmount": "999999.99",
            },
        )
        expect_status(approved_replacement, 422)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select revision_number, status from compensation_proposal_revision "
            "where ticket_id = %s order by revision_number",
            (uuid.UUID(proposal_ticket_id),),
        ).fetchall() == [(1, "SUPERSEDED"), (2, "APPROVED")]

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
            return error.diag.constraint_name

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservation_results = list(executor.map(lambda _: reserve_concurrently(), range(2)))
    assert sorted(reservation_results) == ["accepted", "compensation_reservation_capacity"]

    rejection_cases = {
        "ORDER-DELAY-CANCELLED": "COMPENSATION_PROPOSAL_INELIGIBLE",
        "ORDER-DELAY-UNPAID": "COMPENSATION_PROPOSAL_INELIGIBLE",
        "ORDER-DELAY-REFUNDED": "COMPENSATION_PROPOSAL_INELIGIBLE",
        "ORDER-DELAY-COMPENSATED": "COMPENSATION_PROPOSAL_INELIGIBLE",
        "ORDER-DELAY-LOW-ALLOWANCE": "COMPENSATION_ALLOWANCE_INSUFFICIENT",
        "ORDER-DELAY-RESERVED": "COMPENSATION_ALLOWANCE_INSUFFICIENT",
    }
    rejected_ticket_ids = []
    with httpx.Client(timeout=20.0) as client:
        for order_reference, expected_reason in rejection_cases.items():
            response = client.post(
                f"{spring_url}/api/customer/tickets",
                headers={
                    "X-Synthetic-Customer-Id": "customer-demo",
                    "Idempotency-Key": f"reject-{uuid.uuid4()}",
                },
                json={"orderReference": order_reference, "description": "不合法补偿提案验收"},
            )
            expect_status(response, 201)
            rejected_id = uuid.UUID(response.json()["ticketId"])
            rejected_ticket_ids.append(rejected_id)
            observed = False
            for _ in range(40):
                with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
                    observed = connection.execute(
                        "select exists(select 1 from audit_event where ticket_id = %s and event_type = %s)",
                        (rejected_id, "AGENT_COMMAND_REJECTED_" + expected_reason),
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
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                f"{spring_url}/api/customer/tickets",
                headers={
                    "X-Synthetic-Customer-Id": "customer-demo",
                    "Idempotency-Key": f"clarification-{label}-{uuid.uuid4()}",
                },
                json={"orderReference": "ORDER-DELAY-AMBIGUOUS", "description": f"需要确认订单 {label}"},
            )
            expect_status(response, 201)
            created_id = response.json()["ticketId"]
            for _ in range(80):
                projection_response = client.get(
                    f"{spring_url}/api/customer/tickets/{created_id}",
                    headers={"X-Synthetic-Customer-Id": "customer-demo"},
                )
                expect_status(projection_response, 200)
                projection = projection_response.json()
                if projection["ticket"]["lifecycleState"] == "WAITING_FOR_CUSTOMER" and projection["clarification"]:
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
    with httpx.Client(timeout=20.0) as client:
        invalid = client.post(
            reply_url,
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
                "Idempotency-Key": f"invalid-{uuid.uuid4()}",
                "X-Resume-Request-Id": str(uuid.uuid4()),
            },
            json={"answer": "unrelated input"},
        )
        expect_status(invalid, 422)
        accepted_reply = client.post(
            reply_url,
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
                "Idempotency-Key": reply_message_id,
                "X-Resume-Request-Id": resume_request_id,
            },
            json={"answer": "A"},
        )
        expect_status(accepted_reply, 202)
        duplicate_reply = client.post(
            reply_url,
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
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
                "X-Synthetic-Customer-Id": "customer-demo",
                "Idempotency-Key": reply_message_id,
                "X-Resume-Request-Id": resume_request_id,
            },
            json={"answer": "B"},
        )
        expect_status(conflicting_reuse, 409)
        stale_reply = client.post(
            reply_url,
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
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
                headers={"X-Synthetic-Customer-Id": "customer-demo"},
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
        assert connection.execute(
            "select count(*) from agent_resume_request where generation_id = %s",
            (clarification_generation[0],),
        ).fetchone()[0] == 1

    with httpx.Client(timeout=20.0) as client:
        runs = client.get(
            f"{agent_url}/threads/{clarification_generation[1]}/runs?limit=100",
            headers=spring_headers,
        )
        expect_status(runs, 200)
        run_metadata = [run.get("metadata", {}) for run in runs.json()]
        assert sum("submission_request_id" in metadata for metadata in run_metadata) == 1
        assert sum(metadata.get("resume_request_id") == resume_request_id for metadata in run_metadata) == 1

    concurrent_ticket_id, concurrent_projection = create_ambiguous_ticket("concurrent")
    concurrent_request_id = concurrent_projection["clarification"]["id"]
    reply_barrier = threading.Barrier(2)

    def reply_concurrently(answer: str) -> int:
        reply_barrier.wait()
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                f"{spring_url}/api/customer/tickets/{concurrent_ticket_id}/clarifications/{concurrent_request_id}/replies",
                headers={
                    "X-Synthetic-Customer-Id": "customer-demo",
                    "Idempotency-Key": f"concurrent-message-{uuid.uuid4()}",
                    "X-Resume-Request-Id": str(uuid.uuid4()),
                },
                json={"answer": answer},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent_reply_statuses = list(executor.map(reply_concurrently, ["A", "B"]))
    assert sorted(concurrent_reply_statuses) == [202, 409]

    superseded_ticket_id, superseded_projection = create_ambiguous_ticket("superseded")
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update agent_processing_generation set status = 'SUPERSEDED' where ticket_id = %s and status = 'ACTIVE'",
            (uuid.UUID(superseded_ticket_id),),
        )
    with httpx.Client(timeout=20.0) as client:
        superseded = client.post(
            f"{spring_url}/api/customer/tickets/{superseded_ticket_id}/clarifications/"
            f"{superseded_projection['clarification']['id']}/replies",
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
                "Idempotency-Key": f"superseded-{uuid.uuid4()}",
                "X-Resume-Request-Id": str(uuid.uuid4()),
            },
            json={"answer": "A"},
        )
        expect_status(superseded, 409)
    replacement_generation_id = uuid.uuid4()
    replacement_thread_id = uuid.uuid4()
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select status from customer_clarification_request where id = %s",
            (uuid.UUID(superseded_projection["clarification"]["id"]),),
        ).fetchone()[0] == "INVALIDATED"
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
    with httpx.Client(timeout=20.0) as client:
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
        assert replacement_request.json()["clarificationRequestId"] != superseded_projection["clarification"]["id"]

    human_ticket_id, human_projection = create_ambiguous_ticket("human-preference")
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update support_ticket set customer_human_preference = true where id = %s",
            (uuid.UUID(human_ticket_id),),
        )
        assert connection.execute(
            "select status from customer_clarification_request where id = %s",
            (uuid.UUID(human_projection["clarification"]["id"]),),
        ).fetchone()[0] == "INVALIDATED"
    with httpx.Client(timeout=20.0) as client:
        human_preference = client.post(
            f"{spring_url}/api/customer/tickets/{human_ticket_id}/clarifications/"
            f"{human_projection['clarification']['id']}/replies",
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
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
    with httpx.Client(timeout=20.0) as client:
        handed_off = client.post(
            f"{spring_url}/api/customer/tickets/{human_ticket_id}/clarifications/"
            f"{human_projection['clarification']['id']}/replies",
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
                "Idempotency-Key": f"human-mode-{uuid.uuid4()}",
                "X-Resume-Request-Id": str(uuid.uuid4()),
            },
            json={"answer": "A"},
        )
        expect_status(handed_off, 409)

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
        "proposal_ticket_id": proposal_ticket_id,
        "proposal_revision_count": 2,
        "rejected_proposal_count": len(rejected_ticket_ids),
        "concurrent_reservation_results": reservation_results,
        "concurrent_clarification_reply_statuses": concurrent_reply_statuses,
        "clarification_resume_status": resume_status,
        "concurrent_replays": 7,
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"smoke failed: {error}", file=sys.stderr)
        raise
