from __future__ import annotations

from baseline_agent.deepseek_investigation_model import (
    DeepSeekFailureClassification,
    ModelCallAttemptRecord,
)


def supplier_block_reason(record: ModelCallAttemptRecord) -> str | None:
    if record.provider_http_status == 401:
        return "SUPPLIER_AUTHENTICATION_FAILED"
    if record.provider_http_status == 402:
        return "INSUFFICIENT_BALANCE"
    if record.provider_http_status in {403, 429}:
        return "SUPPLIER_REQUEST_BLOCKED"
    if record.provider_http_status is not None and record.provider_http_status >= 500:
        return "SUPPLIER_UNAVAILABLE"
    if record.provider_http_status is not None and record.provider_http_status >= 400:
        return "SUPPLIER_REQUEST_REJECTED"
    if record.failure_classification in {
        DeepSeekFailureClassification.CONNECTION_TIMEOUT,
        DeepSeekFailureClassification.READ_TIMEOUT,
        DeepSeekFailureClassification.DEADLINE_EXCEEDED,
        DeepSeekFailureClassification.TRANSIENT_PROVIDER_ERROR,
    }:
        return "SUPPLIER_NETWORK_FAILURE"
    if record.failure_classification is DeepSeekFailureClassification.PROVIDER_FAILED:
        return "SUPPLIER_FAILED"
    return None
