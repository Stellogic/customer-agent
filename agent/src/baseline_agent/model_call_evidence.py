from dataclasses import asdict
from enum import Enum

from baseline_agent.deepseek_investigation_model import (
    ModelCallAttemptRecord,
    estimate_flash_cost_micros,
)


def serialize_model_attempt(record: ModelCallAttemptRecord) -> dict[str, object]:
    attempt: dict[str, object] = {}
    for name, value in asdict(record).items():
        first, *rest = name.split("_")
        attempt[first + "".join(word.capitalize() for word in rest)] = (
            value.value if isinstance(value, Enum) else value
        )
    return attempt


def model_call_evidence(
    attempts: list[dict[str, object]], *, schema_version: str
) -> dict[str, object]:
    def total(field: str) -> int | None:
        values = [attempt.get(field) for attempt in attempts]
        if not values or any(not isinstance(value, int) for value in values):
            return None
        return sum(value for value in values if isinstance(value, int))

    input_tokens = total("inputTokens")
    output_tokens = total("outputTokens")
    tokens = total("totalTokens")
    complete = input_tokens is not None and output_tokens is not None and tokens is not None
    return {
        "schemaVersion": schema_version,
        "currency": "USD",
        "logicalCalls": len({attempt["internalCallId"] for attempt in attempts}),
        "providerAttempts": len(attempts),
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "tokens": tokens,
        "costMicros": (
            estimate_flash_cost_micros(input_tokens, output_tokens)
            if complete and input_tokens is not None and output_tokens is not None
            else None
        ),
        "usageComplete": complete,
        "failureClassification": next(
            (
                attempt["failureClassification"]
                for attempt in attempts
                if attempt.get("failureClassification")
            ),
            "",
        ),
        "attempts": attempts,
    }
