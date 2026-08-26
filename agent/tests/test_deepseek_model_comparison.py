from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from baseline_agent.deepseek_model_comparison import (
    ISSUE_130_OPT_IN,
    ModelComparisonBlocked,
    deepseek_pricing_at,
    run_model_comparison,
)


def _environment() -> dict[str, str]:
    return {
        "DEEPSEEK_MODEL_COMPARISON": ISSUE_130_OPT_IN,
        "DEEPSEEK_API_KEY": "issue-130-test-secret",
    }


def _completed_response(request: httpx.Request) -> dict[str, object]:
    body = json.loads(request.content)
    delay_seconds = json.loads(body["input"])["syntheticInvestigationFacts"]["delaySeconds"]
    model = body["model"]
    return {
        "id": f"response-{model}",
        "object": "response",
        "created_at": 1_787_616_000,
        "status": "completed",
        "model": f"{model}-20260813",
        "system_fingerprint": f"fingerprint-{model}",
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
                                "compensationReviewRequired": delay_seconds >= 86_400,
                                "reasonCode": (
                                    "LOGISTICS_DELAY"
                                    if delay_seconds >= 86_400
                                    else "DELAY_UNDER_24_HOURS"
                                ),
                            }
                        ),
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 8,
            "total_tokens": 28,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "error": None,
        "incomplete_details": None,
    }


@pytest.mark.asyncio
async def test_comparison_uses_identical_full_dataset_and_redacted_aggregate_report() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=_completed_response(request))

    report = await run_model_comparison(
        _environment(),
        transport=httpx.MockTransport(handler),
        pricing_observed_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
    )
    rendered = json.dumps(report, ensure_ascii=False)

    assert len(requests) == 110
    assert {request["model"] for request in requests} == {
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    }
    flash_requests = [request for request in requests if request["model"] == "deepseek-v4-flash"]
    pro_requests = [request for request in requests if request["model"] == "deepseek-v4-pro"]
    assert [{**request, "model": None} for request in flash_requests] == [
        {**request, "model": None} for request in pro_requests
    ]
    assert report["dataset"] == {
        "version": "b0-synthetic-evaluation-v1",
        "repetitions": 5,
        "scenarioCountPerModel": 60,
        "providerAttemptsPerModel": 55,
        "identicalForAllCandidates": True,
    }
    assert report["sharedContract"] == {
        "promptVersion": "investigation-judgment-v1",
        "schemaVersion": "investigation-judgment-v1",
        "thinking": "disabled",
        "strictJsonSchema": True,
        "maximumAttemptsPerScenario": 1,
    }
    assert report["spend"]["maximumCny"] == 6.0
    assert report["spend"]["actualCny"] < 6.0
    assert report["blockedReason"] is None
    assert report["conclusion"]["decision"] == "CONTINUE_FLASH"
    for candidate in report["candidates"]:
        assert candidate["evaluation"]["scenarioCount"] == 60
        assert candidate["evaluation"]["metrics"]["schemaSuccessRate"] == 1.0
        assert "admitted" not in candidate["evaluation"]
        assert "thresholds" not in candidate["evaluation"]
        assert candidate["attempts"] == {"actual": 55, "maximum": 55, "retries": 0}
        assert candidate["observedProvider"]["responseModels"]
        assert candidate["observedProvider"]["backendFingerprints"]
        assert candidate["observedProvider"]["backendFingerprintReportedAttempts"] == 55
        assert candidate["observedProvider"]["backendFingerprintMissingAttempts"] == 0
    assert "issue-130-test-secret" not in rendered
    assert "ORDER-EVAL" not in rendered
    assert "syntheticInvestigationFacts" not in rendered
    assert "response-deepseek" not in rendered


@pytest.mark.asyncio
async def test_first_supplier_failure_stops_the_whole_comparison() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(402, json={"error": {"message": "secret balance detail"}})

    report = await run_model_comparison(_environment(), transport=httpx.MockTransport(handler))

    assert calls == 1
    assert report["blockedReason"] == "INSUFFICIENT_BALANCE"
    assert report["conclusion"]["decision"] == "INSUFFICIENT_EVIDENCE"
    assert report["attempts"]["actual"] == 1
    assert "secret balance detail" not in json.dumps(report)


def test_current_pricing_has_fixed_flash_and_pro_cny_rates() -> None:
    tier, pricing = deepseek_pricing_at(datetime(2026, 8, 26, 12, 0, tzinfo=UTC))

    assert tier == "off-peak"
    assert pricing["deepseek-v4-flash"].cached_input == 0.05
    assert pricing["deepseek-v4-flash"].uncached_input == 1.5
    assert pricing["deepseek-v4-flash"].output == 4.5
    assert pricing["deepseek-v4-pro"].cached_input == 0.15
    assert pricing["deepseek-v4-pro"].uncached_input == 4.5
    assert pricing["deepseek-v4-pro"].output == 13.5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"DEEPSEEK_API_KEY": ""}, "MISSING_API_KEY"),
        ({"DEEPSEEK_MODEL_COMPARISON": ""}, "OPT_IN_REQUIRED"),
        ({"DEEPSEEK_MODEL": "deepseek-v4-flash"}, "EXTERNAL_MODEL_SELECTION_FORBIDDEN"),
    ],
)
async def test_entrypoint_fixes_candidates_and_requires_exact_opt_in(
    changes: dict[str, str], reason: str
) -> None:
    with pytest.raises(ModelComparisonBlocked, match=reason):
        await run_model_comparison(
            {**_environment(), **changes}, transport=httpx.MockTransport(lambda _: None)
        )
