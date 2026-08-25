import pytest

from baseline_agent.formal_mode_business_smoke import _validate_success_state


def test_failed_success_expectation_reports_only_sanitized_terminal_state() -> None:
    state = {
        "generationStatus": "HANDED_OFF",
        "submissionStatus": "COMPLETED",
        "lifecycleState": "INVESTIGATING",
        "handlingMode": "HUMAN",
        "handoffReasonCode": "INVALID_MODEL_OUTPUT",
        "proposalCount": 0,
        "handoffRequestCount": 1,
        "threadId": "must-not-be-reported",
    }

    with pytest.raises(RuntimeError) as captured:
        _validate_success_state(state)

    message = str(captured.value)
    assert "HANDED_OFF" in message
    assert "INVALID_MODEL_OUTPUT" in message
    assert "proposalCount=0" in message
    assert "must-not-be-reported" not in message
    assert "threadId" not in message
