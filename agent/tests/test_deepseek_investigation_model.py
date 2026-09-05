from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from baseline_agent.deepseek_investigation_model import (
    DeepSeekFailureClassification,
    DeepSeekResponsesConfig,
    DeepSeekResponsesInvestigationModel,
    InMemoryModelCallAuditSink,
)
from baseline_agent.investigation_model import (
    InvestigationJudgmentFailure,
    InvestigationJudgmentFailureCode,
    InvestigationJudgmentInput,
    InvestigationReasonCode,
)

MODEL_INPUT = InvestigationJudgmentInput(
    order_reference="ORDER-DELAY-001",
    delay_seconds=80 * 60 * 60,
    evidence_refs=("order:ORDER-DELAY-001", "logistics:ORDER-DELAY-001"),
)


def _response(
    *,
    status: str = "completed",
    text: str | None = '{"compensationReviewRequired":true,"reasonCode":"LOGISTICS_DELAY"}',
    response_id: str = "resp-1",
    incomplete_reason: str | None = None,
) -> dict[str, object]:
    content: list[dict[str, object]] = []
    if text is not None:
        content.append({"type": "output_text", "text": text})
    return {
        "id": response_id,
        "object": "response",
        "created_at": 1_787_616_000,
        "status": status,
        "model": "deepseek-v4-flash-202608",
        "system_fingerprint": "fp_202608",
        "output": [
            {
                "id": "message-1",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": content,
            }
        ],
        "usage": {
            "input_tokens": 19,
            "input_tokens_details": {"cached_tokens": 7},
            "output_tokens": 8,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 27,
        },
        "error": None,
        "incomplete_details": (
            {"reason": incomplete_reason} if incomplete_reason is not None else None
        ),
    }


def _model(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_attempts: int = 3,
    deadline_seconds: float = 2,
) -> tuple[DeepSeekResponsesInvestigationModel, InMemoryModelCallAuditSink]:
    audit = InMemoryModelCallAuditSink()
    config = DeepSeekResponsesConfig(
        api_key="deepseek-test-secret",
        model="deepseek-v4-flash",
        connect_timeout_seconds=0.2,
        read_timeout_seconds=0.2,
        deadline_seconds=deadline_seconds,
        max_attempts=max_attempts,
        retry_base_delay_seconds=0,
    )
    return (
        DeepSeekResponsesInvestigationModel(
            config,
            transport=httpx.MockTransport(handler),
            audit_sink=audit,
        ),
        audit,
    )


@pytest.mark.asyncio
async def test_deepseek_adapter_sends_only_minimal_facts_and_strict_allowed_parameters() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_response())

    model, _ = _model(handler)

    judgment = await model.judge(MODEL_INPUT)

    assert judgment.compensation_review_required is True
    assert judgment.reason_code is InvestigationReasonCode.LOGISTICS_DELAY
    body = captured["body"]
    assert isinstance(body, dict)
    assert set(body) == {
        "model",
        "instructions",
        "input",
        "max_output_tokens",
        "reasoning",
        "stream",
        "text",
    }
    assert json.loads(body["input"]) == {"syntheticInvestigationFacts": {"delaySeconds": 288000}}
    assert body["reasoning"] == {"effort": "none"}
    assert body["stream"] is False
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    assert set(body["text"]["format"]["schema"]["properties"]) == {
        "compensationReviewRequired",
        "reasonCode",
    }
    serialized = json.dumps(body)
    assert "ORDER-DELAY-001" not in serialized
    assert "deepseek-test-secret" not in serialized
    assert captured["authorization"] == "Bearer deepseek-test-secret"


@pytest.mark.asyncio
async def test_deepseek_adapter_records_minimal_metadata_without_raw_material() -> None:
    model, audit = _model(lambda _: httpx.Response(200, json=_response()))

    await model.judge(MODEL_INPUT)

    assert len(audit.records) == 1
    record = audit.records[0]
    assert record.attempt_number == 1
    assert record.provider_response_id == "resp-1"
    assert record.response_status == "completed"
    assert record.request_model == "deepseek-v4-flash"
    assert record.response_model == "deepseek-v4-flash-202608"
    assert record.backend_fingerprint == "fp_202608"
    assert record.prompt_version == "investigation-judgment-v1"
    assert record.schema_version == "investigation-judgment-v1"
    assert record.input_tokens == 19
    assert record.output_tokens == 8
    assert record.total_tokens == 27
    assert record.cached_tokens == 7
    assert record.cache_hit is True
    assert record.provider == "deepseek"
    assert record.failure_classification is None
    assert record.strict_schema_requested is True
    assert record.thinking_disabled is True
    assert record.allowed_parameters_only is True
    assert record.actual_response_shape_valid is True
    assert record.usage_reported is True
    assert record.cache_metrics_reported is True
    assert record.reasoning_tokens == 0
    rendered = repr(record)
    assert "deepseek-test-secret" not in rendered
    assert "ORDER-DELAY-001" not in rendered
    assert "compensationReviewRequired" not in rendered


