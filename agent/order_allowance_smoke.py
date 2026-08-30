# pyright: reportOptionalSubscript=false
"""#165: 合成订单上的真实 HTTP / PostgreSQL 额度仲裁, 不调用模型。"""

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import httpx
import psycopg

from smoke import expect_status, login_human


class Acceptance:
    def __init__(self, support: httpx.Client, approver: httpx.Client):
        self.spring = os.environ["SPRING_INTERNAL_URL"]
        self.database = os.environ["SPRING_DATABASE_URI"]
        self.support = support
        self.approver = approver
        self.executor = {"Authorization": f"Bearer {os.environ['EXECUTOR_MACHINE_TOKEN']}"}

    def tickets(self, order: str) -> list[str]:
        tickets = [str(uuid.uuid4()), str(uuid.uuid4())]
        with psycopg.connect(self.database) as connection:
            for ticket, kind in zip(tickets, ("LOGISTICS_DELAY", "DUPLICATE_CHARGE"), strict=True):
                connection.execute(
                    "insert into support_ticket (id, customer_id, order_reference, description, "
                    "issue_kind, lifecycle_state, handling_mode, created_at, first_responded_at, "
                    "resolution_running_since) values (%s, 'customer-demo', %s, %s, %s, "
                    "'INVESTIGATING', 'HUMAN', '2026-08-09T14:00Z', '2026-08-09T14:00Z', '2026-08-09T14:00Z')",
                    (ticket, order, f"仅该工单可见的对话标记-{ticket}", kind),
                )
                connection.execute(
                    "insert into support_assignment (id, ticket_id, support_id, status, assigned_at) "
                    "values (%s, %s, 'support-demo', 'ACTIVE', '2026-08-09T14:00Z')",
                    (uuid.uuid4(), ticket),
                )
        return tickets

    def proposal(self, ticket: str, expected: int = 201) -> dict:
        request = str(uuid.uuid4())
        url = f"{self.spring}/api/support/workbench/tickets/{ticket}/compensation-proposals"
        body = {
            "schema": "support-workbench-v2",
            "planCode": "SIMULATED_PARTIAL_REFUND",
            "reasonCode": "LOGISTICS_DELAY",
        }
        response = self.support.post(url, headers={"Idempotency-Key": request}, json=body)
        expect_status(response, expected)
        if expected == 201:
            # 丢弃首次响应后以原请求重放, 仍只有同一版本。
            replay = self.support.post(url, headers={"Idempotency-Key": request}, json=body)
            expect_status(replay, 200)
            assert replay.json()["proposalRevisionId"] == response.json()["proposalRevisionId"]
        return response.json()

    def view(self, proposal: dict) -> tuple[str, dict, dict]:
        revision = proposal["proposalRevisionId"]
        base = f"{self.spring}/api/approver/compensation-proposals/{revision}"
        claim = self.approver.post(
            base + "/claims",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"requestedLeaseSeconds": 900},
        )
        expect_status(claim, 201)
        headers = {
            "X-Approval-Lease-Token": claim.json()["leaseToken"],
            "X-Approval-Lease-Version": str(claim.json()["leaseVersion"]),
            "Idempotency-Key": str(uuid.uuid4()),
        }
        view = self.approver.get(base + "/approval-view", headers=headers)
        expect_status(view, 200)
        assert "仅该工单可见的对话标记" not in view.text
        body = {
            "proposalRevision": proposal["proposalRevision"],
            "contentDigest": view.json()["contentDigest"],
        }
        snapshot = view.json()["evidenceSnapshot"]
        assert Decimal(snapshot["totalAvailableCompensationAmount"]) - Decimal(
            snapshot["activeReservationAmount"]
        ) == Decimal(snapshot["remainingAvailableCompensationAmount"])
        return base, headers, body

    def approve(self, view: tuple[str, dict, dict], expected: int = 200) -> dict:
        base, headers, body = view
        response = self.approver.post(base + "/approve", headers=headers, json=body)
        expect_status(response, expected)
        if expected == 200:
            replay = self.approver.post(base + "/approve", headers=headers, json=body)
            expect_status(replay, 200)
            assert replay.json()["executionId"] == response.json()["executionId"]
        return response.json()

    def allowance(self, order: str, total: str, active: str, consumed: str) -> None:
        with psycopg.connect(self.database) as connection:
            row = connection.execute(
                "select total_available_compensation_amount, active_reservation_amount, consumed_amount "
                "from order_compensation_allowance where order_reference = %s",
                (order,),
            ).fetchone()
            assert row == tuple(map(Decimal, (total, active, consumed))), row

    def execute(self, approved: dict, scenario: str) -> tuple[str, dict]:
        execution = approved["executionId"]
        base = f"{self.spring}/internal/compensation-executions/{execution}"
        claim = self.support.post(
            base + "/claims", headers={**self.executor, "Idempotency-Key": str(uuid.uuid4())}
        )
        expect_status(claim, 201)
        bound = {
            key: claim.json()[key] for key in ("attemptId", "idempotencyKey", "parameterDigest")
        }
        provider_url = f"{self.spring}/internal/compensation-simulator/{execution}/executions"
        headers = {
            **self.executor,
            "Idempotency-Key": bound["idempotencyKey"],
            "X-Simulation-Scenario": scenario,
        }
        payload = {"parameterDigest": bound["parameterDigest"], "amount": "26.80"}
        expected = 504 if scenario == "AFTER_EFFECT_RESPONSE_LOST" else 200
        expect_status(self.support.post(provider_url, headers=headers, json=payload), expected)
        # 供应商响应丢失/重复请求不产生第二次副作用。
        expect_status(self.support.post(provider_url, headers=headers, json=payload), expected)
        action = {
            "SUCCESS": "success",
            "BEFORE_EFFECT_FAILURE": "failures",
            "AFTER_EFFECT_RESPONSE_LOST": "unknown",
        }[scenario]
        response = self.support.post(
            base + "/" + action,
            headers={**self.executor, "Idempotency-Key": str(uuid.uuid4())},
            json=bound,
        )
        expect_status(response, 200)
        return execution, bound

    def race_and_response_loss(self) -> None:
        order = "ORDER-ALLOW165-RACE"
        tickets = self.tickets(order)
        barrier = threading.Barrier(2)

        def submit(ticket: str) -> dict:
            barrier.wait()
            return self.proposal(ticket)

        with ThreadPoolExecutor(max_workers=2) as pool:
            proposals = list(pool.map(submit, tickets))
        assert proposals[0]["proposalRevisionId"] != proposals[1]["proposalRevisionId"]
        self.allowance(order, "30.00", "0.00", "0.00")
        with psycopg.connect(self.database) as connection:
            assert connection.execute(
                "select pending_proposal_amount from order_compensation_allowance where order_reference = %s",
                (order,),
            ).fetchone() == (Decimal("53.60"),)
        views = [self.view(proposal) for proposal in proposals]
        barrier = threading.Barrier(2)

        def decide(view: tuple[str, dict, dict]) -> httpx.Response:
            barrier.wait()
            return self.approver.post(view[0] + "/approve", headers=view[1], json=view[2])

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(decide, views))
        assert sorted(response.status_code for response in responses) == [200, 409]
        winner = next(
            index for index, response in enumerate(responses) if response.status_code == 200
        )
        approved = self.approve(views[winner])
        self.allowance(order, "30.00", "26.80", "0.00")
        execution, bound = self.execute(approved, "AFTER_EFFECT_RESPONSE_LOST")
        self.allowance(order, "30.00", "26.80", "0.00")
        self.proposal(tickets[1 - winner], 409)
        query = self.support.get(
            f"{self.spring}/internal/compensation-simulator/{execution}/reconciliation",
            headers={**self.executor, "Idempotency-Key": bound["idempotencyKey"]},
        )
        expect_status(query, 200)
        assert query.json()["outcome"] == "FOUND"
        url = f"{self.spring}/internal/compensation-executions/{execution}/reconciliations"
        headers = {**self.executor, "Idempotency-Key": str(uuid.uuid4())}
        for _ in range(2):
            reconciled = self.support.post(
                url,
                headers=headers,
                json={key: query.json()[key] for key in ("queryId", "outcome", "resultReference")},
            )
            expect_status(reconciled, 200)
            assert reconciled.json()["status"] == "SUCCEEDED"
        self.allowance(order, "3.20", "0.00", "26.80")
        self.proposal(tickets[1 - winner], 409)
        with psycopg.connect(self.database) as connection:
            assert connection.execute(
                "select count(*) from simulated_partial_refund where execution_id = %s",
                (execution,),
            ).fetchone() == (1,)
        print(
            "#165 并发提案=2成功；并发审批=1成功/1冲突；响应丢失及重放后副作用=1，已消费=26.80/30.00"
        )

    def failure_and_combination(self) -> None:
        order = "ORDER-ALLOW165-FAILURE"
        tickets = self.tickets(order)
        first = self.view(self.proposal(tickets[0]))
        second = self.view(self.proposal(tickets[1]))
        approved = self.approve(first)
        self.approve(second, 409)
        self.execute(approved, "BEFORE_EFFECT_FAILURE")
        self.allowance(order, "30.00", "0.00", "0.00")
        refreshed = self.view(self.proposal(tickets[1]))
        rejected = self.approver.post(
            refreshed[0] + "/reject",
            headers=refreshed[1],
            json={**refreshed[2], "internalReason": "合成验收驳回"},
        )
        expect_status(rejected, 200)
        self.allowance(order, "30.00", "0.00", "0.00")
        self.approve(self.view(self.proposal(tickets[1])))
        self.allowance(order, "30.00", "26.80", "0.00")

        order = "ORDER-ALLOW165-COMBINATION"
        tickets = self.tickets(order)
        view = self.view(self.proposal(tickets[0]))
        barrier = threading.Barrier(2)

        def resubmit() -> int:
            barrier.wait()
            return self.support.post(
                f"{self.spring}/api/support/workbench/tickets/{tickets[0]}/compensation-proposals",
                headers={"Idempotency-Key": str(uuid.uuid4())},
                json={
                    "schema": "support-workbench-v2",
                    "planCode": "SIMULATED_PARTIAL_REFUND",
                    "reasonCode": "LOGISTICS_DELAY",
                },
            ).status_code

        def approve_current() -> dict:
            barrier.wait()
            return self.approve(view)

        with ThreadPoolExecutor(max_workers=2) as pool:
            resubmission = pool.submit(resubmit)
            approval = pool.submit(approve_current)
            first = approval.result(timeout=30)
            assert resubmission.result(timeout=30) in (201, 409)
        self.execute(first, "SUCCESS")
        self.allowance(order, "33.20", "0.00", "26.80")
        second = self.approve(self.view(self.proposal(tickets[1])))
        self.allowance(order, "33.20", "26.80", "26.80")
        self.execute(second, "SUCCESS")
        self.allowance(order, "6.40", "0.00", "53.60")
        extra = self.tickets(order)[0]
        self.proposal(extra, 409)
        denied = self.approver.get(
            f"{self.spring}/api/support/workbench/tickets/{extra}/compensation-options"
        )
        expect_status(denied, 403)
        with httpx.Client(timeout=30) as unassigned:
            login_human(
                unassigned,
                self.spring,
                "internal-demo",
                ["SUPPORT_WORKBENCH_ACCESS", "APPROVAL_WORKBENCH_ACCESS", "KNOWLEDGE_READ_ACCESS"],
            )
            denied = unassigned.get(
                f"{self.spring}/api/support/workbench/tickets/{extra}/compensation-options"
            )
            expect_status(denied, 404)
        print("#165 确认失败释放=26.80；驳回不占额；合法组合=2×26.80，成功后剩余=6.40/60.00")

    def storage_race(self) -> None:
        barrier = threading.Barrier(2)
        order = "ORDER-ALLOW165-STORAGE"

        def reserve(_: int) -> str:
            try:
                with psycopg.connect(self.database) as connection:
                    barrier.wait()
                    connection.execute(
                        "insert into compensation_reservation (id, order_reference, amount, status, created_at) values (%s, %s, 20.00, 'ACTIVE', clock_timestamp())",
                        (uuid.uuid4(), order),
                    )
                return "ACCEPTED"
            except psycopg.errors.CheckViolation as error:
                assert error.diag.constraint_name == "compensation_reservation_capacity"
                return "CAPACITY_CONFLICT"

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(reserve, range(2))) == ["ACCEPTED", "CAPACITY_CONFLICT"]
        with psycopg.connect(self.database) as connection:
            connection.execute(
                "update compensation_reservation set status = 'CONSUMED' where order_reference = %s",
                (order,),
            )
        self.allowance(order, "10.00", "0.00", "20.00")
        print("#165 PostgreSQL 并发预占=1成功/1约束冲突；已消费不恢复额度")

    def expiry_lock_order(self) -> None:
        order = "ORDER-ALLOW165-EXPIRY"
        tickets = self.tickets(order)
        revision = uuid.uuid4()
        with psycopg.connect(self.database) as connection:
            connection.execute(
                "insert into compensation_proposal_revision "
                "(id, proposal_id, revision_number, ticket_id, order_reference, delay_hours, "
                "delay_seconds, compensation_method, amount, reason_code, evidence_references, "
                "policy_version, content_digest, status, created_at, expires_at) "
                "values (%s, %s, 1, %s, %s, 80, 288000, 'SIMULATED_PARTIAL_REFUND', 26.80, "
                "'LOGISTICS_DELAY', '[]', 'delay-policy-v1', %s, 'PENDING_APPROVAL', "
                "'2026-08-08T13:00Z', '2026-08-09T13:00Z')",
                (revision, uuid.uuid4(), tickets[0], order, revision.hex * 2),
            )
        # 在订单锁被持有时, 到期 claim 必须等在订单锁前, 不能先持有提案行。
        with ThreadPoolExecutor(max_workers=1) as pool:
            with psycopg.connect(self.database) as connection:
                connection.execute(
                    "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (order + "\nCOMPENSATION_ALLOWANCE",),
                )
                claim = pool.submit(
                    self.approver.post,
                    f"{self.spring}/api/approver/compensation-proposals/{revision}/claims",
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                    json={"requestedLeaseSeconds": 900},
                )
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    waiting = connection.execute(
                        "select count(*) from pg_locks held join pg_locks waiting "
                        "on held.locktype = waiting.locktype and held.classid = waiting.classid "
                        "and held.objid = waiting.objid and held.objsubid = waiting.objsubid "
                        "where held.pid = pg_backend_pid() and held.locktype = 'advisory' "
                        "and held.granted and not waiting.granted"
                    ).fetchone()[0]
                    if waiting:
                        break
                    time.sleep(0.02)
                else:
                    raise AssertionError("到期 claim 未到达订单锁屏障")
                connection.execute(
                    "select id from compensation_proposal_revision where id = %s for update nowait",
                    (revision,),
                )
            expect_status(claim.result(timeout=10), 410)
        # 队列清理遇到忙订单跳过; 释放订单后下次查询完成到期状态更新。
        second = uuid.uuid4()
        with psycopg.connect(self.database) as connection:
            connection.execute(
                "insert into compensation_proposal_revision "
                "select %s, %s, 1, %s, order_reference, null, delay_hours, delay_seconds, "
                "compensation_method, amount, reason_code, evidence_references, policy_version, "
                "content_digest, 'PENDING_APPROVAL', created_at, expires_at "
                "from compensation_proposal_revision where id = %s",
                (second, uuid.uuid4(), tickets[1], revision),
            )
        with (
            ThreadPoolExecutor(max_workers=1) as pool,
            psycopg.connect(self.database) as connection,
        ):
            connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (order + "\nCOMPENSATION_ALLOWANCE",),
            )
            queue = pool.submit(
                self.approver.get, f"{self.spring}/api/approver/compensation-proposals"
            )
            expect_status(queue.result(timeout=5), 200)
            assert connection.execute(
                "select status from compensation_proposal_revision where id = %s for update nowait",
                (second,),
            ).fetchone() == ("PENDING_APPROVAL",)
        expect_status(self.approver.get(f"{self.spring}/api/approver/compensation-proposals"), 200)
        with psycopg.connect(self.database) as connection:
            assert connection.execute(
                "select status from compensation_proposal_revision where id = %s", (second,)
            ).fetchone() == ("EXPIRED",)
        print("#165 到期 claim 在订单锁前等待；队列跳过忙订单且下次完成过期；无提案行/订单锁反序")


def main() -> None:
    with httpx.Client(timeout=30) as support, httpx.Client(timeout=30) as approver:
        spring = os.environ["SPRING_INTERNAL_URL"]
        login_human(
            support, spring, "support-demo", ["SUPPORT_WORKBENCH_ACCESS", "KNOWLEDGE_READ_ACCESS"]
        )
        login_human(
            approver,
            spring,
            "approver-demo",
            ["APPROVAL_WORKBENCH_ACCESS", "KNOWLEDGE_READ_ACCESS"],
        )
        acceptance = Acceptance(support, approver)
        acceptance.race_and_response_loss()
        acceptance.failure_and_combination()
        acceptance.storage_race()
        acceptance.expiry_lock_order()
    print("Issue #165 订单额度仲裁验收 PASS：5 个合成订单，无模型调用")


if __name__ == "__main__":
    main()
