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
        ).fetchone()[0] == 6
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

    approver_headers = {"X-Synthetic-Approver-Id": "approver-demo"}
    other_approver_headers = {"X-Synthetic-Approver-Id": "approver-other-demo"}
    with httpx.Client(timeout=20.0) as client:
        queue = client.get(
            f"{spring_url}/api/approver/compensation-proposals", headers=approver_headers
        )
        expect_status(queue, 200)
        queue_item = next(
            item for item in queue.json() if item["proposalRevisionId"] == str(first_revision_id)
        )
        assert set(queue_item) == {
            "proposalRevisionId", "compensationMethod", "amount", "submittedAt", "expiresAt"
        }

        for forbidden_identity in ("customer-demo", "support-demo"):
            denied = client.get(
                f"{spring_url}/api/approver/compensation-proposals",
                headers={"X-Synthetic-Approver-Id": forbidden_identity},
            )
            expect_status(denied, 401)
        approver_customer_detail = client.get(
            f"{spring_url}/api/customer/tickets/{proposal_ticket_id}", headers=approver_headers
        )
        expect_status(approver_customer_detail, 401)
        approver_support_detail = client.get(
            f"{spring_url}/api/support/tickets/{proposal_ticket_id}", headers=approver_headers
        )
        expect_status(approver_support_detail, 404)
        approver_execution = client.get(
            f"{spring_url}/internal/capabilities/executor/probe", headers=approver_headers
        )
        expect_status(approver_execution, 400)

    claim_requests = {
        "approver-demo": f"issue-20-claim-a-{uuid.uuid4()}",
        "approver-other-demo": f"issue-20-claim-b-{uuid.uuid4()}",
    }

    def claim_concurrently(approver_id: str) -> httpx.Response:
        with httpx.Client(timeout=20.0) as concurrent_client:
            return concurrent_client.post(
                f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/claims",
                headers={
                    "X-Synthetic-Approver-Id": approver_id,
                    "Idempotency-Key": claim_requests[approver_id],
                },
                json={"requestedLeaseSeconds": 900},
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claim_responses = list(executor.map(
            claim_concurrently, ["approver-demo", "approver-other-demo"]
        ))
    assert sorted(response.status_code for response in claim_responses) == [201, 409], [
        (response.status_code, response.text) for response in claim_responses
    ]
    winner_index = next(index for index, response in enumerate(claim_responses) if response.status_code == 201)
    winner_id = ["approver-demo", "approver-other-demo"][winner_index]
    loser_id = "approver-other-demo" if winner_id == "approver-demo" else "approver-demo"
    winner_headers = {"X-Synthetic-Approver-Id": winner_id}
    lease_one = claim_responses[winner_index].json()
    assert lease_one["leaseVersion"] == 1 and lease_one["replayed"] is False

    with httpx.Client(timeout=20.0) as client:
        replay = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/claims",
            headers={**winner_headers, "Idempotency-Key": claim_requests[winner_id]},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(replay, 200)
        assert replay.json()["leaseToken"] == lease_one["leaseToken"]
        assert replay.json()["replayed"] is True
        parameter_conflict = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/claims",
            headers={**winner_headers, "Idempotency-Key": claim_requests[winner_id]},
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
        assert approval_projection["contentDigest"] == proposal_row[9]
        assert approval_projection["authoritativeAmount"] == 26.8
        assert approval_projection["orderReference"] == proposal_order_reference
        assert approval_projection["reasonCode"] == "LOGISTICS_DELAY"
        assert approval_projection["delaySeconds"] == 288000
        assert approval_projection["leaseToken"] == lease_one["leaseToken"]
        assert not any(field in approval_projection for field in (
            "ticket", "ticketId", "customerId", "description", "publicMessages", "internalNotes",
            "execution", "generationId", "threadId", "toolPayload",
        ))
        denied_other_approver = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers={
                "X-Synthetic-Approver-Id": loser_id,
                "X-Approval-Lease-Token": lease_one["leaseToken"],
                "X-Approval-Lease-Version": "1",
            },
        )
        expect_status(denied_other_approver, 403)
        denied_old_token = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers={
                **winner_headers,
                "X-Approval-Lease-Token": str(uuid.uuid4()),
                "X-Approval-Lease-Version": "1",
            },
        )
        expect_status(denied_old_token, 403)

        release_request = f"issue-20-release-{uuid.uuid4()}"
        released = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/release",
            headers={**lease_headers, "Idempotency-Key": release_request},
        )
        expect_status(released, 200)
        assert released.json() == {
            "proposalRevisionId": str(first_revision_id), "released": True, "replayed": False
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
        expect_status(revoked_after_release, 403)

        reclaim_two = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/claims",
            headers={
                "X-Synthetic-Approver-Id": loser_id,
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
        expect_status(stale_release, 403)

    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update approval_lease set claimed_at = '2026-08-09T13:59:59Z', "
            "expires_at = '2026-08-09T14:00:00Z' where proposal_revision_id = %s and lease_version = 2",
            (first_revision_id,),
        )
        proposal_expiry = connection.execute(
            "select expires_at from compensation_proposal_revision where id = %s",
            (first_revision_id,),
        ).fetchone()[0]
        assert proposal_expiry.isoformat() == "2026-08-10T14:00:00+00:00"
        assert connection.execute(
            "select count(*) from compensation_proposal_revision "
            "where id = %s and status = 'PENDING_APPROVAL' and expires_at > %s",
            (first_revision_id, proposal_expiry),
        ).fetchone()[0] == 0

    with httpx.Client(timeout=20.0) as client:
        expired_view = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers={
                "X-Synthetic-Approver-Id": loser_id,
                "X-Approval-Lease-Token": lease_two["leaseToken"],
                "X-Approval-Lease-Version": "2",
            },
        )
        expect_status(expired_view, 403)
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
            "available_compensation_amount, active_reservation_amount, paid, cancelled, fully_refunded, "
            "existing_compensation, evidence_references, captured_at) values "
            "(%s, 'ORDER-DELAY-UNDER-24', 24, 86400, 268.00, 268.00, 0.00, true, false, false, false, "
            "'[\"order:ORDER-DELAY-UNDER-24\",\"logistics:ORDER-DELAY-UNDER-24\"]', "
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

    with httpx.Client(timeout=20.0) as client:
        queue_at_proposal_expiry = client.get(
            f"{spring_url}/api/approver/compensation-proposals", headers=approver_headers
        )
        expect_status(queue_at_proposal_expiry, 200)
        assert all(
            item["proposalRevisionId"] != str(expired_revision_id)
            for item in queue_at_proposal_expiry.json()
        )
        claim_at_proposal_expiry = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{expired_revision_id}/claims",
            headers={**approver_headers, "Idempotency-Key": f"expired-claim-{uuid.uuid4()}"},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(claim_at_proposal_expiry, 410)
        expired_scope_headers = {
            **approver_headers,
            "X-Approval-Lease-Token": str(expired_lease_token),
            "X-Approval-Lease-Version": "1",
        }
        view_at_proposal_expiry = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{expired_revision_id}/approval-view",
            headers=expired_scope_headers,
        )
        expect_status(view_at_proposal_expiry, 403)
        release_at_proposal_expiry = client.post(
            f"{spring_url}/api/approver/compensation-proposals/{expired_revision_id}/release",
            headers={
                **expired_scope_headers,
                "Idempotency-Key": f"expired-release-{uuid.uuid4()}",
            },
        )
        expect_status(release_at_proposal_expiry, 403)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select status from approval_lease where proposal_revision_id = %s",
            (expired_revision_id,),
        ).fetchone()[0] == "EXPIRED"

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

        replaced_view = client.get(
            f"{spring_url}/api/approver/compensation-proposals/{first_revision_id}/approval-view",
            headers={
                **winner_headers,
                "X-Approval-Lease-Token": lease_three["leaseToken"],
                "X-Approval-Lease-Version": "3",
            },
        )
        expect_status(replaced_view, 403)

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
        assert connection.execute(
            "select status from approval_lease where proposal_revision_id = %s and lease_version = 3",
            (first_revision_id,),
        ).fetchone()[0] == "REVOKED"
        assert connection.execute(
            "select count(*) from audit_event where ticket_id = %s and event_type in "
            "('APPROVAL_LEASE_CLAIMED', 'APPROVAL_LEASE_RELEASED', 'APPROVAL_LEASE_REVOKED')",
            (uuid.UUID(proposal_ticket_id),),
        ).fetchone()[0] == 5

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
        "ORDER-DELAY-CANCELLED": "UNSUPPORTED_SCENARIO",
        "ORDER-DELAY-UNPAID": "UNSUPPORTED_SCENARIO",
        "ORDER-DELAY-REFUNDED": "UNSUPPORTED_SCENARIO",
        "ORDER-DELAY-COMPENSATED": "UNSUPPORTED_SCENARIO",
        "ORDER-DELAY-LOW-ALLOWANCE": "FACT_CONFLICT",
        "ORDER-DELAY-RESERVED": "FACT_CONFLICT",
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

    handoff_ticket_id, handoff_projection = create_ambiguous_ticket("human-handoff")
    handoff_clarification_id = handoff_projection["clarification"]["id"]
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        handoff_generation_id, handoff_clarification_request_key = connection.execute(
            "select g.id, c.request_key from agent_processing_generation g "
            "join customer_clarification_request c on c.generation_id = g.id "
            "where g.ticket_id = %s and g.status = 'ACTIVE'",
            (uuid.UUID(handoff_ticket_id),),
        ).fetchone()
        lifecycle_before_handoff = connection.execute(
            "select lifecycle_state from support_ticket where id = %s",
            (uuid.UUID(handoff_ticket_id),),
        ).fetchone()[0]

    handoff_request_id = f"handoff-{uuid.uuid4()}"
    handoff_url = f"{spring_url}/api/customer/tickets/{handoff_ticket_id}/human-handoff"
    handoff_headers = {
        "X-Synthetic-Customer-Id": "customer-demo",
        "Idempotency-Key": handoff_request_id,
    }
    with httpx.Client(timeout=20.0) as client:
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
            headers={"X-Synthetic-Customer-Id": "customer-demo"},
        )
        expect_status(handoff_status, 200)
        restored_handoff = client.get(
            f"{spring_url}/api/customer/tickets/{handoff_ticket_id}",
            headers={"X-Synthetic-Customer-Id": "customer-demo"},
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
                "X-Synthetic-Customer-Id": "customer-demo",
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
        assert connection.execute(
            "select status from agent_processing_generation where id = %s",
            (handoff_generation_id,),
        ).fetchone()[0] == "HANDED_OFF"
        assert connection.execute(
            "select status from customer_clarification_request where id = %s",
            (uuid.UUID(handoff_clarification_id),),
        ).fetchone()[0] == "INVALIDATED"
        assert connection.execute(
            "select count(*) from customer_human_handoff_request where ticket_id = %s",
            (uuid.UUID(handoff_ticket_id),),
        ).fetchone()[0] == 1
        handoff_summary = connection.execute(
            "select investigation_summary from customer_human_handoff_request where ticket_id = %s",
            (uuid.UUID(handoff_ticket_id),),
        ).fetchone()[0]
        assert handoff_summary["generationId"] == str(handoff_generation_id)
        assert isinstance(handoff_summary["facts"], list)
        assert connection.execute(
            "select count(*) from audit_event where ticket_id = %s and event_type in ("
            "'CUSTOMER_HUMAN_HANDOFF_REQUEST_RECORDED', 'CUSTOMER_HUMAN_PREFERENCE_RECORDED', "
            "'AGENT_GENERATION_HANDED_OFF', 'SHARED_SUPPORT_QUEUE_ENTERED')",
            (uuid.UUID(handoff_ticket_id),),
        ).fetchone()[0] == 4
        assert connection.execute(
            "select count(*) from audit_event where ticket_id = %s and ("
            "event_type = 'AGENT_COMMAND_REJECTED_STALE_OR_OUT_OF_SCOPE_GENERATION' or "
            "event_type = 'CLARIFICATION_REJECTED_STALE_CLARIFICATION_GENERATION')",
            (uuid.UUID(handoff_ticket_id),),
        ).fetchone()[0] >= 4
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
    with httpx.Client(timeout=20.0) as client:
        forged_summary = client.post(
            agent_handoff_url,
            headers={**agent_handoff_headers, "Idempotency-Key": f"forged-{uuid.uuid4()}"},
            json={
                **agent_handoff_body,
                "summary": {
                    "conclusionCode": "INVESTIGATION_COULD_NOT_CONTINUE",
                    "facts": [{
                        "type": "ORDER",
                        "value": "raw payload fragment",
                        "evidenceReference": "order:forged",
                    }],
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
            headers={**agent_handoff_headers, "Idempotency-Key": f"late-agent-handoff-{uuid.uuid4()}"},
            json=agent_handoff_body,
        )
        expect_status(stale_new_handoff, 403)
        agent_handoff_public_response = client.get(
            f"{spring_url}/api/customer/tickets/{agent_handoff_ticket_id}",
            headers={"X-Synthetic-Customer-Id": "customer-demo"},
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
            headers={"X-Synthetic-Support-Id": "support-demo"},
        )
        expect_status(agent_handoff_queue_response, 200)
        agent_handoff_queue_item = next(
            item for item in agent_handoff_queue_response.json()
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
        assert connection.execute(
            "select status from agent_processing_generation where id = %s",
            (agent_handoff_generation_id,),
        ).fetchone()[0] == "HANDED_OFF"
        stored_reason, stored_summary = connection.execute(
            "select reason_code, investigation_summary from agent_human_handoff_request "
            "where generation_id = %s and request_id = %s",
            (agent_handoff_generation_id, agent_handoff_request_id),
        ).fetchone()
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
        with httpx.Client(timeout=20.0) as concurrent_client:
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
        concurrent_agent_handoff_statuses = list(executor.map(
            concurrent_agent_handoff, ["FACT_CONFLICT", "UNSUPPORTED_SCENARIO"]
        ))
    assert sorted(concurrent_agent_handoff_statuses) == [202, 403]
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select count(*) from agent_human_handoff_request where ticket_id = %s",
            (uuid.UUID(concurrent_agent_handoff_ticket_id),),
        ).fetchone()[0] == 1
        assert connection.execute(
            "select count(*) from public_message where ticket_id = %s and body = %s",
            (
                uuid.UUID(concurrent_agent_handoff_ticket_id),
                "为确保处理安全，此工单已转由客服继续调查。客服将在此工单中与您联系。",
            ),
        ).fetchone()[0] == 1

    resolved_handoff_request_id = f"resolved-handoff-{uuid.uuid4()}"
    with httpx.Client(timeout=20.0) as client:
        resolved_handoff = client.post(
            f"{spring_url}/api/customer/tickets/{resolved_ticket_id}/human-handoff",
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
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
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                f"{spring_url}/api/customer/tickets/{race_ticket_id}/human-handoff",
                headers={
                    "X-Synthetic-Customer-Id": "customer-demo",
                    "Idempotency-Key": race_handoff_id,
                },
                json={"reasonCode": "CUSTOMER_REQUESTED"},
            )
            return response.status_code

    def reply_during_handoff() -> int:
        race_barrier.wait()
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                f"{spring_url}/api/customer/tickets/{race_ticket_id}/clarifications/"
                f"{race_clarification_id}/replies",
                headers={
                    "X-Synthetic-Customer-Id": "customer-demo",
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
        assert connection.execute(
            "select count(*) from agent_processing_generation where ticket_id = %s and status = 'ACTIVE'",
            (uuid.UUID(race_ticket_id),),
        ).fetchone()[0] == 0
        assert connection.execute(
            "select count(*) from customer_clarification_request where id = %s and status = 'OPEN'",
            (uuid.UUID(race_clarification_id),),
        ).fetchone()[0] == 0

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

    fixed_now = "2026-08-09T14:00:00Z"
    first_warning_headers = {
        "X-Synthetic-Customer-Id": "customer-demo",
        "Idempotency-Key": f"sla-first-warning-{uuid.uuid4()}",
    }
    with httpx.Client(timeout=20.0) as client:
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

    with httpx.Client(timeout=20.0) as client:
        notifications = client.get(
            f"{spring_url}/api/support/sla/notifications",
            headers={"X-Synthetic-Support-Id": "support-demo"},
        )
        expect_status(notifications, 200)
        assert {item["objective"] for item in notifications.json() if item["ticketId"] == ticket_id} == {
            "FIRST_RESPONSE", "RESOLUTION"
        }
        escalations = client.get(
            f"{spring_url}/api/support/escalations",
            headers={"X-Synthetic-Support-Id": "support-demo"},
        )
        expect_status(escalations, 200)
        queue_item = next(item for item in escalations.json() if item["ticketId"] == ticket_id)
        assert queue_item["lifecycleState"] == "WAITING_FOR_EXTERNAL"
        assert queue_item["handlingMode"] == "AGENT"
        assert queue_item["reasonCode"] == "SLA_BREACH"
        assert set(queue_item["breachedObjectives"]) == {"FIRST_RESPONSE", "RESOLUTION"}
        assert not any(field in queue_item for field in (
            "customerId", "orderReference", "description", "messages", "investigationFacts"
        ))
        sla_handoff_request_id = f"sla-handoff-{uuid.uuid4()}"
        sla_handoff = client.post(
            f"{spring_url}/api/customer/tickets/{ticket_id}/human-handoff",
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
                "Idempotency-Key": sla_handoff_request_id,
            },
            json={"reasonCode": "CUSTOMER_REQUESTED"},
        )
        expect_status(sla_handoff, 202)
        shared_queue = client.get(
            f"{spring_url}/api/support/queue",
            headers={"X-Synthetic-Support-Id": "support-demo"},
        )
        expect_status(shared_queue, 200)
        combined_queue_item = next(item for item in shared_queue.json() if item["ticketId"] == ticket_id)
        assert set(combined_queue_item["reasonCodes"]) == {"SLA_BREACH", "CUSTOMER_REQUESTED_HANDOFF"}
        assert combined_queue_item["handlingMode"] == "HUMAN"
        escalations_after_handoff = client.get(
            f"{spring_url}/api/support/escalations",
            headers={"X-Synthetic-Support-Id": "support-demo"},
        )
        expect_status(escalations_after_handoff, 200)
        assert sum(item["ticketId"] == ticket_id for item in escalations_after_handoff.json()) == 1
        denied_queue = client.get(
            f"{spring_url}/api/support/escalations",
            headers={"X-Synthetic-Support-Id": "customer-demo"},
        )
        expect_status(denied_queue, 403)
        unassigned_detail = client.get(
            f"{spring_url}/api/support/tickets/{first_warning_ticket_id}",
            headers={"X-Synthetic-Support-Id": "support-demo"},
        )
        expect_status(unassigned_detail, 404)

    immediate_ticket_id, immediate_projection = create_ambiguous_ticket("sla-resume-boundary")
    immediate_request_id = immediate_projection["clarification"]["id"]
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        connection.execute(
            "update support_ticket set resolution_elapsed_seconds = 86400, "
            "resolution_running_since = null where id = %s",
            (uuid.UUID(immediate_ticket_id),),
        )
    with httpx.Client(timeout=20.0) as client:
        immediate_reply = client.post(
            f"{spring_url}/api/customer/tickets/{immediate_ticket_id}/clarifications/"
            f"{immediate_request_id}/replies",
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
                "Idempotency-Key": f"sla-resume-message-{uuid.uuid4()}",
                "X-Resume-Request-Id": str(uuid.uuid4()),
            },
            json={"answer": "A"},
        )
        expect_status(immediate_reply, 202)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select count(*) from ticket_sla_fact where ticket_id = %s "
            "and objective = 'RESOLUTION' and fact_type = 'BREACH'",
            (uuid.UUID(immediate_ticket_id),),
        ).fetchone()[0] == 1

    time.sleep(1.5)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select count(*) from ticket_sla_fact where ticket_id = %s", (ticket_uuid,)
        ).fetchone()[0] == 4
        assert connection.execute(
            "select count(*) from audit_event where ticket_id = %s and event_type like 'SLA_%%'",
            (ticket_uuid,),
        ).fetchone()[0] == 4
        assert connection.execute(
            "select lifecycle_state, handling_mode, resolution_elapsed_seconds from support_ticket where id = %s",
            (ticket_uuid,),
        ).fetchone() == ("WAITING_FOR_EXTERNAL", "HUMAN", 86399)

    with httpx.Client(timeout=20.0) as client:
        concurrent_state_response = client.post(
            f"{spring_url}/api/customer/tickets",
            headers={
                "X-Synthetic-Customer-Id": "customer-demo",
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
            "update support_ticket set lifecycle_state = 'RESOLVED' where id = %s",
            (concurrent_state_ticket_id,),
        )
    time.sleep(1.25)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select lifecycle_state, resolution_elapsed_seconds from support_ticket where id = %s",
            (concurrent_state_ticket_id,),
        ).fetchone() == ("RESOLVED", 86400)
        assert connection.execute(
            "select count(*) from ticket_sla_fact where ticket_id = %s and objective = 'RESOLUTION'",
            (concurrent_state_ticket_id,),
        ).fetchone()[0] == 2
        connection.execute(
            "update support_ticket set lifecycle_state = 'INVESTIGATING', "
            "resolution_running_since = %s where id = %s",
            (fixed_now, concurrent_state_ticket_id),
        )
    time.sleep(1.25)
    with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
        assert connection.execute(
            "select lifecycle_state, resolution_elapsed_seconds, resolution_running_since is not null "
            "from support_ticket where id = %s",
            (concurrent_state_ticket_id,),
        ).fetchone() == ("INVESTIGATING", 86400, True)
        assert connection.execute(
            "select count(*) from ticket_sla_fact where ticket_id = %s and objective = 'RESOLUTION'",
            (concurrent_state_ticket_id,),
        ).fetchone()[0] == 2
    try:
        with psycopg.connect(os.environ["SPRING_DATABASE_URI"]) as connection:
            connection.execute(
                "update support_ticket set resolution_elapsed_seconds = 0 where id = %s",
                (concurrent_state_ticket_id,),
            )
        raise AssertionError("resolution elapsed time unexpectedly reset on reopen")
    except psycopg.errors.CheckViolation as error:
        assert error.diag.constraint_name == "resolution_elapsed_seconds_monotonic"

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
        "human_handoff_ticket_id": handoff_ticket_id,
        "agent_handoff_ticket_id": agent_handoff_ticket_id,
        "concurrent_agent_handoff_statuses": concurrent_agent_handoff_statuses,
        "handoff_reply_race_statuses": race_statuses,
        "clarification_resume_status": resume_status,
        "sla_fact_count": len(sla_facts),
        "sla_resume_immediate": True,
        "concurrent_replays": 7,
        "approval_claim_statuses": sorted(response.status_code for response in claim_responses),
        "approval_lease_versions": [1, 2, 3],
        "approval_replacement_revoked": True,
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"smoke failed: {error}", file=sys.stderr)
        raise
