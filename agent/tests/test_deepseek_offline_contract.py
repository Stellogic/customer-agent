from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TypedDict

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from baseline_agent.deepseek_investigation_model import (
    DeepSeekFailureClassification,
    DeepSeekResponsesConfig,
    DeepSeekResponsesInvestigationModel,
    InMemoryModelCallAuditSink,
    ModelCallAttemptRecord,
)
from baseline_agent.investigation_model import (
    InvestigationJudgmentFailure,
    InvestigationJudgmentFailureCode,
    InvestigationJudgmentInput,
    InvestigationReasonCode,
)

MODEL_INPUT = InvestigationJudgmentInput(
    order_reference="ORDER-OFFLINE-001",
    delay_seconds=80 * 60 * 60,
    evidence_refs=("order:ORDER-OFFLINE-001", "logistics:ORDER-OFFLINE-001"),
)
FORBIDDEN_RAW_MATERIAL = (
    "offline-contract-secret",
    "ORDER-OFFLINE-001",
    "raw prompt",
    "model body",
    "provider payload",
)


def _completed_response() -> dict[str, object]:
    return {
        "id": "resp-offline-1",
        "status": "completed",
        "model": "deepseek-v4-flash-offline",
        "system_fingerprint": "offline-fingerprint",
        "output": [
            {
                "type": "message",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "compensationReviewRequired": True,
                                "reasonCode": "LOGISTICS_DELAY",
                            },
                            separators=(",", ":"),
                        ),
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 11,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 7,
            "total_tokens": 18,
        },
    }


@dataclass(frozen=True)
class _SupplierAction:
    status_code: int = 200
    payload: dict[str, object] | None = None
    delay_seconds: float = 0
    disconnect: bool = False


class _CheckpointState(TypedDict, total=False):
    compensation_review_required: bool
    reason_code: str


class _JsonlAuditSink:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def record(self, record: ModelCallAttemptRecord) -> None:
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(record), default=str) + "\n")


def _offline_model(
    endpoint: str,
    *,
    audit: InMemoryModelCallAuditSink | _JsonlAuditSink | None = None,
    max_attempts: int = 1,
    max_output_tokens: int = 128,
    connect_timeout_seconds: float = 3,
    read_timeout_seconds: float = 15,
    deadline_seconds: float = 20,
) -> DeepSeekResponsesInvestigationModel:
    return DeepSeekResponsesInvestigationModel(
        DeepSeekResponsesConfig(
            api_key="offline-contract-secret",
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            deadline_seconds=deadline_seconds,
            max_attempts=max_attempts,
            retry_base_delay_seconds=0,
            max_output_tokens=max_output_tokens,
        ),
        endpoint=endpoint,
        audit_sink=audit,
    )


