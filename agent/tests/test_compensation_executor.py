import json

import httpx

from baseline_agent.compensation_executor import execute_ready_once


def test_executor_claims_and_confirms_each_assignment_with_stable_delivery_ids() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[{
                    "executionId": "30000000-0000-0000-0000-000000000001",
                    "compensationMethod": "COUPON",
                    "amount": 10.00,
                    "status": "READY",
                }],
            )
        if request.url.path.endswith("/claims"):
            return httpx.Response(
                201,
                json={
                    "executionId": "30000000-0000-0000-0000-000000000001",
                    "attemptId": "30000000-0000-0000-0000-000000000002",
                    "status": "PROCESSING",
                    "idempotencyKey": "compensation-execution:revision",
                    "parameterDigest": "a" * 64,
                    "compensationMethod": "COUPON",
                    "amount": 10.00,
                    "replayed": False,
                },
            )
        assert json.loads(request.content) == {
            "attemptId": "30000000-0000-0000-0000-000000000002",
            "idempotencyKey": "compensation-execution:revision",
            "parameterDigest": "a" * 64,
        }
        return httpx.Response(200, json={"status": "SUCCEEDED"})

    with httpx.Client(
        base_url="http://spring",
        headers={"Authorization": "Bearer executor-secret"},
        transport=httpx.MockTransport(handler),
    ) as client:
        assert execute_ready_once(client) == 1

    execution_id = "30000000-0000-0000-0000-000000000001"
    assert requests[1].headers["Idempotency-Key"] == f"claim:{execution_id}"
    assert requests[2].headers["Idempotency-Key"] == f"success:{execution_id}"
