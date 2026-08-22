import datetime
import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg

PROPOSAL_BOUNDARY_REVISION = "68000000-0000-0000-0000-000000000032"
LEASE_BOUNDARY_REVISION = "68000000-0000-0000-0000-000000000033"
BLOCKER_LEASE = "68000000-0000-0000-0000-000000000051"


def login_approver(client: httpx.Client, spring_url: str) -> None:
    csrf_response = client.get(f"{spring_url}/api/auth/csrf")
    assert csrf_response.status_code == 200, csrf_response.text
    csrf = csrf_response.json()
    login = client.post(
        f"{spring_url}/api/auth/login",
        headers={csrf["headerName"]: csrf["token"]},
        data={"username": "approver-demo", "password": "local-demo-password"},
    )
    assert login.status_code == 204, login.text


def main() -> None:
    spring_url = os.environ["SPRING_INTERNAL_URL"]
    spring_database_uri = os.environ["SPRING_DATABASE_URI"]
    approver_headers = {"X-Synthetic-Approver-Id": "approver-demo"}

    with psycopg.connect(spring_database_uri, autocommit=True) as connection:
        boundary_row = connection.execute(
            "select expires_at from compensation_proposal_revision where id = %s",
            (PROPOSAL_BOUNDARY_REVISION,),
        ).fetchone()
        assert boundary_row is not None
        boundary_at = boundary_row[0]

    lock_connection = psycopg.connect(spring_database_uri)
    try:
        blocker_pid_row = lock_connection.execute("select pg_backend_pid()").fetchone()
        assert blocker_pid_row is not None
        blocker_pid = blocker_pid_row[0]
        lock_connection.execute(
            "select 1 from approval_lease where id = %s for update", (BLOCKER_LEASE,)
        )

        def read_queue() -> httpx.Response:
            with httpx.Client(timeout=20.0) as client:
                login_approver(client, spring_url)
                return client.get(
                    f"{spring_url}/api/approver/compensation-proposals",
                    headers=approver_headers,
                )

        with ThreadPoolExecutor(max_workers=1) as executor:
            response_future = executor.submit(read_queue)
            lock_wait_observed = False
            try:
                with psycopg.connect(spring_database_uri, autocommit=True) as observer:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        waiting_row = observer.execute(
                            "select count(*) from pg_stat_activity "
                            "where datname = current_database() and usename = current_user "
                            "and state = 'active' and wait_event_type = 'Lock' "
                            "and query like 'update compensation_proposal_revision set status%%' "
                            "and %s = any(pg_blocking_pids(pid))",
                            (blocker_pid,),
                        ).fetchone()
                        # The outer proposal UPDATE remains visible while its V9 AFTER trigger
                        # waits to revoke the ACTIVE lease row held by blocker_pid.
                        assert waiting_row is not None
                        if waiting_row[0]:
                            lock_wait_observed = True
                            break
                        time.sleep(0.05)
                if lock_wait_observed:
                    remaining = (boundary_at - datetime.datetime.now(datetime.UTC)).total_seconds()
                    if remaining > 0:
                        time.sleep(remaining + 0.25)
            finally:
                lock_connection.commit()
            assert lock_wait_observed, "PostgreSQL did not report the target queue lock wait"
            response = response_future.result(timeout=10)
    finally:
        lock_connection.close()

    assert response.status_code == 200, response.text
    visible = {item["proposalRevisionId"] for item in response.json()}
    assert str(PROPOSAL_BOUNDARY_REVISION) not in visible
    assert str(LEASE_BOUNDARY_REVISION) in visible

    with httpx.Client(timeout=20.0) as client:
        login_approver(client, spring_url)
        repeated = client.get(
            f"{spring_url}/api/approver/compensation-proposals", headers=approver_headers
        )
    assert repeated.status_code == 200, repeated.text
    repeated_visible = {item["proposalRevisionId"] for item in repeated.json()}
    assert str(PROPOSAL_BOUNDARY_REVISION) not in repeated_visible
    assert str(LEASE_BOUNDARY_REVISION) in repeated_visible


if __name__ == "__main__":
    main()
