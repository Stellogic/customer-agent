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
        if assignment["status"] == "UNKNOWN":
            reconciliation = client.get(
                f"/internal/compensation-simulator/{execution_id}/reconciliation",
                headers={"Idempotency-Key": assignment["idempotencyKey"]},
            )
            reconciliation.raise_for_status()
            provider_result = reconciliation.json()
            result = client.post(
                f"/internal/compensation-executions/{execution_id}/reconciliations",
                headers={
                    "Idempotency-Key": f"reconcile:{execution_id}:{provider_result['queryId']}"
                },
                json=provider_result,
            )
            result.raise_for_status()
            if result.json()["status"] == "SUCCEEDED":
                succeeded += 1
            continue
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
        if claimed["compensationMethod"] == "SIMULATED_PARTIAL_REFUND":
            try:
                simulation_headers = {"Idempotency-Key": claimed["idempotencyKey"]}
                if scenario := os.environ.get("EXECUTOR_SIMULATION_SCENARIO"):
                    simulation_headers["X-Simulation-Scenario"] = scenario
                provider = client.post(
                    f"/internal/compensation-simulator/{execution_id}/executions",
                    headers=simulation_headers,
                    json={
                        "parameterDigest": claimed["parameterDigest"],
                        "amount": claimed["amount"],
                    },
                )
                provider.raise_for_status()
            except httpx.HTTPError:
                unknown = client.post(
                    f"/internal/compensation-executions/{execution_id}/unknown",
                    headers={"Idempotency-Key": f"unknown:{execution_id}"},
                    json={
                        "attemptId": claimed["attemptId"],
                        "idempotencyKey": claimed["idempotencyKey"],
                        "parameterDigest": claimed["parameterDigest"],
                    },
                )
                unknown.raise_for_status()
                continue
            if provider.json()["outcome"] == "CONFIRMED_NOT_OCCURRED":
                failed = client.post(
                    f"/internal/compensation-executions/{execution_id}/failures",
                    headers={"Idempotency-Key": f"failure:{execution_id}"},
                    json={
                        "attemptId": claimed["attemptId"],
                        "idempotencyKey": claimed["idempotencyKey"],
                        "parameterDigest": claimed["parameterDigest"],
                    },
                )
                failed.raise_for_status()
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
