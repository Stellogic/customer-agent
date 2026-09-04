from __future__ import annotations

from collections.abc import Mapping

from baseline_agent.deepseek_intake_model import INTAKE_PROMPT_VERSION, DeepSeekIntakeModel
from baseline_agent.intake_model import FixedFakeIntakeModel, IntakeModel


def configured_intake_model(environment: Mapping[str, str]) -> tuple[IntakeModel, str]:
    mode = environment.get("INVESTIGATION_MODEL_MODE", "fixed-fake").strip().lower()
    if mode == "fixed-fake":
        return FixedFakeIntakeModel(), "fixed-fake-intake-v1"
    if mode in {"deepseek-formal", "real-shadow"}:
        return (
            DeepSeekIntakeModel.from_environment(dict(environment)),
            f"{mode}-{INTAKE_PROMPT_VERSION}",
        )
    raise ValueError(f"unsupported intake model mode: {mode}")
