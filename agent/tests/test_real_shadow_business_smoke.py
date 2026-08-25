from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from baseline_agent import real_shadow_business_smoke


class _Response:
    status_code = 200

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def json(self) -> dict[str, object]:
        return {"values": self._values}


def test_shadow_comparison_waits_for_the_terminal_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        (
            _Response({}),
            _Response(
                {
                    "shadow_comparison": {
                        "model": "deepseek-v4-flash",
                        "outcome": "MATCH",
                        "failure_classification": "",
                        "provider_attempts": "1",
                        "provider_http_status": "200",
                    }
                }
            ),
        )
    )
    calls = 0

    def get(*_: object, **__: object) -> _Response:
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr(real_shadow_business_smoke.httpx, "get", get)
    monkeypatch.setattr(real_shadow_business_smoke.time, "sleep", lambda _: None)
    monkeypatch.setenv("SPRING_TO_AGENT_TOKEN", "offline-token")

    comparison = real_shadow_business_smoke._read_comparison(
        "http://agent-server",
        "synthetic-thread",
    )

    assert calls == 2
    assert comparison["model"] == "deepseek-v4-flash"
    assert comparison["outcome"] == "MATCH"
    assert comparison["provider_attempts"] == "1"
    assert comparison["provider_http_status"] == "200"


def test_only_sanitized_aggregate_evidence_can_be_persisted(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    report = {
        "schemaVersion": "issue-126-real-business-shadow-v1",
        "candidateModel": "deepseek-v4-flash",
        "auditEvidence": {
            "realProviderAttempts": 3,
            "failureClassifications": {"NONE": 3},
        },
        "comparisonEvidence": {"matches": 3, "mismatches": 0, "failed": 0},
        "admittedForFormalMode": True,
    }

    real_shadow_business_smoke.persist_sanitized_report(report_path, report)

    assert report_path.read_text(encoding="utf-8").endswith("\n")
    assert "deepseek-v4-flash" in report_path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe evidence field"):
        real_shadow_business_smoke.persist_sanitized_report(
            report_path,
            {**report, "ticketId": "must-not-persist"},
        )
