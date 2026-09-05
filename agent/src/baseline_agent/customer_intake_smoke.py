from __future__ import annotations

import httpx


def create_customer_ticket(
    client: httpx.Client,
    spring_url: str,
    request_id: str,
    order_reference: str,
    description: str,
    duplicate_action: str = "CREATE_NEW",
    existing_ticket_id: str | None = None,
    intake_followup: str | None = None,
) -> httpx.Response:
    """Create one smoke-test ticket through the public v4 intake contract."""
    response = client.post(
        f"{spring_url}/api/customer/v2/intakes",
        headers={"Idempotency-Key": request_id},
        json={
            "schema": "customer-intake-v4",
            "message": f"订单 {order_reference} 的物流延迟问题：{description}",
        },
    )
    if response.status_code not in {200, 201}:
        return response

    snapshot = response.json()
    if snapshot["status"] == "CONFIRMED":
        return _confirmed_response(response, snapshot)
    while snapshot["duplicateMatches"]:
        matches = snapshot["duplicateMatches"]
        match = next(
            (
                candidate
                for candidate in matches
                if existing_ticket_id is None or candidate["ticketId"] == existing_ticket_id
            ),
            None,
        )
        if match is None:
            raise AssertionError(f"expected duplicate ticket was not offered: {snapshot}")
        response = client.post(
            f"{spring_url}/api/customer/v2/intakes/{snapshot['intakeId']}/duplicate-resolution",
            headers={"Idempotency-Key": f"{request_id}:duplicate:{match['ticketId']}"},
            json={
                "schema": "customer-intake-v4",
                "existingTicketId": match["ticketId"],
                "action": duplicate_action,
                "expectedVersion": snapshot["version"],
            },
        )
        if response.status_code not in {200, 201}:
            return response
        snapshot = response.json()

    if snapshot["status"] == "CONFIRMED":
        return _confirmed_response(response, snapshot)

    if snapshot["status"] != "READY_TO_CONFIRM":
        raise AssertionError(f"intake did not become confirmable: {snapshot}")
    if intake_followup is not None:
        response = client.post(
            f"{spring_url}/api/customer/v2/intakes/{snapshot['intakeId']}/messages",
            headers={"Idempotency-Key": f"{request_id}:followup"},
            json={
                "schema": "customer-intake-v4",
                "message": intake_followup,
                "expectedVersion": snapshot["version"],
            },
        )
        if response.status_code not in {200, 201}:
            return response
        snapshot = response.json()
        if snapshot["status"] != "READY_TO_CONFIRM":
            raise AssertionError(f"intake followup did not remain confirmable: {snapshot}")
    response = client.post(
        f"{spring_url}/api/customer/v2/intakes/{snapshot['intakeId']}/messages",
        headers={"Idempotency-Key": f"{request_id}:confirm"},
        json={
            "schema": "customer-intake-v4",
            "message": "确认提交",
            "expectedVersion": snapshot["version"],
        },
    )
    if response.status_code not in {200, 201}:
        return response
    return _confirmed_response(response, response.json())


def _confirmed_response(response: httpx.Response, confirmed: dict) -> httpx.Response:
    result_ids = confirmed["ticketIds"] or confirmed["routedTicketIds"]
    if len(result_ids) != 1:
        raise AssertionError(f"intake did not resolve to exactly one ticket: {confirmed}")
    return httpx.Response(
        status_code=response.status_code,
        json={**confirmed, "ticketId": result_ids[0], "accepted": True},
        request=response.request,
    )
