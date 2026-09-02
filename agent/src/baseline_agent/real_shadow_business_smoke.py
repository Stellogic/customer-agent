from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg

from baseline_agent.customer_intake_smoke import create_customer_ticket
from baseline_agent.deepseek_real_evaluation import (
    DEEPSEEK_PRICING_VERSION,
    deepseek_flash_pricing_at,
)
from baseline_agent.real_shadow_evaluation import (
    RealShadowScenarioResult,
    build_real_shadow_report,
    supplier_block_reason,
)

_TEMPLATES = {
    "normal": "ORDER-DELAY-001",
    "boundary-24h": "ORDER-DELAY-EXECUTION-10",
    "ineligible-under-24h": "ORDER-DELAY-UNDER-24",
}
_FAULTS = {
    "refusal": "MODEL_REFUSAL",
    "timeout": "READ_TIMEOUT",
    "invalid-output": "INVALID_JSON",
}
_COMPARISON_SAFE_FIELDS = {
    "model",
    "prompt_version",
    "schema_version",
    "outcome",
    "failure_classification",
    "latency_ms",
    "provider_attempts",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_input_tokens",
    "contract_valid",
    "provider_http_status",
}
_COMPARISON_WAIT_SECONDS = 10
_COMPARISON_POLL_SECONDS = 0.25
_REPORT_FIELDS = {
    "schemaVersion",
    "candidateModel",
    "priorContractAdmitted",
    "pricingVersion",
    "pricingTier",
    "limits",
    "scenarioIds",
    "attempts",
    "auditEvidence",
    "comparisonEvidence",
    "metrics",
    "usage",
    "failureSimulations",
    "admittedForFormalMode",
    "blockedReason",
    "startedAtUtc",
    "endedAtUtc",
}
_UNSAFE_EVIDENCE_FIELDS = {
    "apiKey",
    "authorization",
    "prompt",
    "instructions",
    "input",
    "output",
    "response",
    "ticketId",
    "orderReference",
    "generationId",
    "comparisonId",
    "providerResponseId",
    "internalCallId",
    "attemptId",
    "systemFingerprint",
}


def _expect(response: httpx.Response, status: int) -> None:
    if response.status_code != status:
        raise RuntimeError(f"business shadow request failed with HTTP {response.status_code}")


def _login(client: httpx.Client, spring_url: str) -> None:
    anonymous = client.get(f"{spring_url}/api/auth/csrf")
    _expect(anonymous, 200)
    token = anonymous.json()
    login = client.post(
        f"{spring_url}/api/auth/login",
        headers={token["headerName"]: token["token"]},
        data={"username": "customer-demo", "password": "local-demo-password"},
    )
    _expect(login, 204)
    current = client.get(f"{spring_url}/api/auth/csrf")
    _expect(current, 200)
    current_token = current.json()
    client.headers[current_token["headerName"]] = current_token["token"]


def _clone_order(connection: psycopg.Connection[Any], template: str, clone: str) -> None:
    connection.execute(
        "insert into synthetic_order ("
        "order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds, "
        "paid, cancelled, fully_refunded, existing_compensation, policy_version, "
        "available_compensation_amount) "
        "select %s, customer_id, paid_amount, currency, delay_hours, delay_seconds, "
        "paid, cancelled, fully_refunded, existing_compensation, policy_version, "
        "available_compensation_amount from synthetic_order where order_reference = %s",
        (clone, template),
    )


def _wait_for_generation(connection_uri: str, ticket_id: str) -> tuple[str, str, dict[str, object]]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        with psycopg.connect(connection_uri) as connection:
            row = connection.execute(
                "select g.id::text, g.thread_id::text, g.status, s.status "
                "from agent_processing_generation g "
                "join agent_submission s on s.generation_id = g.id "
                "where g.ticket_id = %s::uuid",
                (ticket_id,),
            ).fetchone()
            if row and row[2] in {"COMPLETED", "INVALIDATED"} and row[3] == "COMPLETED":
                side_effects = _side_effects(connection, ticket_id, row[0])
                return row[0], row[1], side_effects
        time.sleep(0.25)
    raise RuntimeError("business shadow generation did not reach a terminal state")


