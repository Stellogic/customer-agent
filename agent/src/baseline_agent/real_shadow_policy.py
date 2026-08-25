from __future__ import annotations

from dataclasses import dataclass

from baseline_agent.deepseek_investigation_model import DEEPSEEK_FLASH_MODEL


@dataclass(frozen=True)
class RealShadowProviderPolicy:
    candidate_model: str
    connect_timeout_seconds: int
    read_timeout_seconds: int
    call_deadline_seconds: int
    maximum_attempts_per_scenario: int
    maximum_real_provider_attempts: int
    maximum_output_tokens: int


REAL_SHADOW_PROVIDER_POLICY = RealShadowProviderPolicy(
    candidate_model=DEEPSEEK_FLASH_MODEL,
    connect_timeout_seconds=3,
    read_timeout_seconds=12,
    call_deadline_seconds=20,
    maximum_attempts_per_scenario=1,
    maximum_real_provider_attempts=6,
    maximum_output_tokens=128,
)

REQUIRED_REAL_SHADOW_SCENARIOS = frozenset({"normal", "boundary-24h", "ineligible-under-24h"})
