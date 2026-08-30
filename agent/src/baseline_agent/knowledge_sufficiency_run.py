"""仅固定合成开发72题的一次C回放;串行、无重试、共用持久化人民币账本。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from baseline_agent.knowledge_sufficiency import (
    ARCHIVE_SHA256,
    DATA_SHA256,
    REPO,
    SOURCE_SHA,
    SufficiencyBlocked,
    budget_plan,
    contract,
    development_rows,
    parse_response,
    replay_metrics,
    request_body,
    response_observation,
    sha256,
)

OPT_IN = "issue-190-synthetic-sufficiency-c-once"
PHASE = "seen_development"


def decision_diagnostic(text: str, api_key: str) -> dict[str, Any]:
    """仅取证已通过envelope检查的合成判定文本,不改变原解析或判定。"""
    def redact(value: str) -> str:
        if api_key:
            value = value.replace(json.dumps(api_key)[1:-1], "[REDACTED]")
            value = value.replace(api_key, "[REDACTED]")
        return value

    # 先脱敏再截断,避免凭据跨截断点留下前缀;hash针对完整脱敏文本。
    sanitized = redact(text)
    diagnostic: dict[str, Any] = {
        "output_text": sanitized[:4096],
        "sanitized_text_sha256": sha256(sanitized.encode("utf-8")),
        "sanitized_char_count": len(sanitized),
        "truncated": len(sanitized) > 4096,
        "top_level_type": None,
        "fields": [],
    }
    try:
        decision = json.loads(text)
    except json.JSONDecodeError:
        diagnostic["json_valid"] = False
        return diagnostic
    diagnostic.update(json_valid=True, top_level_type=type(decision).__name__)
    if isinstance(decision, dict):
        diagnostic["field_count"] = len(decision)
        diagnostic["fields"] = [
            {"name": redact(key)[:64], "type": type(value).__name__}
            for key, value in list(decision.items())[:16]
        ]
    return diagnostic


def write_json(path: Path, value: dict[str, Any]) -> None:
    """调用前预留和调用后结算都持久化;异常不清理尚未结算的预留。"""
    temporary = path.with_suffix(".pending-write")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


class ExperimentLedger:
    def __init__(self, path: Path, frozen: dict[str, Any]) -> None:
        self.path = path
        self.plan = budget_plan(frozen)
        if path.exists():
            self.state = json.loads(path.read_text(encoding="utf-8"))
            if self.state["schema"] != "issue190-sufficiency-cost-v1":
                raise SufficiencyBlocked("LEDGER_SCHEMA_MISMATCH")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.state = {
                "schema": "issue190-sufficiency-cost-v1",
                "prior_paid_micro_cny": 0,
                "prior_evidence": "issue190-logistic-fit-20260831b: paid_model_cost_cny=0",
                "phases": {},
                "identity": None,
                "attempts": [],
            }
            # 只在首次不存在时创建;所有worktree使用同一Git公共目录旁的账本。
            with path.open("x", encoding="utf-8") as output:
                json.dump(self.state, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())

    def totals(self) -> dict[str, int]:
        settled = self.state["prior_paid_micro_cny"] + sum(
            entry["charged_upper_micro_cny"]
            for entry in self.state["attempts"]
            if entry["status"] == "SETTLED"
        )
        pending = sum(
            entry["reserved_micro_cny"]
            for entry in self.state["attempts"]
            if entry["status"] == "PENDING"
        )
        return {"settled_upper_micro_cny": settled, "unsettled_reserved_micro_cny": pending}

    def begin(self, run_id: str, assets: dict[str, str]) -> None:
        if self.totals()["unsettled_reserved_micro_cny"]:
            raise SufficiencyBlocked("UNSETTLED_COST_REQUIRES_COORDINATOR")
        if PHASE in self.state["phases"]:
            raise SufficiencyBlocked("DEVELOPMENT_ALREADY_STARTED_NO_RETRY")
        self.state["phases"][PHASE] = {
            "run_id": run_id,
            "status": "RUNNING",
            "assets": assets,
        }
        write_json(self.path, self.state)

    def reserve(self, query_id: str, request_sha: str) -> dict[str, Any]:
        totals = self.totals()
        if totals["unsettled_reserved_micro_cny"]:
            raise SufficiencyBlocked("UNSETTLED_COST_REQUIRES_COORDINATOR")
        reserved = self.plan["per_call_reservation_micro_cny"]
        if totals["settled_upper_micro_cny"] + reserved > self.plan["total_budget_micro_cny"]:
            raise SufficiencyBlocked("BUDGET_INCOMPLETE")
        phase_attempts = [entry for entry in self.state["attempts"] if entry["phase"] == PHASE]
        if len(phase_attempts) >= 72 or any(
            entry["query_id"] == query_id for entry in phase_attempts
        ):
            raise SufficiencyBlocked("CALL_LIMIT_NO_RETRY")
        entry = {
            "phase": PHASE,
            "query_id": query_id,
            "request_sha256": request_sha,
            "status": "PENDING",
            "reserved_micro_cny": reserved,
        }
        self.state["attempts"].append(entry)
        write_json(self.path, self.state)
        return entry

    def settle(self, entry: dict[str, Any], observation: dict[str, Any]) -> None:
        entry["observation"] = observation
        if observation.get("usage_trusted") is True:
            charged = observation["usage_upper_micro_cny"]
            if not 0 <= charged <= entry["reserved_micro_cny"]:
                raise SufficiencyBlocked("COST_BOUND_VIOLATED", observation)
            entry.update(status="SETTLED", charged_upper_micro_cny=charged)
        write_json(self.path, self.state)

    def finish(self, status: str) -> None:
        self.state["phases"][PHASE]["status"] = status
        write_json(self.path, self.state)


async def run_development(
    report: dict[str, Any],
    ledger: ExperimentLedger,
    frozen: dict[str, Any],
    *,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    rows = development_rows()
    bodies = [request_body(row, frozen) for row in rows]
    ledger.begin(report["run_id"], frozen["asset_sha256"])
    report["rows"] = []
    config = frozen["config"]
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15, connect=3),
        transport=transport,
        follow_redirects=False,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        for row, body in zip(rows, bodies, strict=True):
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            entry = ledger.reserve(row["id"], sha256(encoded))
            started = time.perf_counter()
            observation: dict[str, Any] = {"usage_trusted": False}
            try:
                response = await asyncio.wait_for(
                    client.post(
                        config["endpoint"],
                        content=encoded,
                        headers={"Content-Type": "application/json"},
                    ),
                    timeout=config["call_deadline_seconds"],
                )
                observation["http_status"] = response.status_code
                if response.status_code != 200:
                    codes = {401: "SUPPLIER_AUTHENTICATION_FAILED", 402: "INSUFFICIENT_BALANCE"}
                    raise SufficiencyBlocked(
                        codes.get(response.status_code, "SUPPLIER_HTTP_FAILED"), observation
                    )
                try:
                    payload = response.json()
                except json.JSONDecodeError:
                    raise SufficiencyBlocked("PROVIDER_INVALID_JSON", observation) from None
                if not isinstance(payload, dict):
                    raise SufficiencyBlocked("PROVIDER_INVALID_SHAPE", observation)
                elapsed = round((time.perf_counter() - started) * 1000)
                observation = response_observation(payload, elapsed)
                observation["http_status"] = response.status_code
                identity = ledger.state["identity"]
                parsed = parse_response(
                    payload,
                    row,
                    expected_identity=(identity[0], identity[1]) if identity is not None else None,
                    duration_ms=elapsed,
                )
                if identity is None:
                    ledger.state["identity"] = [
                        observation["response_model"],
                        observation["system_fingerprint"],
                    ]
                report["rows"].append(
                    {
                        "query_id": row["id"],
                        "topic": row["topic"],
                        "kind": row["kind"],
                        "request_sha256": sha256(encoded),
                        "decision": parsed["decision"],
                        "observation": observation,
                        "accepted_chunk_ids": [hit["chunkId"] for hit in row["fusedCandidates"]]
                        if parsed["decision"]["sufficient"]
                        else [],
                    }
                )
            except (TimeoutError, httpx.TransportError):
                observation["failure"] = "SUPPLIER_TIMEOUT_OR_TRANSPORT_ERROR"
                raise SufficiencyBlocked("SUPPLIER_TIMEOUT_OR_TRANSPORT_ERROR") from None
            except SufficiencyBlocked as error:
                observation["failure"] = str(error)
                if str(error) in {
                    "INVALID_DECISION_JSON", "INVALID_DECISION_SCHEMA", "INVALID_EVIDENCE"
                }:
                    # 这些错误仅在固定envelope/单个output_text检查通过后出现。
                    # 不复制供应商error正文、请求头或整个响应,仍由finally结算并抛原错。
                    observation["decision_diagnostic"] = decision_diagnostic(
                        payload["output"][0]["content"][0]["text"], api_key
                    )
                raise
            finally:
                observation["duration_ms"] = round((time.perf_counter() - started) * 1000)
                ledger.settle(entry, observation)
    decisions = [entry["decision"]["sufficient"] for entry in report["rows"]]
    report.update(replay_metrics(rows, decisions))
    report["by_topic"] = {
        topic: {
            "count": sum(row["topic"] == topic for row in rows),
            "accepted": sum(
                accepted
                for row, accepted in zip(rows, decisions, strict=True)
                if row["topic"] == topic
            ),
        }
        for topic in sorted({row["topic"] for row in rows})
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("run-id", "head-sha", "base-sha", "pricing-and-context-verified-date"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # 正式入口必须验证活的共享锁;没有任何自建锁身份或无锁付费模式。
    if os.environ.get("CUSTOMER_AGENT_TEST_GATE_IDENTITY"):
        raise SufficiencyBlocked("CUSTOM_LOCK_IDENTITY_NOT_ALLOWED")
    locked = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPO / "scripts/test-gate-lock.ps1"),
            "-AssertInherited",
        ],
        capture_output=True,
        check=False,
    )
    if locked.returncode != 0:
        raise SufficiencyBlocked("TEST_GATE_LOCK_REQUIRED")
    if os.environ.get("KNOWLEDGE_SUFFICIENCY_EXPERIMENT") != OPT_IN:
        raise SufficiencyBlocked("EXPERIMENT_OPT_IN_REQUIRED")
    if args.pricing_and_context_verified_date != datetime.now(UTC).date().isoformat():
        raise SufficiencyBlocked("CURRENT_PRICING_REVIEW_REQUIRED")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key.strip():
        raise SufficiencyBlocked("MISSING_API_KEY")
    git_dir = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    ledger_path = Path(git_dir).parent / ".local/issue190-sufficiency/cost-ledger.json"
    frozen = contract()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        started = time.perf_counter()
        report: dict[str, Any] = {
            "schema": "knowledge-sufficiency-experiment-run-v1",
            "status": "ERROR",
            "run_id": args.run_id,
            "head_sha": args.head_sha,
            "base_sha": args.base_sha,
            "retrieval_observation_head_sha": SOURCE_SHA,
            "archive_sha256": ARCHIVE_SHA256,
            "dataset_sha256": DATA_SHA256,
            "partition": "seen_development_not_unseen",
            "query_count": 72,
            "contract": frozen,
            "budget_plan": budget_plan(frozen),
            "pricing_and_context_verified_date": args.pricing_and_context_verified_date,
            "environment": {"python": platform.python_version(), "platform": platform.platform()},
            "rows": [],
            "metrics": None,
        }
        ledger: ExperimentLedger | None = None
        try:
            ledger = ExperimentLedger(ledger_path, frozen)
            asyncio.run(run_development(report, ledger, frozen, api_key=api_key))
        except SufficiencyBlocked as error:
            report.update(status="STOPPED", stopped_reason=str(error))
        except Exception as error:
            # 不记录异常正文,避免凭据/供应商payload进入归档。
            report.update(status="ERROR", error_type=type(error).__name__)
        finally:
            if ledger is not None:
                phase = ledger.state["phases"].get(PHASE, {})
                if phase.get("run_id") == args.run_id and phase.get("status") == "RUNNING":
                    ledger.finish(report["status"])
                report["cost_ledger"] = ledger.state
                report["cost_totals"] = ledger.totals()
            report["elapsed_seconds"] = time.perf_counter() - started
            json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
