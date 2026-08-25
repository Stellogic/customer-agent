from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from baseline_agent.deepseek_investigation_action_model import (
    DeepSeekActionConfig,
    DeepSeekResponsesInvestigationActionModel,
)
from baseline_agent.deepseek_investigation_model import DEEPSEEK_FLASH_MODEL
from baseline_agent.investigation_action_loop import (
    ActionLoopFailure,
    ActionLoopFailureCode,
    DeterministicActionModel,
    InvestigationActionModel,
)

_DETERMINISTIC_MODE = "deterministic"
_FORMAL_MODE = "deepseek-formal"


@dataclass(frozen=True)
class ConfiguredInvestigationActionModel:
    model: InvestigationActionModel
    mode: str
    maximum_attempts_per_action: int
    call_deadline_seconds: int


def configured_investigation_action_model(
    environment: Mapping[str, str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ConfiguredInvestigationActionModel:
    mode = environment.get("AGENT_INVESTIGATION_ACTION_MODEL_MODE", _DETERMINISTIC_MODE)
    if mode == _DETERMINISTIC_MODE:
        return ConfiguredInvestigationActionModel(
            model=DeterministicActionModel(),
            mode="deterministic-action-model-v1",
            maximum_attempts_per_action=1,
            call_deadline_seconds=0,
        )
    if mode != _FORMAL_MODE or environment.get("DEEPSEEK_MODEL") != DEEPSEEK_FLASH_MODEL:
        raise ActionLoopFailure(ActionLoopFailureCode.MODEL_CALL_FAILED)
    config = DeepSeekActionConfig.from_environment(environment)
    return ConfiguredInvestigationActionModel(
        model=DeepSeekResponsesInvestigationActionModel(config, transport=transport),
        mode="deepseek-v4-flash-action-formal-v1",
        maximum_attempts_per_action=config.max_attempts,
        call_deadline_seconds=round(config.deadline_seconds),
    )