@pytest.mark.asyncio
async def test_deepseek_adapter_observes_actual_non_thinking_response() -> None:
    payload = _response()
    output = payload["output"]
    assert isinstance(output, list)
    payload["output"] = [
        {
            "id": "reasoning-1",
            "type": "reasoning",
            "status": "completed",
            "content": [{"type": "reasoning_text", "text": "private"}],
        },
        *output,
    ]
    usage = payload["usage"]
    assert isinstance(usage, dict)
    usage["output_tokens_details"] = {"reasoning_tokens": 1}
    model, audit = _model(lambda _: httpx.Response(200, json=payload))

    await model.judge(MODEL_INPUT)

    assert audit.records[0].thinking_disabled is False
    assert audit.records[0].reasoning_tokens == 1


@pytest.mark.asyncio
async def test_deepseek_adapter_flags_malformed_observed_response_shape() -> None:
    payload = _response()
    output = payload["output"]
    assert isinstance(output, list) and isinstance(output[0], dict)
    output[0].pop("role")
    model, audit = _model(lambda _: httpx.Response(200, json=payload))

    await model.judge(MODEL_INPUT)

    assert audit.records[0].actual_response_shape_valid is False


@pytest.mark.parametrize(
    ("payload", "expected_classification"),
    [
        (_response(status="failed"), DeepSeekFailureClassification.PROVIDER_FAILED),
        (
            _response(status="incomplete", incomplete_reason="content_filter"),
            DeepSeekFailureClassification.PROVIDER_INCOMPLETE,
        ),
        (
            _response(status="incomplete", incomplete_reason="max_output_tokens"),
            DeepSeekFailureClassification.OUTPUT_TRUNCATED,
        ),
        (_response(text=None), DeepSeekFailureClassification.EMPTY_OUTPUT),
        (_response(text="not-json"), DeepSeekFailureClassification.INVALID_JSON),
        (
            _response(text='{"compensationReviewRequired":true}'),
            DeepSeekFailureClassification.SCHEMA_MISMATCH,
        ),
        (
            _response(text=('{"compensationReviewRequired":false,"reasonCode":"LOGISTICS_DELAY"}')),
            DeepSeekFailureClassification.SCHEMA_MISMATCH,
        ),
    ],
)
@pytest.mark.asyncio
async def test_deepseek_adapter_classifies_non_success_responses_without_retry(
    payload: dict[str, object],
    expected_classification: DeepSeekFailureClassification,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=payload)

    model, audit = _model(handler)

    with pytest.raises(InvestigationJudgmentFailure) as captured:
        await model.judge(MODEL_INPUT)

    assert captured.value.code is InvestigationJudgmentFailureCode.MODEL_CALL_FAILED
    assert calls == 1
    assert audit.records[0].failure_classification is expected_classification


@pytest.mark.asyncio
async def test_deepseek_adapter_classifies_refusal_without_reading_reasoning() -> None:
    payload = _response(text=None)
    payload["output"] = [
        {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "private"}]},
        {
            "type": "message",
            "status": "completed",
            "content": [{"type": "refusal", "refusal": "cannot comply"}],
        },
    ]
    model, audit = _model(lambda _: httpx.Response(200, json=payload))

    with pytest.raises(InvestigationJudgmentFailure) as captured:
        await model.judge(MODEL_INPUT)

    assert captured.value.code is InvestigationJudgmentFailureCode.MODEL_CALL_FAILED
    assert audit.records[0].failure_classification is DeepSeekFailureClassification.MODEL_REFUSAL
    assert "private" not in repr(audit.records[0])
    assert "cannot comply" not in repr(audit.records[0])


@pytest.mark.parametrize("status_code", [400, 401, 402, 422])
@pytest.mark.asyncio
async def test_deepseek_adapter_does_not_retry_deterministic_http_errors(
    status_code: int,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, json={"error": {"message": "do not persist me"}})

    model, audit = _model(handler)

    with pytest.raises(InvestigationJudgmentFailure) as captured:
        await model.judge(MODEL_INPUT)

    assert captured.value.code is InvestigationJudgmentFailureCode.MODEL_CALL_FAILED
    assert calls == 1
    assert len(audit.records) == 1
    assert (
        audit.records[0].failure_classification
        is DeepSeekFailureClassification.PROVIDER_REQUEST_REJECTED
    )
    assert "do not persist me" not in repr(audit.records[0])