@contextmanager
def _supplier_stub(
    *actions: _SupplierAction,
) -> Iterator[tuple[str, list[dict[str, object]]]]:
    requests: list[dict[str, object]] = []
    remaining_actions = list(actions) or [_SupplierAction(payload=_completed_response())]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            content_length = int(self.headers["Content-Length"])
            requests.append(json.loads(self.rfile.read(content_length)))
            action = remaining_actions.pop(0)
            if action.delay_seconds:
                time.sleep(action.delay_seconds)
            if action.disconnect:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            body = json.dumps(action.payload or {}).encode()
            self.send_response(action.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/responses", requests
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


@pytest.mark.asyncio
async def test_offline_supplier_contract_is_exercised_through_the_public_model_interface() -> None:
    with _supplier_stub() as (endpoint, requests):
        audit = InMemoryModelCallAuditSink()
        model = _offline_model(endpoint, audit=audit)

        judgment = await model.judge(MODEL_INPUT)

    assert judgment.compensation_review_required is True
    assert judgment.reason_code is InvestigationReasonCode.LOGISTICS_DELAY
    assert len(requests) == 1
    assert len(audit.records) == 1


@pytest.mark.asyncio
async def test_offline_supplier_receives_only_the_allowed_strict_request_contract() -> None:
    with _supplier_stub() as (endpoint, requests):
        model = _offline_model(endpoint, max_output_tokens=64)

        await model.judge(MODEL_INPUT)

    assert len(requests) == 1
    request = requests[0]
    assert set(request) == {
        "model",
        "instructions",
        "input",
        "max_output_tokens",
        "reasoning",
        "stream",
        "text",
    }
    assert request["max_output_tokens"] == 64
    assert json.loads(str(request["input"])) == {
        "syntheticInvestigationFacts": {"delaySeconds": 288000}
    }
    output_schema = request["text"]
    assert isinstance(output_schema, dict)
    output_format = output_schema["format"]
    assert isinstance(output_format, dict)
    schema = output_format["schema"]
    assert isinstance(schema, dict)
    assert output_format["strict"] is True
    assert schema["required"] == ["compensationReviewRequired", "reasonCode"]
    assert schema["additionalProperties"] is False
    reason_code = schema["properties"]["reasonCode"]
    assert set(reason_code["enum"]) == {"LOGISTICS_DELAY", "DELAY_UNDER_24_HOURS"}
    serialized = json.dumps(request)
    assert "ORDER-OFFLINE-001" not in serialized
    assert "order:ORDER-OFFLINE-001" not in serialized
    assert "offline-contract-secret" not in serialized


@pytest.mark.asyncio
async def test_offline_contract_rejects_an_unscoped_evidence_array_before_supplier_access() -> None:
    with _supplier_stub() as (endpoint, requests):
        model = _offline_model(endpoint)

        with pytest.raises(InvestigationJudgmentFailure) as captured:
            await model.judge(
                InvestigationJudgmentInput(
                    order_reference="ORDER-OFFLINE-001",
                    delay_seconds=80 * 60 * 60,
                    evidence_refs=("raw-provider-payload",),
                )
            )

    assert captured.value.code is InvestigationJudgmentFailureCode.INVALID_INPUT
    assert requests == []


@pytest.mark.parametrize(
    "text",
    [
        '{"reasonCode":"LOGISTICS_DELAY"}',
        '{"compensationReviewRequired":true,"reasonCode":"UNKNOWN"}',
        (
            '{"compensationReviewRequired":true,"reasonCode":"LOGISTICS_DELAY",'
            '"evidenceRefs":["raw-provider-payload"]}'
        ),
    ],
)
@pytest.mark.asyncio
async def test_offline_supplier_cannot_weaken_required_enum_or_additional_field_rules(
    text: str,
) -> None:
    response = _completed_response()
    response["output"] = [
        {
            "type": "message",
            "status": "completed",
            "content": [{"type": "output_text", "text": text}],
        }
    ]
    with _supplier_stub(_SupplierAction(payload=response)) as (endpoint, requests):
        audit = InMemoryModelCallAuditSink()
        model = _offline_model(endpoint, audit=audit, max_attempts=3)

        with pytest.raises(InvestigationJudgmentFailure) as captured:
            await model.judge(MODEL_INPUT)

    assert captured.value.code is InvestigationJudgmentFailureCode.MODEL_CALL_FAILED
    assert len(requests) == 1
    assert len(audit.records) == 1
    assert audit.records[0].failure_classification is DeepSeekFailureClassification.SCHEMA_MISMATCH


@pytest.mark.parametrize("status_code", [400, 401, 402, 422])
@pytest.mark.asyncio
async def test_offline_supplier_deterministic_errors_never_retry_or_fall_back(
    status_code: int,
) -> None:
    error = {"error": {"message": "raw provider payload must not escape"}}
    with _supplier_stub(_SupplierAction(status_code=status_code, payload=error)) as (
        endpoint,
        requests,
    ):
        audit = InMemoryModelCallAuditSink()
        model = _offline_model(endpoint, audit=audit, max_attempts=3)

        with pytest.raises(InvestigationJudgmentFailure) as captured:
            await model.judge(MODEL_INPUT)

    assert captured.value.code is InvestigationJudgmentFailureCode.MODEL_CALL_FAILED
    assert len(requests) == 1
    assert len(audit.records) == 1
    assert (
        audit.records[0].failure_classification
        is DeepSeekFailureClassification.PROVIDER_REQUEST_REJECTED
    )


@pytest.mark.parametrize("status_code", [429, 500, 503])
@pytest.mark.asyncio
async def test_offline_supplier_transient_errors_record_every_bounded_attempt(
    status_code: int,
) -> None:
    actions = (
        _SupplierAction(status_code=status_code, payload={"error": {"message": "temporary-1"}}),
        _SupplierAction(status_code=status_code, payload={"error": {"message": "temporary-2"}}),
        _SupplierAction(payload=_completed_response()),
    )
    with _supplier_stub(*actions) as (endpoint, requests):
        audit = InMemoryModelCallAuditSink()
        model = _offline_model(endpoint, audit=audit, max_attempts=3)

        judgment = await model.judge(MODEL_INPUT)

    assert judgment.reason_code is InvestigationReasonCode.LOGISTICS_DELAY
    assert len(requests) == 3
    assert [record.attempt_number for record in audit.records] == [1, 2, 3]
    assert len({record.attempt_id for record in audit.records}) == 3
    assert len({record.internal_call_id for record in audit.records}) == 1
    assert [record.failure_classification for record in audit.records] == [
        DeepSeekFailureClassification.TRANSIENT_PROVIDER_ERROR,
        DeepSeekFailureClassification.TRANSIENT_PROVIDER_ERROR,
        None,
    ]


@pytest.mark.asyncio
async def test_offline_supplier_ambiguous_disconnect_is_a_distinct_recorded_attempt() -> None:
    with _supplier_stub(
        _SupplierAction(disconnect=True),
        _SupplierAction(payload=_completed_response()),
    ) as (endpoint, requests):
        audit = InMemoryModelCallAuditSink()
        model = _offline_model(endpoint, audit=audit, max_attempts=2)

        judgment = await model.judge(MODEL_INPUT)

    assert judgment.reason_code is InvestigationReasonCode.LOGISTICS_DELAY
    assert len(requests) == 2
    assert [record.failure_classification for record in audit.records] == [
        DeepSeekFailureClassification.TRANSIENT_PROVIDER_ERROR,
        None,
    ]


@pytest.mark.asyncio
async def test_offline_supplier_read_timeout_is_bounded_and_recorded_per_attempt() -> None:
    slow = _SupplierAction(payload=_completed_response(), delay_seconds=0.08)
    with _supplier_stub(slow, slow) as (endpoint, requests):
        audit = InMemoryModelCallAuditSink()
        model = _offline_model(
            endpoint,
            audit=audit,
            read_timeout_seconds=0.01,
            deadline_seconds=1,
            max_attempts=2,
        )

        with pytest.raises(InvestigationJudgmentFailure) as captured:
            await model.judge(MODEL_INPUT)

    assert captured.value.code is InvestigationJudgmentFailureCode.MODEL_CALL_FAILED
    assert len(requests) == 2
    assert [record.failure_classification for record in audit.records] == [
        DeepSeekFailureClassification.READ_TIMEOUT,
        DeepSeekFailureClassification.READ_TIMEOUT,
    ]


@pytest.mark.asyncio
async def test_offline_supplier_whole_call_deadline_stops_the_attempt_budget() -> None:
    with _supplier_stub(_SupplierAction(payload=_completed_response(), delay_seconds=0.08)) as (
        endpoint,
        requests,
    ):
        audit = InMemoryModelCallAuditSink()
        model = _offline_model(
            endpoint,
            audit=audit,
            read_timeout_seconds=1,
            deadline_seconds=0.01,
            max_attempts=3,
        )

        with pytest.raises(InvestigationJudgmentFailure) as captured:
            await model.judge(MODEL_INPUT)

    assert captured.value.code is InvestigationJudgmentFailureCode.MODEL_CALL_FAILED
    assert len(requests) <= 1
    assert len(audit.records) == len(requests)
    assert all(
        record.failure_classification is DeepSeekFailureClassification.DEADLINE_EXCEEDED
        for record in audit.records
    )


@pytest.mark.asyncio
async def test_offline_contract_classifies_connection_timeout_without_network_access() -> None:
    def connect_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("offline connect timeout", request=request)

    audit = InMemoryModelCallAuditSink()
    model = DeepSeekResponsesInvestigationModel(
        DeepSeekResponsesConfig(
            api_key="offline-contract-secret",
            max_attempts=2,
            retry_base_delay_seconds=0,
        ),
        transport=httpx.MockTransport(connect_timeout),
        audit_sink=audit,
    )

    with pytest.raises(InvestigationJudgmentFailure) as captured:
        await model.judge(MODEL_INPUT)

    assert captured.value.code is InvestigationJudgmentFailureCode.MODEL_CALL_FAILED
    assert [record.failure_classification for record in audit.records] == [
        DeepSeekFailureClassification.CONNECTION_TIMEOUT,
        DeepSeekFailureClassification.CONNECTION_TIMEOUT,
    ]


@pytest.mark.asyncio
async def test_offline_failure_records_and_logs_exclude_all_raw_material(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    provider_payload = {
        "error": {
            "message": (
                "offline-contract-secret ORDER-OFFLINE-001 raw prompt model body provider payload"
            )
        }
    }
    with _supplier_stub(_SupplierAction(status_code=400, payload=provider_payload)) as (
        endpoint,
        _,
    ):
        audit_path = tmp_path / "model-call-attempts.jsonl"
        model = _offline_model(endpoint, audit=_JsonlAuditSink(audit_path))

        with pytest.raises(InvestigationJudgmentFailure):
            await model.judge(MODEL_INPUT)

    persisted_record = audit_path.read_text(encoding="utf-8")
    assert all(value not in persisted_record for value in FORBIDDEN_RAW_MATERIAL)
    assert all(value not in caplog.text for value in FORBIDDEN_RAW_MATERIAL)


@pytest.mark.asyncio
async def test_offline_model_raw_material_never_enters_a_langgraph_checkpoint() -> None:
    response = _completed_response()
    response["provider_private_payload"] = {
        "prompt": "raw prompt",
        "body": "model body provider payload",
    }
    with _supplier_stub(_SupplierAction(payload=response)) as (endpoint, _):
        model = _offline_model(endpoint)

        async def judge(_: _CheckpointState) -> _CheckpointState:
            judgment = await model.judge(MODEL_INPUT)
            return {
                "compensation_review_required": judgment.compensation_review_required,
                "reason_code": judgment.reason_code.value,
            }

        builder = StateGraph(_CheckpointState)
        builder.add_node("judge", judge)
        builder.add_edge(START, "judge")
        builder.add_edge("judge", END)
        graph = builder.compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "issue-114-offline-contract"}}

        await graph.ainvoke({}, config)
        checkpoint = await graph.aget_state(config)

    serialized_checkpoint = json.dumps(checkpoint.values)
    assert json.loads(serialized_checkpoint) == {
        "compensation_review_required": True,
        "reason_code": "LOGISTICS_DELAY",
    }
    assert all(value not in serialized_checkpoint for value in FORBIDDEN_RAW_MATERIAL)