def _side_effects(
    connection: psycopg.Connection[Any], ticket_id: str, generation_id: str
) -> dict[str, object]:
    row = connection.execute(
        "select t.lifecycle_state, t.handling_mode, "
        "(select count(*) from agent_processing_generation g where g.ticket_id = t.id), "
        "(select count(*) from compensation_proposal_revision p where p.ticket_id = t.id), "
        "(select count(*) from public_message m where m.ticket_id = t.id), "
        "(select count(*) from audit_event a where a.ticket_id = t.id), "
        "(select count(*) from agent_command_request c where c.generation_id = %s::uuid) "
        "from support_ticket t where t.id = %s::uuid",
        (generation_id, ticket_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("business shadow ticket disappeared")
    return {
        "lifecycleState": row[0],
        "handlingMode": row[1],
        "generationCount": row[2],
        "proposalCount": row[3],
        "publicMessageCount": row[4],
        "auditEventCount": row[5],
        "agentCommandCount": row[6],
    }


def _read_comparison(agent_url: str, thread_id: str) -> dict[str, str]:
    deadline = time.monotonic() + _COMPARISON_WAIT_SECONDS
    while True:
        response = httpx.get(
            f"{agent_url}/threads/{thread_id}/state",
            headers={
                "Authorization": f"Bearer {os.environ['SPRING_TO_AGENT_TOKEN']}",
                "X-Spring-Principal": "spring-system",
            },
            timeout=20,
        )
        _expect(response, 200)
        comparison = response.json()["values"].get("shadow_comparison")
        if isinstance(comparison, dict):
            return {field: str(comparison.get(field, "")) for field in _COMPARISON_SAFE_FIELDS}
        if time.monotonic() >= deadline:
            raise RuntimeError("business shadow comparison is missing from LangGraph checkpoint")
        time.sleep(_COMPARISON_POLL_SECONDS)


def _run_scenario(scenario_id: str, template: str, phase: str, run_id: str) -> dict[str, object]:
    spring_url = os.environ["SPRING_INTERNAL_URL"]
    database_uri = os.environ["SPRING_SHADOW_DATABASE_URI"]
    order_reference = f"I126-{run_id}-{phase}-{scenario_id}".upper()
    with psycopg.connect(database_uri) as connection:
        _clone_order(connection, template, order_reference)
    with httpx.Client(timeout=20) as client:
        _login(client, spring_url)
        response = create_customer_ticket(
            client,
            spring_url,
            str(uuid.uuid4()),
            order_reference,
            "合成客服工单真实 shadow 验证",
        )
        _expect(response, 201)
        ticket_id = response.json()["ticketId"]
    _, thread_id, side_effects = _wait_for_generation(database_uri, ticket_id)
    result: dict[str, object] = {"scenarioId": scenario_id, "sideEffects": side_effects}
    if phase != "control":
        result["comparison"] = _read_comparison(os.environ["AGENT_SERVER_URL"], thread_id)
    return result


def _write_phase(path: Path, phase: str, run_id: str, fault: str | None) -> None:
    started = datetime.now(UTC)
    if phase == "control":
        scenarios = [
            _run_scenario(scenario_id, template, phase, run_id)
            for scenario_id, template in _TEMPLATES.items()
        ]
    elif phase == "real":
        scenarios = []
        for scenario_id, template in _TEMPLATES.items():
            result = _run_scenario(scenario_id, template, phase, run_id)
            scenarios.append(result)
            comparison = result.get("comparison")
            if isinstance(comparison, dict):
                reason = supplier_block_reason(comparison)
                if reason is not None:
                    _write_phase_payload(path, phase, fault, started, scenarios)
                    raise RuntimeError(reason)
    elif phase == "fault" and fault in _FAULTS:
        scenarios = [_run_scenario(fault, _TEMPLATES["normal"], f"fault-{fault}", run_id)]
    else:
        raise ValueError("unsupported business shadow phase")
    _write_phase_payload(path, phase, fault, started, scenarios)


def _write_phase_payload(
    path: Path,
    phase: str,
    fault: str | None,
    started: datetime,
    scenarios: list[dict[str, object]],
) -> None:
    payload = {
        "phase": phase,
        "fault": fault,
        "startedAtUtc": started.isoformat().replace("+00:00", "Z"),
        "endedAtUtc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scenarios": scenarios,
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _aggregate(evidence_dir: Path) -> dict[str, object]:
    control = _load(evidence_dir / "control.json")
    real = _load(evidence_dir / "real.json")
    controls = {
        item["scenarioId"]: item["sideEffects"]
        for item in control["scenarios"]  # type: ignore[index,union-attr]
    }
    results: list[RealShadowScenarioResult] = []
    for item in real["scenarios"]:  # type: ignore[union-attr]
        results.append(
            RealShadowScenarioResult(
                scenario_id=item["scenarioId"],
                comparison=item["comparison"],
                side_effects_match_control=(item["sideEffects"] == controls[item["scenarioId"]]),
                real_model_invoked=True,
            )
        )
    for fault, expected in _FAULTS.items():
        payload = _load(evidence_dir / f"fault-{fault}.json")
        item = payload["scenarios"][0]  # type: ignore[index]
        results.append(
            RealShadowScenarioResult(
                scenario_id=fault,
                comparison=item["comparison"],
                side_effects_match_control=(item["sideEffects"] == controls["normal"]),
                real_model_invoked=False,
                expected_failure_classification=expected,
            )
        )
    started = datetime.fromisoformat(str(real["startedAtUtc"]).replace("Z", "+00:00"))
    ended = datetime.fromisoformat(str(real["endedAtUtc"]).replace("Z", "+00:00"))
    start_tier, pricing = deepseek_flash_pricing_at(started)
    end_tier, _ = deepseek_flash_pricing_at(ended)
    report = build_real_shadow_report(
        results,
        pricing=pricing,
        pricing_version=DEEPSEEK_PRICING_VERSION,
        pricing_tier=start_tier,
        prior_contract_admitted=(
            os.environ.get("DEEPSEEK_PRIOR_CONTRACT_ADMITTED") == "issue-125-admitted"
        ),
    )
    if start_tier != end_tier:
        report["admittedForFormalMode"] = False
        report["blockedReason"] = "PRICING_WINDOW_CHANGED"
    report["startedAtUtc"] = str(real["startedAtUtc"])
    report["endedAtUtc"] = str(real["endedAtUtc"])
    return report


def persist_sanitized_report(path: Path, report: dict[str, object]) -> None:
    unexpected = set(report) - _REPORT_FIELDS
    if unexpected:
        raise ValueError("unsafe evidence field")

    def validate(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in _UNSAFE_EVIDENCE_FIELDS:
                    raise ValueError("unsafe evidence field")
                validate(child)
        elif isinstance(value, list):
            for child in value:
                validate(child)

    validate(report)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["control", "real", "fault", "aggregate"], required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--fault", choices=sorted(_FAULTS))
    parser.add_argument("--evidence-dir", type=Path, default=Path("/evidence"))
    parser.add_argument("--report-path", type=Path)
    arguments = parser.parse_args()
    if arguments.phase == "aggregate":
        report = _aggregate(arguments.evidence_dir)
        if arguments.report_path is not None:
            persist_sanitized_report(arguments.report_path, report)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if not report["admittedForFormalMode"]:
            raise SystemExit(2)
        return
    if not arguments.run_id or not arguments.run_id.isalnum():
        raise SystemExit("controlled run id is required")
    output = arguments.evidence_dir / (
        f"fault-{arguments.fault}.json" if arguments.phase == "fault" else f"{arguments.phase}.json"
    )
    _write_phase(output, arguments.phase, arguments.run_id, arguments.fault)


if __name__ == "__main__":
    _main()