@pytest.mark.parametrize("status_code", [429, 500, 503])
@pytest.mark.asyncio
async def test_deepseek_adapter_retries_transient_http_errors_with_one_record_per_attempt(
    status_code: int,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(status_code, json={"error": {"message": "temporary"}})
        return httpx.Response(200, json=_response(response_id="resp-recovered"))

    model, audit = _model(handler)

    judgment = await model.judge(MODEL_INPUT)

    assert judgment.compensation_review_required is True
    assert calls == 3
    assert len(audit.records) == 3
    assert [record.attempt_number for record in audit.records] == [1, 2, 3]
    assert all(
        record.internal_call_id == audit.records[0].internal_call_id for record in audit.records
    )
    assert len({record.attempt_id for record in audit.records}) == 3
    assert [record.failure_classification for record in audit.records] == [
        DeepSeekFailureClassification.TRANSIENT_PROVIDER_ERROR,
        DeepSeekFailureClassification.TRANSIENT_PROVIDER_ERROR,
        None,
    ]


@pytest.mark.parametrize(
    ("exception_factory", "expected_classification"),
    [
        (
            lambda request: httpx.ConnectTimeout("connect", request=request),
            DeepSeekFailureClassification.CONNECTION_TIMEOUT,
        ),
        (
            lambda request: httpx.ReadTimeout("read", request=request),
            DeepSeekFailureClassification.READ_TIMEOUT,
        ),
    ],
)
@pytest.mark.asyncio
async def test_deepseek_adapter_bounds_timeout_retries(
    exception_factory: Callable[[httpx.Request], Exception],
    expected_classification: DeepSeekFailureClassification,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise exception_factory(request)

    model, audit = _model(handler, max_attempts=2)

    with pytest.raises(InvestigationJudgmentFailure) as captured:
        await model.judge(MODEL_INPUT)

    assert captured.value.code is InvestigationJudgmentFailureCode.MODEL_CALL_FAILED
    assert calls == 2
    assert len(audit.records) == 2
    assert all(record.failure_classification is expected_classification for record in audit.records)


@pytest.mark.asyncio
async def test_deepseek_adapter_enforces_the_whole_call_deadline() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, json=_response())

    audit = InMemoryModelCallAuditSink()
    model = DeepSeekResponsesInvestigationModel(
        DeepSeekResponsesConfig(
            api_key="secret",
            deadline_seconds=0.01,
            max_attempts=3,
            retry_base_delay_seconds=0,
        ),
        transport=httpx.MockTransport(handler),
        audit_sink=audit,
    )

    with pytest.raises(InvestigationJudgmentFailure) as captured:
        await model.judge(MODEL_INPUT)

    assert captured.value.code is InvestigationJudgmentFailureCode.MODEL_CALL_FAILED
    assert len(audit.records) == 1
    assert (
        audit.records[0].failure_classification is DeepSeekFailureClassification.DEADLINE_EXCEEDED
    )


def test_deepseek_configuration_fails_explicitly_without_key_or_for_unsupported_model() -> None:
    with pytest.raises(InvestigationJudgmentFailure) as missing:
        DeepSeekResponsesConfig.from_environment({"DEEPSEEK_MODEL": "deepseek-v4-flash"})

    assert missing.value.code is InvestigationJudgmentFailureCode.CONFIGURATION_ERROR

    with pytest.raises(InvestigationJudgmentFailure) as unsupported:
        DeepSeekResponsesConfig(
            api_key="secret",
            model="deepseek-v4-pro",
        )

    assert unsupported.value.code is InvestigationJudgmentFailureCode.CONFIGURATION_ERROR


def test_deepseek_configuration_reads_only_explicit_deepseek_settings() -> None:
    config = DeepSeekResponsesConfig.from_environment(
        {
            "DEEPSEEK_API_KEY": "secret",
            "DEEPSEEK_MODEL": "deepseek-v4-flash",
            "OPENAI_API_KEY": "must-not-be-used",
        }
    )

    assert config.api_key == "secret"
    assert config.model == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_concurrent_judgment_evidence_does_not_include_another_call_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    graph_module = importlib.import_module("baseline_agent.graph")
    successful_started = asyncio.Event()
    failed_finished = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        facts = json.loads(body["input"])["syntheticInvestigationFacts"]
        if facts["delaySeconds"] == 288000:
            successful_started.set()
            await failed_finished.wait()
            return httpx.Response(200, json=_response())
        return httpx.Response(400, json={"error": {"code": "invalid_request"}})

    audit = InMemoryModelCallAuditSink()
    model = DeepSeekResponsesInvestigationModel(
        DeepSeekResponsesConfig(api_key="test-only", max_attempts=1),
        transport=httpx.MockTransport(handler),
        audit_sink=audit,
    )
    monkeypatch.setattr(graph_module, "investigation_judgment_model", model)

    async def successful_call() -> dict[str, object]:
        offset = graph_module._judgment_audit_offset()
        await model.judge(MODEL_INPUT)
        return graph_module._judgment_call_evidence(offset, "")

    async def failed_call() -> dict[str, object]:
        await successful_started.wait()
        offset = graph_module._judgment_audit_offset()
        try:
            with pytest.raises(InvestigationJudgmentFailure):
                await model.judge(
                    InvestigationJudgmentInput(
                        order_reference="ORDER-DELAY-002",
                        delay_seconds=3600,
                        evidence_refs=("order:ORDER-DELAY-002", "logistics:ORDER-DELAY-002"),
                    )
                )
            return graph_module._judgment_call_evidence(offset, "MODEL_CALL_FAILED")
        finally:
            failed_finished.set()

    successful, failed = await asyncio.gather(successful_call(), failed_call())
    assert len(audit.records) == 2
    assert failed["providerAttempts"] == 1
    assert failed["failureClassification"] == "MODEL_CALL_FAILED"
    assert successful["providerAttempts"] == 1
    assert successful["failureClassification"] == ""
    assert successful["tokens"] == 27
