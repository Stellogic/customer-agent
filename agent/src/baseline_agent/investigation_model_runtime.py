from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from baseline_agent.deepseek_investigation_model import (
    DeepSeekResponsesConfig,
    DeepSeekResponsesInvestigationModel,
)
from baseline_agent.investigation_model import (
    FixedFakeInvestigationModel,
    InvestigationJudgmentFailure,
    InvestigationJudgmentFailureCode,
    InvestigationJudgmentModel,
)

_FAKE_MODE = "fixed-fake"
_FORMAL_MODE = "deepseek-formal"
_DISABLED_SHADOW_MODES = frozenset({"", "disabled"})


@dataclass(frozen=True)
class ConfiguredInvestigationModel:
    model: InvestigationJudgmentModel
    mode: str
    maximum_provider_attempts: int
    call_deadline_seconds: int


def configured_investigation_model(
    environment: Mapping[str, str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ConfiguredInvestigationModel:
    mode = environment.get("AGENT_INVESTIGATION_MODEL_MODE", _FAKE_MODE)
    shadow_mode = environment.get("AGENT_INVESTIGATION_SHADOW_MODE", "disabled")
    if mode == _FAKE_MODE:
        return ConfiguredInvestigationModel(
            model=FixedFakeInvestigationModel(),
            mode="fixed-fake-model-v1",
            maximum_provider_attempts=0,
            call_deadline_seconds=0,
        )
    if mode != _FORMAL_MODE or shadow_mode not in _DISABLED_SHADOW_MODES:
        raise _configuration_failure()

    config = DeepSeekResponsesConfig(
        api_key=environment.get("DEEPSEEK_API_KEY", ""),
        model=environment.get("DEEPSEEK_MODEL", ""),
        connect_timeout_seconds=3,
        read_timeout_seconds=12,
        deadline_seconds=20,
        max_attempts=2,
        retry_base_delay_seconds=0.2,
        max_output_tokens=128,
    )
    return ConfiguredInvestigationModel(
        model=DeepSeekResponsesInvestigationModel(config, transport=transport),
        mode="deepseek-v4-flash-formal-v1",
        maximum_provider_attempts=config.max_attempts,
        call_deadline_seconds=int(config.deadline_seconds),
    )


def _configuration_failure() -> InvestigationJudgmentFailure:
    return InvestigationJudgmentFailure(InvestigationJudgmentFailureCode.CONFIGURATION_ERROR)
