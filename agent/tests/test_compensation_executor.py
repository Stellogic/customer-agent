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


def test_executor_recovers_lost_claim_response_and_retries_the_same_success() -> None:
    claim_calls = 0
    success_calls = 0
    execution_id = "30000000-0000-0000-0000-000000000003"
    claimed = {
        "executionId": execution_id,
        "attemptId": "30000000-0000-0000-0000-000000000004",
        "status": "PROCESSING",
        "idempotencyKey": "compensation-execution:recovery",
        "parameterDigest": "b" * 64,
        "compensationMethod": "COUPON",
        "amount": 20.00,
        "replayed": True,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal claim_calls, success_calls
        if request.method == "GET":
            return httpx.Response(200, json=[{
                "executionId": execution_id,
                "compensationMethod": "COUPON",
                "amount": 20.00,
                "status": "PROCESSING" if claim_calls else "READY",
            }])
        if request.url.path.endswith("/claims"):
            claim_calls += 1
            if claim_calls == 1:
                raise httpx.ReadTimeout("claim response was lost", request=request)
            return httpx.Response(200, json=claimed)
        success_calls += 1
        if success_calls == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json={"status": "SUCCEEDED"})

    with httpx.Client(
        base_url="http://spring",
        headers={"Authorization": "Bearer executor-secret"},
        transport=httpx.MockTransport(handler),
    ) as client:
        for _ in range(2):
            try:
                execute_ready_once(client)
            except httpx.HTTPError:
                pass
        assert execute_ready_once(client) == 1

    assert claim_calls == 3
    assert success_calls == 2
