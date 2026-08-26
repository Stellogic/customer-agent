from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from baseline_agent.customer_communication_model import (
    CustomerCommunicationFailure,
    CustomerCommunicationFailureCode,
    CustomerCommunicationModel,
    FixedFakeCustomerCommunicationModel,
)
from baseline_agent.deepseek_customer_communication_model import (
    DeepSeekCustomerCommunicationConfig,
    DeepSeekResponsesCustomerCommunicationModel,
)
from baseline_agent.deepseek_investigation_model import DEEPSEEK_FLASH_MODEL

_FIXED_FAKE_MODE = "fixed-fake"
_FORMAL_MODE = "deepseek-formal"


@dataclass(frozen=True)
class ConfiguredCustomerCommunicationModel:
    model: CustomerCommunicationModel
    mode: str
    maximum_attempts: int
    call_deadline_seconds: int


def configured_customer_communication_model(
    environment: Mapping[str, str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ConfiguredCustomerCommunicationModel:
    mode = environment.get("AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE", _FIXED_FAKE_MODE)
    if mode == _FIXED_FAKE_MODE:
        return ConfiguredCustomerCommunicationModel(
            model=FixedFakeCustomerCommunicationModel(),
            mode="fixed-fake-customer-communication-v1",
            maximum_attempts=0,
            call_deadline_seconds=0,
        )
    if mode != _FORMAL_MODE or environment.get("DEEPSEEK_MODEL") != DEEPSEEK_FLASH_MODEL:
        raise CustomerCommunicationFailure(CustomerCommunicationFailureCode.INVALID_INPUT)
    config = DeepSeekCustomerCommunicationConfig.from_environment(environment)
    return ConfiguredCustomerCommunicationModel(
        model=DeepSeekResponsesCustomerCommunicationModel(config, transport=transport),
        mode="deepseek-v4-flash-customer-communication-formal-v1",
        maximum_attempts=config.max_attempts,
        call_deadline_seconds=round(config.deadline_seconds),
    )
