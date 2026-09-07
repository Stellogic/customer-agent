import asyncio
import importlib
import json

import httpx
import pytest
from test_customer_communication_model import _payment_reply
from test_deepseek_customer_communication_model import _completed, _streamed
from test_graph import _capability_catalog, _capability_result, _with_facts

from baseline_agent.deepseek_customer_communication_model import (
    DeepSeekCustomerCommunicationConfig,
    DeepSeekResponsesCustomerCommunicationModel,
)
from baseline_agent.deepseek_investigation_model import InMemoryModelCallAuditSink
from baseline_agent.investigation_action_loop import DeterministicActionModel


@pytest.mark.asyncio
async def test_concurrent_graph_runs_keep_actual_provider_attempts_and_unknown_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_module = importlib.import_module("baseline_agent.graph")
    native_client = httpx.AsyncClient
    successful_started = asyncio.Event()
    failed_finished = asyncio.Event()
    supplier_calls: list[str] = []
    conclusions: list[str] = []
    catalog = _capability_catalog()
    policy = catalog["requiredFacts"]
    policy["riskScenario"] = "DUPLICATE_CHARGE"
    payment_types = {
        "ORDER",
        "PAYMENT",
        "ORDER_CANCELLATION",
        "REFUND_STATUS",
        "EXISTING_COMPENSATION",
        "PENDING_ACTION_COUNT",
    }
    policy["facts"] = [fact for fact in policy["facts"] if fact["factType"] in payment_types]
    for fact in policy["facts"]:
        if fact["factType"] == "PAYMENT":
            fact["applicability"] = "PAYMENT_STATUS"
        elif fact["factType"] == "REFUND_STATUS":
            fact["applicability"] = "REFUND_STATUS"

    def spring(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        ticket_id = path.split("/tickets/", 1)[1].split("/", 1)[0]
        order = "ORDER-PROVIDER-A" if ticket_id == "ticket-a" else "ORDER-PROVIDER-B"
        if path.endswith("/capabilities"):
            payload = catalog
        elif path.endswith("/sibling-summary"):
            payload = {"schemaVersion": "sibling-ticket-summary-v1", "tickets": []}
        elif path.endswith("/customer-communication-context"):
            payload = {
                "schemaVersion": "customer-communication-input-v1",
                "syntheticCustomerText": "疑似重复扣款，请核查。",
                "publicConversation": [],
            }
        elif "/capabilities/" in path:
            payload = _capability_result(
                path, _with_facts(orderReference=order, duplicateChargeSuspected=True)
            )
        elif path.endswith("/human-handoff"):
            payload = {"handlingMode": "HUMAN", "reasonCode": "INVALID_MODEL_OUTPUT"}
        else:
            if path.endswith("/conclusions"):
                conclusions.append(ticket_id)
            payload = {"accepted": True, "lifecycleState": "INVESTIGATING"}
        return httpx.Response(200, json=payload)

    async def supplier(request: httpx.Request) -> httpx.Response:
        authorized = json.loads(json.loads(request.content)["input"])["authorizedInvestigation"]
        order = authorized["orderReference"]
        supplier_calls.append(order)
        if order == "ORDER-PROVIDER-A":
            successful_started.set()
            await failed_finished.wait()
            reply = _payment_reply()
            reply["body"] = reply["body"].replace("ORDER-C129", order)
            reply["referencedOrder"] = order
            reply["evidenceRefs"] = [f"order:{order}", f"payment:{order}"]
            payload = _completed(reply["body"], reply["intent"])
            payload["output"][0]["content"][0]["text"] = json.dumps(reply, ensure_ascii=False)
            return _streamed(payload, split_at=80)
        await successful_started.wait()
        return httpx.Response(400, json={"error": {"code": "invalid_request"}})

    def client_factory(**kwargs):
        if kwargs.get("transport") is None:
            kwargs["transport"] = httpx.MockTransport(spring)
        return native_client(**kwargs)

    audit = InMemoryModelCallAuditSink()
    model = DeepSeekResponsesCustomerCommunicationModel(
        DeepSeekCustomerCommunicationConfig(api_key="synthetic-test-key", max_attempts=1),
        transport=httpx.MockTransport(supplier),
        audit_sink=audit,
    )
    monkeypatch.setattr(graph_module.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(graph_module, "customer_communication_model", model)
    monkeypatch.setattr(graph_module, "investigation_action_model", DeterministicActionModel())
    monkeypatch.setenv("SPRING_INTERNAL_URL", "http://spring")
    monkeypatch.setenv("AGENT_MACHINE_TOKEN", "synthetic-agent-token")
    monkeypatch.setenv("AGENT_INVESTIGATION_SHADOW_MODE", "disabled")

    async def run(suffix: str):
        try:
            return await graph_module.graph.ainvoke(
                {
                    "requested_by": "spring",
                    "ticket_id": f"ticket-{suffix}",
                    "generation_id": f"generation-{suffix}",
                    "issue_kind": "DUPLICATE_CHARGE",
                }
            )
        finally:
            if suffix == "b":
                failed_finished.set()

    async with asyncio.timeout(10):
        successful, failed = await asyncio.gather(run("a"), run("b"))

    assert conclusions == ["ticket-a"]
    assert "conclusion" in successful
    assert failed["handoff"]["reasonCode"] == "INVALID_MODEL_OUTPUT"
    # The graph retains its existing one correction before a controlled handoff.
    assert supplier_calls.count("ORDER-PROVIDER-A") == 1
    assert supplier_calls.count("ORDER-PROVIDER-B") == 2
    assert len(audit.records) == 3
    evidences = [successful["provider_call_evidence"], failed["provider_call_evidence"]]
    for suffix, evidence, expected_attempts, http_status in zip(
        ("a", "b"), evidences, (1, 2), (200, 400), strict=True
    ):
        assert evidence["schemaVersion"] == "provider-call-evidence-v1"
        assert evidence["ticketId"] == f"ticket-{suffix}"
        assert evidence["generationId"] == f"generation-{suffix}"
        assert evidence["providerAttempts"] == expected_attempts
        assert len(evidence["attempts"]) == expected_attempts
        assert {attempt["role"] for attempt in evidence["attempts"]} == {"communication"}
        assert {attempt["attemptId"] for attempt in evidence["attempts"]} == {
            record.attempt_id
            for record in audit.records
            if record.provider_http_status == http_status
        }
    assert evidences[0]["usageComplete"] is True
    assert evidences[0]["tokens"] == 110
    assert evidences[1]["usageComplete"] is False
    for name in ("inputTokens", "outputTokens", "tokens", "costMicros"):
        assert evidences[1][name] is None
    for attempt in evidences[1]["attempts"]:
        assert attempt["inputTokens"] is None
        assert attempt["outputTokens"] is None
        assert attempt["totalTokens"] is None
