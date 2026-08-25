from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest

import baseline_agent.deepseek_real_evaluation as real_evaluation
from baseline_agent.deepseek_real_evaluation import (
    ISSUE_125_OPT_IN,
    RealEvaluationBlocked,
    run_real_evaluation,
)


def _completed_response(request: httpx.Request, *, include_cache: bool = True) -> dict[str, object]:
    body = json.loads(request.content)
    delay_seconds = json.loads(body["input"])["syntheticInvestigationFacts"]["delaySeconds"]
    review_required = delay_seconds >= 86_400
    cached_tokens = 3 if include_cache else None
    usage: dict[str, object] = {
        "input_tokens": 20,
        "output_tokens": 8,
        "total_tokens": 28,
    }
    if include_cache:
        usage["input_tokens_details"] = {"cached_tokens": cached_tokens}
    usage["output_tokens_details"] = {"reasoning_tokens": 0}
    return {
        "id": "response-synthetic",
        "object": "response",
        "created_at": 1_787_616_000,
        "status": "completed",
        "model": "deepseek-v4-flash-202608",
        "system_fingerprint": "fingerprint-synthetic",
        "output": [
            {
                "id": "message-synthetic",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "compensationReviewRequired": review_required,
                                "reasonCode": (
                                    "LOGISTICS_DELAY" if review_required else "DELAY_UNDER_24_HOURS"
                                ),
                            }
                        ),
                    }
                ],
            }
        ],
        "usage": usage,
        "error": None,
        "incomplete_details": None,
    }


def _environment() -> dict[str, str]:
    return {
        "DEEPSEEK_REAL_EVALUATION": ISSUE_125_OPT_IN,
        "DEEPSEEK_API_KEY": "issue-125-test-secret",
        "DEEPSEEK_MODEL": "deepseek-v4-flash",
    }


@pytest.mark.asyncio
async def test_real_entrypoint_reuses_frozen_dataset_and_emits_only_aggregate_contract() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=_completed_response(request))

    report = await run_real_evaluation(
        _environment(),
        transport=httpx.MockTransport(handler),
        pricing_observed_at=datetime(2026, 8, 25, 8, 0, tzinfo=UTC),
    )
    rendered = json.dumps(report, ensure_ascii=False)

    assert len(requests) == 55
    assert report["evaluation"]["datasetVersion"] == "b0-synthetic-evaluation-v1"
    assert report["evaluation"]["scenarioCount"] == 60
    assert report["evaluation"]["admitted"] is True
    assert report["contractChecks"] == {
        "strictSchema": True,
        "completedStatus": True,
        "thinkingDisabled": True,
        "allowedParametersOnly": True,
        "requestTracking": True,
        "actualResponseShape": True,
        "usageReported": True,
        "cacheReported": True,
    }
    assert report["attempts"] == {"actual": 55, "maximum": 55, "retries": 0}
    assert report["pricingVersion"] == "deepseek-time-of-use-2026-08-25"
    assert report["pricingTier"] == "peak"
    assert report["pricingObservedAtUtc"] == "2026-08-25T08:00:00Z"
    assert report["pricingUsdPerMillionTokens"] == {
        "cachedInput": 0.014,
        "uncachedInput": 0.44,
        "output": 1.32,
    }
    assert report["usage"] == {
        "inputTokens": 1100,
        "outputTokens": 440,
        "totalTokens": 1540,
        "cachedInputTokens": 165,
        "cacheHitAttempts": 55,
        "measuredAttempts": 55,
        "unmeasuredAttempts": 0,
    }
    assert report["blockedReason"] is None
    assert "issue-125-test-secret" not in rendered
    assert "ORDER-EVAL" not in rendered
    assert "syntheticInvestigationFacts" not in rendered
    assert "response-synthetic" not in rendered
    assert "fingerprint-synthetic" not in rendered


