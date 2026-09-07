import asyncio
import importlib
import json

import httpx
import pytest
from test_deepseek_intake_model import _completed_intake_response

from baseline_agent.deepseek_intake_model import DeepSeekIntakeModel
from baseline_agent.deepseek_investigation_model import InMemoryModelCallAuditSink


@pytest.mark.asyncio
async def test_concurrent_intake_graphs_keep_known_and_unknown_usage_with_their_own_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = importlib.import_module("baseline_agent.intake_graph")
    known_started = asyncio.Event()
    unknown_finished = asyncio.Event()
    requests: list[httpx.Request] = []

    async def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        customer_text = json.loads(json.loads(request.content)["input"])["customerText"]
        payload = _completed_intake_response()
        if customer_text == "完整计量的受理":
            payload["id"] = "response-known-230"
            known_started.set()
            await unknown_finished.wait()
        else:
            payload["id"] = "response-unknown-230"
            payload.pop("usage")
        return httpx.Response(200, json=payload)

    audit = InMemoryModelCallAuditSink()
    model = DeepSeekIntakeModel(
        "synthetic-test-key", transport=httpx.MockTransport(provider), audit_sink=audit
    )
    monkeypatch.setattr(intake, "intake_model", model)
    monkeypatch.setattr(intake, "intake_model_mode", "deepseek-formal-intake-v3")
    initial = {
        "requested_by": "spring",
        "visible_orders": [{"reference": "ORDER-230", "summary": "合成订单"}],
        "current_order_reference": "ORDER-230",
        "current_pending_issue_kinds": ["DUPLICATE_CHARGE"],
    }

    async def unknown_run() -> dict:
        await known_started.wait()
        try:
            return await intake.graph.ainvoke({**initial, "customer_message": "未知计量的受理"})
        finally:
            unknown_finished.set()

    known, unknown = await asyncio.wait_for(
        asyncio.gather(
            intake.graph.ainvoke({**initial, "customer_message": "完整计量的受理"}), unknown_run()
        ),
        timeout=5,
    )

    assert len(requests) == 2
    for result in (known, unknown):
        assert result["intake_understanding"]["status"] == "READY_TO_CONFIRM"
        evidence = result["intake_call_evidence"]
        assert evidence["schemaVersion"] == "intake-call-evidence-v1"
        assert evidence["currency"] == "USD"
        assert evidence["logicalCalls"] == 1
        assert evidence["providerAttempts"] == 1
        assert evidence["failureClassification"] == ""
        assert len(evidence["attempts"]) == 1

    known_evidence = known["intake_call_evidence"]
    assert known_evidence["inputTokens"] == 80
    assert known_evidence["outputTokens"] == 20
    assert known_evidence["tokens"] == 100
    assert known_evidence["costMicros"] > 0
    assert known_evidence["usageComplete"] is True
    assert known_evidence["attempts"][0]["providerResponseId"] == "response-known-230"
    assert known_evidence["attempts"][0]["cachedTokens"] == 16

    unknown_evidence = unknown["intake_call_evidence"]
    assert unknown_evidence["inputTokens"] is None
    assert unknown_evidence["outputTokens"] is None
    assert unknown_evidence["tokens"] is None
    assert unknown_evidence["costMicros"] is None
    assert unknown_evidence["usageComplete"] is False
    assert unknown_evidence["attempts"][0]["providerResponseId"] == "response-unknown-230"
    assert unknown_evidence["attempts"][0]["cachedTokens"] is None
    assert (
        known_evidence["attempts"][0]["internalCallId"]
        != unknown_evidence["attempts"][0]["internalCallId"]
    )


@pytest.mark.asyncio
async def test_invalid_intake_graph_result_returns_failure_with_its_consumed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = importlib.import_module("baseline_agent.intake_graph")
    payload = _completed_intake_response()
    raw_marker = "PRIVATE_PROVIDER_ANSWER_NOT_FOR_AUDIT"
    payload["output"][0]["content"][0]["text"] = json.dumps({"answer": raw_marker})
    model = DeepSeekIntakeModel(
        "synthetic-test-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    monkeypatch.setattr(intake, "intake_model", model)
    monkeypatch.setattr(intake, "intake_model_mode", "deepseek-formal-intake-v3")

    result = await intake.graph.ainvoke(
        {
            "requested_by": "spring",
            "customer_message": "请核实扣款问题",
            "visible_orders": [{"reference": "ORDER-230", "summary": "合成订单"}],
            "current_order_reference": "ORDER-230",
            "current_pending_issue_kinds": ["DUPLICATE_CHARGE"],
        }
    )

    assert result["intake_failure"] == {"code": "SCHEMA_MISMATCH"}
    assert "intake_understanding" not in result
    evidence = result["intake_call_evidence"]
    assert evidence["logicalCalls"] == 1
    assert evidence["providerAttempts"] == 1
    assert evidence["tokens"] == 100
    assert evidence["usageComplete"] is True
    assert evidence["costMicros"] > 0
    assert evidence["failureClassification"] == "SCHEMA_MISMATCH"
    assert len(evidence["attempts"]) == 1
    assert evidence["attempts"][0]["providerResponseId"] == "response-intake-230"
    assert evidence["attempts"][0]["providerHttpStatus"] == 200
    assert raw_marker not in json.dumps(result)
    assert "invalid clarification answer" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "classification", "http_status"),
    [("http_rejected", "PROVIDER_REQUEST_REJECTED", 400), ("read_timeout", "READ_TIMEOUT", None)],
)
async def test_intake_graph_returns_controlled_provider_failure_with_unknown_usage(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    classification: str,
    http_status: int | None,
) -> None:
    intake = importlib.import_module("baseline_agent.intake_graph")
    raw_marker = "PRIVATE_PROVIDER_ERROR_NOT_FOR_GRAPH"
    requests: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "read_timeout":
            raise httpx.ReadTimeout(raw_marker, request=request)
        return httpx.Response(400, text=raw_marker)

    model = DeepSeekIntakeModel("synthetic-test-key", transport=httpx.MockTransport(provider))
    monkeypatch.setattr(intake, "intake_model", model)
    result = await intake.graph.ainvoke(
        {
            "requested_by": "spring",
            "customer_message": "请核实扣款问题",
            "visible_orders": [{"reference": "ORDER-230", "summary": "合成订单"}],
            "current_order_reference": "ORDER-230",
            "current_pending_issue_kinds": ["DUPLICATE_CHARGE"],
        }
    )

    assert len(requests) == 1
    assert result["intake_failure"] == {"code": classification}
    assert "intake_understanding" not in result
    evidence = result["intake_call_evidence"]
    assert evidence["logicalCalls"] == evidence["providerAttempts"] == 1
    assert evidence["failureClassification"] == classification
    assert evidence["tokens"] is None
    assert evidence["costMicros"] is None
    assert evidence["usageComplete"] is False
    assert len(evidence["attempts"]) == 1
    assert evidence["attempts"][0]["providerHttpStatus"] == http_status
    assert raw_marker not in json.dumps(result)


@pytest.mark.asyncio
async def test_intake_graph_does_not_turn_unaudited_http_failure_into_provider_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = importlib.import_module("baseline_agent.intake_graph")

    class UnavailableIntakeModel:
        async def understand(self, model_input: object) -> None:
            raise httpx.ReadTimeout("failure without a model attempt")

    monkeypatch.setattr(intake, "intake_model", UnavailableIntakeModel())
    with pytest.raises(httpx.ReadTimeout):
        await intake.graph.ainvoke({"requested_by": "spring", "customer_message": "核实订单"})
