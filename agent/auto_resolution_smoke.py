# pyright: reportOptionalSubscript=false
"""#162: 真实 HTTP、PostgreSQL 与 Spring 调度; 时钟由外层重建后端推进。"""

import argparse
import datetime
import os
import time
import uuid
from pathlib import Path

import httpx
import psycopg

from smoke import collect_investigation_facts, evidence_sufficiency, expect_status, login_human

START = datetime.datetime(2026, 8, 9, 14, tzinfo=datetime.UTC)
DUE = START + datetime.timedelta(minutes=5)
CASES = (
    "success",
    "reply",
    "cancel",
    "pending",
    "compensation",
    "proposal",
    "human",
    "facts",
    "generation",
    "stream",
    "exact-race",
    "completed-check",
)
BLOCKED = ("pending", "compensation", "proposal", "human", "facts", "generation", "stream")


class Acceptance:
    def __init__(self, namespace: str):
        self.namespace = uuid.UUID(namespace)
        self.spring = os.environ["SPRING_INTERNAL_URL"]
        self.database = os.environ["SPRING_DATABASE_URI"]
        self.fixture_database = os.environ["SPRING_FIXTURE_DATABASE_URI"]

    def ticket(self, case: str) -> uuid.UUID:
        # 相同截止时刻按 UUID 排序: 屏障票先于精确截止回复票。
        if case == "success":
            return uuid.UUID(f"00000000-0000-0000-0000-{self.namespace.hex[:12]}")
        if case == "exact-race":
            return uuid.UUID(f"ffffffff-ffff-ffff-ffff-{self.namespace.hex[-12:]}")
        return uuid.uuid5(self.namespace, f"ticket:{case}")

    def generation(self, case: str) -> uuid.UUID:
        return uuid.uuid5(self.namespace, f"generation:{case}")

    def order(self, case: str) -> str:
        return f"ORDER-AUTO162-{self.namespace.hex.upper()}-{case.upper()}"

    def agent_headers(self, case: str, operation: str, request: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {os.environ['AGENT_MACHINE_TOKEN']}",
            "X-Agent-Generation-Id": str(self.generation(case)),
            "X-Agent-Operation": operation,
            "Idempotency-Key": f"auto162:{case}:{request}",
        }

    def row(self, case: str):
        with psycopg.connect(self.database) as connection:
            return connection.execute(
                "select t.lifecycle_state, a.status, a.created_at, a.due_at, "
                "t.resolved_at, t.close_due_at from support_ticket t "
                "left join ticket_auto_resolution a on a.ticket_id = t.id where t.id = %s",
                (self.ticket(case),),
            ).fetchone()

    def wait_status(self, case: str, status: str) -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.row(case)[1] == status:
                return
            time.sleep(0.1)
        raise AssertionError(f"{case}: expected {status}, got {self.row(case)}")

    def prepare(self) -> None:
        for case in (*CASES, "partial"):
            ticket_id = self.ticket(case)
            generation_id = self.generation(case)
            with psycopg.connect(self.database) as connection:
                connection.execute(
                    "insert into support_ticket (id, customer_id, order_reference, description, "
                    "issue_kind, lifecycle_state, handling_mode, created_at, first_responded_at, "
                    "resolution_running_since) values (%s, 'customer-demo', %s, '请解释物流状态', "
                    "'LOGISTICS_DELAY', 'INVESTIGATING', 'AGENT', %s, %s, %s)",
                    (ticket_id, self.order(case), START, START, START),
                )
                connection.execute(
                    "insert into agent_processing_generation "
                    "(id, ticket_id, generation_number, thread_id, status, created_at) "
                    "values (%s, %s, 1, %s, 'ACTIVE', %s)",
                    (generation_id, ticket_id, uuid.uuid4(), START),
                )
                connection.execute(
                    "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) "
                    "values (%s, %s, 1, 'CUSTOMER', '请解释物流状态', %s)",
                    (uuid.uuid4(), ticket_id, START),
                )
            with httpx.Client(timeout=20) as client:
                facts = collect_investigation_facts(
                    client,
                    self.spring,
                    ticket_id,
                    generation_id,
                    self.agent_headers(case, "USE_INVESTIGATION_CAPABILITY", "facts"),
                )
                body = (
                    f"经核验，订单 {self.order(case)} 的物流延迟不足 24 小时，当前不符合补偿条件。"
                )
                base = (
                    f"{self.spring}/internal/agent/tickets/{ticket_id}/generations/{generation_id}"
                )
                for index, payload in enumerate(
                    (
                        {"type": "STREAM_STARTED"},
                        {"type": "CONTENT_DELTA", "chunkIndex": 0, "delta": body},
                    )
                ):
                    expect_status(
                        client.post(
                            f"{base}/public-reply-events",
                            headers=self.agent_headers(
                                case, "PUBLISH_PUBLIC_REPLY_EVENT", f"stream:{index}"
                            ),
                            json=payload,
                        ),
                        202,
                    )
                assert self.row(case)[1] is None, "streamed text alone must not create a candidate"
                if case == "partial":
                    continue
                conclusion = {
                    "compensationRequired": False,
                    "reasonCode": "DELAY_UNDER_24_HOURS",
                    "delayHours": facts["delayHours"],
                    "delaySeconds": facts["delaySeconds"],
                    "orderReference": self.order(case),
                    "evidenceRefs": facts["evidenceRefs"],
                    **evidence_sufficiency(self.order(case)),
                    "customerReply": {
                        "schemaVersion": "customer-reply-v1",
                        "body": body,
                        "intent": "NO_COMPENSATION_RESOLUTION",
                        "evidenceRefs": facts["evidenceRefs"],
                        "escalationRequired": False,
                        "referencedOrder": self.order(case),
                    },
                }
                expect_status(
                    client.post(
                        f"{base}/conclusions",
                        headers=self.agent_headers(
                            case, "SUBMIT_INVESTIGATION_CONCLUSION", "conclusion"
                        ),
                        json=conclusion,
                    ),
                    200,
                )
                assert self.row(case)[:4] == ("INVESTIGATING", "PENDING", START, DUE)
            with psycopg.connect(self.database) as connection:
                assert connection.execute(
                    "select m.sent_at, s.status, m.body = s.body from ticket_auto_resolution a "
                    "join public_message m on m.id = a.reply_message_id "
                    "join agent_public_reply_stream s on s.generation_id = a.generation_id "
                    "where a.ticket_id = %s",
                    (ticket_id,),
                ).fetchone() == (START, "COMPLETED", True)
                if case == "completed-check":
                    assert connection.execute(
                        "select scenario from ticket_auto_resolution where ticket_id = %s",
                        (ticket_id,),
                    ).fetchone() == ("COMPLETED_NON_COMPENSATION_CHECK",)
                events = [
                    row[0]
                    for row in connection.execute(
                        "select event_type from customer_public_event "
                        "where ticket_id = %s order by sequence",
                        (ticket_id,),
                    ).fetchall()
                ]
                assert (
                    events.index("AGENT_REPLY_COMPLETED")
                    < events.index("PUBLIC_MESSAGE_APPENDED")
                    < events.index("AUTO_RESOLUTION_CHANGED")
                )
        self.invalidate_candidates()

    def invalidate_candidates(self) -> None:
        with psycopg.connect(self.fixture_database) as connection:
            connection.execute(
                "insert into synthetic_pending_action (id, order_reference, action_type, action_state) "
                "values (%s, %s, 'INFORMATION_CHECK', 'READY')",
                (uuid.uuid4(), self.order("pending")),
            )
            connection.execute(
                "update investigation_fact set conflict_status = 'CONFLICT' where generation_id = %s",
                (self.generation("facts"),),
            )
        with psycopg.connect(self.database) as connection:
            connection.execute(
                "insert into compensation_reservation (id, order_reference, amount, status, created_at) "
                "values (%s, %s, 1.00, 'ACTIVE', %s)",
                (uuid.uuid4(), self.order("compensation"), START),
            )
            connection.execute(
                "insert into compensation_proposal_revision (id, proposal_id, revision_number, "
                "ticket_id, order_reference, generation_id, delay_hours, delay_seconds, "
                "compensation_method, amount, reason_code, evidence_references, policy_version, "
                "content_digest, status, created_at, expires_at) "
                "values (%s, %s, 1, %s, %s, %s, 80, 288000, 'COUPON', 1.00, 'LOGISTICS_DELAY', "
                "'[]'::jsonb, 'delay-policy-v1', %s, 'PENDING_APPROVAL', %s, %s)",
                (
                    uuid.uuid4(),
                    uuid.uuid4(),
                    self.ticket("proposal"),
                    self.order("proposal"),
                    self.generation("proposal"),
                    "a" * 64,
                    START,
                    START + datetime.timedelta(hours=24),
                ),
            )
            connection.execute(
                "update support_ticket set handling_mode = 'HUMAN' where id = %s",
                (self.ticket("human"),),
            )
            connection.execute(
                "insert into agent_processing_generation "
                "(id, ticket_id, generation_number, thread_id, status, created_at) "
                "values (%s, %s, 2, %s, 'ACTIVE', %s)",
                (uuid.uuid4(), self.ticket("generation"), uuid.uuid4(), START),
            )
            connection.execute(
                "update agent_public_reply_stream set status = 'FAILED' where generation_id = %s",
                (self.generation("stream"),),
            )

    def before_due(self) -> None:
        for case in CASES:
            assert self.row(case)[:4] == ("INVESTIGATING", "PENDING", START, DUE)
        with httpx.Client(timeout=20) as client:
            login_human(client, self.spring, "customer-demo", ["CUSTOMER_HELP_ACCESS"])
            snapshot = client.get(f"{self.spring}/api/customer/v2/tickets/{self.ticket('success')}")
            expect_status(snapshot, 200)
            public = snapshot.json()["autoResolution"]
            assert public["status"] == "PENDING"
            assert datetime.datetime.fromisoformat(public["dueAt"]) == DUE
            expect_status(
                client.post(
                    f"{self.spring}/api/customer/v2/tickets/{self.ticket('reply')}/messages",
                    headers={"Idempotency-Key": f"auto162:{self.namespace}:reply"},
                    json={
                        "schema": "public-conversation-v2",
                        "message": "不同意本次结论，仍需帮助",
                    },
                ),
                202,
            )
            expect_status(
                client.post(
                    f"{self.spring}/api/customer/tickets/{self.ticket('cancel')}/auto-resolution/cancel",
                    json={"candidateDueAt": DUE.isoformat(), "candidateGeneration": 2},
                ),
                409,
            )
            assert self.row("cancel")[1] == "PENDING"
            for _ in range(2):
                expect_status(
                    client.post(
                        f"{self.spring}/api/customer/tickets/{self.ticket('cancel')}/auto-resolution/cancel",
                        json={"candidateDueAt": DUE.isoformat(), "candidateGeneration": 1},
                    ),
                    204,
                )
        assert self.row("reply")[1] == "CANCELLED"
        assert self.row("cancel")[1] == "CANCELLED"
        with psycopg.connect(self.database) as connection:
            for case in ("reply", "cancel"):
                assert connection.execute(
                    "select count(*) from customer_public_event where ticket_id = %s "
                    "and event_type = 'AUTO_RESOLUTION_CHANGED' "
                    "and payload->'autoResolution'->>'status' = 'CANCELLED'",
                    (self.ticket(case),),
                ).fetchone() == (1,)
            assert connection.execute(
                "select max(sent_at) from public_message where ticket_id = %s and author = 'CUSTOMER'",
                (self.ticket("reply"),),
            ).fetchone() == (DUE - datetime.timedelta(seconds=1),)

    def exact_race(self, marker_directory: str) -> None:
        markers = Path(marker_directory)
        with psycopg.connect(self.database) as barrier:
            barrier.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{self.ticket('success')}\nBUSINESS_AUTHORITY",),
            )
            holder_pid = barrier.execute("select pg_backend_pid()").fetchone()[0]
            assert self.row("success")[1] == "PENDING"
            assert self.row("exact-race")[1] == "PENDING"
            (markers / "ready").write_text("barrier-held", encoding="utf-8")
            deadline = time.monotonic() + 90
            while not (markers / "due").exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            assert (markers / "due").exists(), "backend did not reach the exact deadline"
            # 先证明调度已选择到期列表并在首票等待, 再提交客户消息。
            deadline = time.monotonic() + 20
            scheduler_waiting = False
            while time.monotonic() < deadline:
                with psycopg.connect(self.database) as observation:
                    scheduler_waiting = observation.execute(
                        "select exists(select 1 from pg_stat_activity "
                        "where %s = any(pg_blocking_pids(pid)) and wait_event_type = 'Lock')",
                        (holder_pid,),
                    ).fetchone()[0]
                if scheduler_waiting:
                    break
                time.sleep(0.1)
            assert scheduler_waiting, "deadline scheduler never waited on the barrier ticket"
            with httpx.Client(timeout=20) as client:
                login_human(client, self.spring, "customer-demo", ["CUSTOMER_HELP_ACCESS"])
                expect_status(
                    client.post(
                        f"{self.spring}/api/customer/v2/tickets/{self.ticket('exact-race')}/messages",
                        headers={"Idempotency-Key": f"auto162:{self.namespace}:exact-race"},
                        json={
                            "schema": "public-conversation-v2",
                            "message": "不同意本次结论，仍需帮助",
                        },
                    ),
                    202,
                )
            assert self.row("exact-race")[1] == "CANCELLED"
            with psycopg.connect(self.database) as observation:
                assert observation.execute(
                    "select max(sent_at) from public_message "
                    "where ticket_id = %s and author = 'CUSTOMER'",
                    (self.ticket("exact-race"),),
                ).fetchone() == (DUE,)
        # 退出事务后释放屏障, 让同一份已选取列表继续处理。
        self.wait_status("success", "RESOLVED")
        assert self.row("exact-race")[:2] == ("INVESTIGATING", "CANCELLED")
        (markers / "done").write_text("exact-deadline-reply-accepted", encoding="utf-8")

    def expired(self) -> None:
        for case in ("success", "completed-check"):
            self.wait_status(case, "RESOLVED")
            assert self.row(case) == (
                "RESOLVED",
                "RESOLVED",
                START,
                DUE,
                DUE,
                DUE + datetime.timedelta(hours=72),
            )
            self.assert_unique_resolution(case)
        for case in BLOCKED:
            self.wait_status(case, "REEVALUATING")
            assert self.row(case)[0] == "INVESTIGATING"
        for case in ("reply", "cancel", "exact-race"):
            assert self.row(case)[:2] == ("INVESTIGATING", "CANCELLED")
        assert self.row("partial")[:2] == ("INVESTIGATING", None)
        self.assert_unique_resolution()
        with psycopg.connect(self.database) as connection:
            for case in (*BLOCKED, "reply", "cancel", "exact-race", "partial"):
                assert connection.execute(
                    "select count(*) from customer_public_event "
                    "where ticket_id = %s and event_type = 'TICKET_RESOLVED'",
                    (self.ticket(case),),
                ).fetchone() == (0,)

    def assert_unique_resolution(self, case: str = "success") -> None:
        with psycopg.connect(self.database) as connection:
            assert connection.execute(
                "select count(*) from customer_public_event "
                "where ticket_id = %s and event_type = 'TICKET_RESOLVED'",
                (self.ticket(case),),
            ).fetchone() == (1,)
            assert connection.execute(
                "select count(*) from audit_event "
                "where ticket_id = %s and event_type = 'AUTO_RESOLUTION_RESOLVED'",
                (self.ticket(case),),
            ).fetchone() == (1,)

    def before_close(self) -> None:
        assert self.row("success")[0] == "RESOLVED"
        assert self.row("success")[5] == DUE + datetime.timedelta(hours=72)
        self.assert_unique_resolution()

    def closed(self) -> None:
        deadline = time.monotonic() + 20
        while self.row("success")[0] != "CLOSED" and time.monotonic() < deadline:
            time.sleep(0.1)
        assert self.row("success")[0] == "CLOSED"
        self.assert_unique_resolution()
        with psycopg.connect(self.database) as connection:
            assert connection.execute(
                "select count(*) from customer_public_event "
                "where ticket_id = %s and event_type = 'TICKET_CLOSED'",
                (self.ticket("success"),),
            ).fetchone() == (1,)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=("prepare", "before_due", "exact_race", "expired", "before_close", "closed"),
    )
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--marker-directory")
    args = parser.parse_args()
    acceptance = Acceptance(args.namespace)
    if args.phase == "exact_race":
        if not args.marker_directory:
            parser.error("exact_race requires --marker-directory")
        acceptance.exact_race(args.marker_directory)
    else:
        getattr(acceptance, args.phase)()
    print(f"Issue #162 持久化验收通过：{args.phase}")


if __name__ == "__main__":
    main()
