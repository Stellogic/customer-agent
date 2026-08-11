from __future__ import annotations

import logging
import os
import time

import httpx


LOGGER = logging.getLogger(__name__)


def execute_ready_once(client: httpx.Client) -> int:
    assignments = client.get("/internal/compensation-executions")
    assignments.raise_for_status()
    succeeded = 0
    for assignment in assignments.json():
        execution_id = assignment["executionId"]
        claim = client.post(
            f"/internal/compensation-executions/{execution_id}/claims",
            headers={"Idempotency-Key": f"claim:{execution_id}"},
        )
        if claim.status_code == httpx.codes.CONFLICT:
            continue
        claim.raise_for_status()
        claimed = claim.json()
        if claimed["status"] == "SUCCEEDED":
            continue
        result = client.post(
            f"/internal/compensation-executions/{execution_id}/success",
            headers={"Idempotency-Key": f"success:{execution_id}"},
            json={
                "attemptId": claimed["attemptId"],
                "idempotencyKey": claimed["idempotencyKey"],
                "parameterDigest": claimed["parameterDigest"],
            },
        )
        result.raise_for_status()
        succeeded += 1
    return succeeded


def main() -> None:
    spring_url = os.environ["SPRING_INTERNAL_URL"]
    token = os.environ["EXECUTOR_MACHINE_TOKEN"]
    poll_delay = float(os.environ.get("EXECUTOR_POLL_DELAY", "0.25"))
    with httpx.Client(
        base_url=spring_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=20.0,
    ) as client:
        while True:
            try:
                execute_ready_once(client)
            except httpx.HTTPError:
                LOGGER.warning("compensation execution poll failed", exc_info=True)
            time.sleep(poll_delay)


if __name__ == "__main__":
    main()
