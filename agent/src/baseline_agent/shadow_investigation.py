from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum

import httpx

from baseline_agent.deepseek_investigation_model import (
    DEEPSEEK_FLASH_MODEL,
    INVESTIGATION_JUDGMENT_PROMPT_VERSION,
    INVESTIGATION_JUDGMENT_SCHEMA_VERSION,
    DeepSeekResponsesConfig,
    DeepSeekResponsesInvestigationModel,
)
from baseline_agent.investigation_model import (
    InvestigationJudgment,
    InvestigationJudgmentInput,
    InvestigationJudgmentModel,
)

_SHADOW_MODE_ENVIRONMENT_KEY = "AGENT_INVESTIGATION_SHADOW_MODE"


class ShadowComparisonOutcome(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ShadowCandidate:
    model: InvestigationJudgmentModel
    model_name: str
    prompt_version: str
    schema_version: str


@dataclass(frozen=True)
class ShadowComparisonRecord:
    comparison_id: str
    ticket_id: str
    generation_id: str
    model: str
    prompt_version: str
    schema_version: str
    outcome: ShadowComparisonOutcome

    def as_checkpoint_value(self) -> dict[str, str]:
        return {name: str(value) for name, value in asdict(self).items()}


def configured_shadow_candidate(
    environment: Mapping[str, str] | None = None,
) -> ShadowCandidate | None:
    values = os.environ if environment is None else environment
    mode = _configured_shadow_mode(values)
    if mode in {"", "disabled"}:
        return None
    if mode == "offline":
        config = DeepSeekResponsesConfig(api_key="offline-shadow-substitute")
        return ShadowCandidate(
            model=DeepSeekResponsesInvestigationModel(
                config,
                transport=httpx.MockTransport(_offline_supplier_response),
            ),
            model_name=DEEPSEEK_FLASH_MODEL,
            prompt_version=INVESTIGATION_JUDGMENT_PROMPT_VERSION,
            schema_version=INVESTIGATION_JUDGMENT_SCHEMA_VERSION,
        )
    if mode != "deepseek":
        raise ValueError("unsupported investigation shadow mode")
    config = DeepSeekResponsesConfig.from_environment(values)
    return ShadowCandidate(
        model=DeepSeekResponsesInvestigationModel(config),
        model_name=config.model,
        prompt_version=INVESTIGATION_JUDGMENT_PROMPT_VERSION,
        schema_version=INVESTIGATION_JUDGMENT_SCHEMA_VERSION,
    )


def shadow_mode_enabled(environment: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environment is None else environment
    return _configured_shadow_mode(values) not in {"", "disabled"}


def _configured_shadow_mode(environment: Mapping[str, str]) -> str:
    return environment.get(_SHADOW_MODE_ENVIRONMENT_KEY, "disabled").strip().lower()


def _offline_supplier_response(request: httpx.Request) -> httpx.Response:
    request_body = json.loads(request.content)
    model_input = json.loads(request_body["input"])
    delay_seconds = model_input["syntheticInvestigationFacts"]["delaySeconds"]
    compensation_required = delay_seconds >= 24 * 60 * 60
    reason_code = "LOGISTICS_DELAY" if compensation_required else "DELAY_UNDER_24_HOURS"
    judgment = json.dumps(
        {
            "compensationReviewRequired": compensation_required,
            "reasonCode": reason_code,
        },
        separators=(",", ":"),
    )
    return httpx.Response(
        200,
        json={
            "id": "offline-shadow-response",
            "status": "completed",
            "model": DEEPSEEK_FLASH_MODEL,
            "system_fingerprint": "offline-shadow-substitute-v1",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": judgment}],
                }
            ],
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "input_tokens_details": {"cached_tokens": 0},
            },
        },
    )


def failed_shadow_comparison(
    *, ticket_id: str, generation_id: str, candidate: ShadowCandidate
) -> ShadowComparisonRecord:
    return _comparison_record(
        ticket_id=ticket_id,
        generation_id=generation_id,
        candidate=candidate,
        outcome=ShadowComparisonOutcome.FAILED,
    )


async def compare_shadow_judgment(
    *,
    ticket_id: str,
    generation_id: str,
    model_input: InvestigationJudgmentInput,
    baseline: InvestigationJudgment,
    candidate: ShadowCandidate,
) -> ShadowComparisonRecord:
    outcome = ShadowComparisonOutcome.FAILED
    try:
        shadow = await candidate.model.judge(model_input)
        outcome = (
            ShadowComparisonOutcome.MATCH
            if shadow == baseline
            else ShadowComparisonOutcome.MISMATCH
        )
    except Exception:
        # Shadow is observational only. Provider, parsing, and configuration failures must
        # never alter the already-authoritative fake-model business path.
        pass
    return _comparison_record(
        ticket_id=ticket_id,
        generation_id=generation_id,
        candidate=candidate,
        outcome=outcome,
    )


def _comparison_record(
    *,
    ticket_id: str,
    generation_id: str,
    candidate: ShadowCandidate,
    outcome: ShadowComparisonOutcome,
) -> ShadowComparisonRecord:
    comparison_id = hashlib.sha256(
        (
            f"{ticket_id}\n{generation_id}\n{candidate.model_name}\n"
            f"{candidate.prompt_version}\n{candidate.schema_version}"
        ).encode()
    ).hexdigest()
    return ShadowComparisonRecord(
        comparison_id=comparison_id,
        ticket_id=ticket_id,
        generation_id=generation_id,
        model=candidate.model_name,
        prompt_version=candidate.prompt_version,
        schema_version=candidate.schema_version,
        outcome=outcome,
    )
