from __future__ import annotations

from collections.abc import Mapping

import httpx

from baseline_agent.core_validation_budget import configured_core_budget

from baseline_agent.deepseek_intake_model import INTAKE_PROMPT_VERSION, DeepSeekIntakeModel
from baseline_agent.intake_model import FixedFakeIntakeModel, IntakeModel


def configured_intake_model(
    environment: Mapping[str, str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[IntakeModel, str]:
    mode = environment.get("INVESTIGATION_MODEL_MODE", "fixed-fake").strip().lower()
    if mode == "fixed-fake":
        return FixedFakeIntakeModel(), "fixed-fake-intake-v1"
    if mode in {"deepseek-formal", "real-shadow"}:
        return (
            DeepSeekIntakeModel.from_environment(
                environment, transport=transport, budget=configured_core_budget(environment)
            ),
            f"{mode}-{INTAKE_PROMPT_VERSION}",
        )
    raise ValueError(f"unsupported intake model mode: {mode}")