def test_time_of_use_pricing_uses_off_peak_rates_outside_weekday_windows() -> None:
    tier, pricing = real_evaluation.deepseek_flash_pricing_at(
        datetime(2026, 8, 25, 4, 0, tzinfo=UTC)
    )

    assert tier == "off-peak"
    assert pricing.input_usd_per_million_tokens == 0.22
    assert pricing.cached_input_usd_per_million_tokens == 0.007
    assert pricing.output_usd_per_million_tokens == 0.66


def test_time_of_use_pricing_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        real_evaluation.deepseek_flash_pricing_at(datetime(2026, 8, 25, 8, 0))


@pytest.mark.asyncio
async def test_balance_failure_stops_after_one_request_without_leaking_payload() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            402,
            json={"error": {"message": "balance plus issue-125-test-secret"}},
        )

    report = await run_real_evaluation(_environment(), transport=httpx.MockTransport(handler))

    assert calls == 1
    assert report["blockedReason"] == "INSUFFICIENT_BALANCE"
    assert report["evaluation"] is None
    assert report["attempts"] == {"actual": 1, "maximum": 55, "retries": 0}
    assert "issue-125-test-secret" not in json.dumps(report)


@pytest.mark.asyncio
async def test_supplier_failure_does_not_retry_and_fails_fast() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"error": {"message": "unavailable"}})

    report = await run_real_evaluation(_environment(), transport=httpx.MockTransport(handler))

    assert calls == 1
    assert report["blockedReason"] == "SUPPLIER_UNAVAILABLE"
    assert report["attempts"] == {"actual": 1, "maximum": 55, "retries": 0}


@pytest.mark.asyncio
async def test_deterministic_provider_rejection_also_fails_fast() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": {"message": "invalid request"}})

    report = await run_real_evaluation(_environment(), transport=httpx.MockTransport(handler))

    assert calls == 1
    assert report["blockedReason"] == "SUPPLIER_REQUEST_REJECTED"
    assert report["attempts"] == {"actual": 1, "maximum": 55, "retries": 0}


@pytest.mark.asyncio
async def test_whole_evaluation_deadline_audits_the_cancelled_in_flight_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        raise AssertionError("the whole-evaluation deadline must cancel the request")

    monkeypatch.setattr(real_evaluation, "_WHOLE_EVALUATION_DEADLINE_SECONDS", 0.01)
    report = await run_real_evaluation(_environment(), transport=httpx.MockTransport(handler))

    assert report["blockedReason"] == "EVALUATION_DEADLINE_EXCEEDED"
    assert report["attempts"] == {"actual": 1, "maximum": 55, "retries": 0}
    assert report["usage"]["measuredAttempts"] == 0
    assert report["usage"]["unmeasuredAttempts"] == 1


@pytest.mark.asyncio
async def test_model_refusal_is_aggregated_instead_of_misreported_as_supplier_block() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            payload = _completed_response(request)
            payload["output"] = [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "refusal", "refusal": "cannot comply"}],
                }
            ]
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json=_completed_response(request))

    report = await run_real_evaluation(_environment(), transport=httpx.MockTransport(handler))

    assert calls == 55
    assert report["blockedReason"] is None
    assert report["evaluation"]["failureCounts"] == {"REFUSAL": 1}
    assert report["evaluation"]["admitted"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"DEEPSEEK_API_KEY": ""}, "MISSING_API_KEY"),
        ({"DEEPSEEK_MODEL": "deepseek-v4-pro"}, "UNSUPPORTED_MODEL"),
        ({"DEEPSEEK_REAL_EVALUATION": ""}, "OPT_IN_REQUIRED"),
    ],
)
async def test_entrypoint_requires_key_flash_and_exact_opt_in(
    changes: dict[str, str], reason: str
) -> None:
    environment = {**_environment(), **changes}

    with pytest.raises(RealEvaluationBlocked, match=reason):
        await run_real_evaluation(environment, transport=httpx.MockTransport(lambda _: None))
