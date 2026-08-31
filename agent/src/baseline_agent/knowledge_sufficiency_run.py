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

from baseline_agent.knowledge_answerability import QUALITY
from baseline_agent.knowledge_sufficiency import (
    ARCHIVE_SHA256,
    CONTRACT_CHECK_LAYERS,
    DATA_SHA256,
    REPO,
    SOURCE_SHA,
    V2_ASSETS,
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
DIAGNOSTIC_OPT_IN = "issue-190-fifth-request-diagnostic-once"
DIAGNOSTIC_PHASE = "fifth_request_diagnostic_once"
FIFTH_QUERY_ID = "weaving-direct-3"
FIFTH_REQUEST_SHA = "d3a9e630949ed0093103ac435db610d9eacd9115c92be2e750be5914b056e20b"
ORIGINAL_LEDGER = (
    REPO / "docs/implementation/evidence/issue190-c-development-20260831a/cost-ledger.json"
)
ORIGINAL_LEDGER_SHA = "5cd9e0ef8ee6977f0897db31d4c00bfee498194b9456bc437ffe0776b79e8507"
REMAINING_OPT_IN = "issue-190-remaining67-diagnostic-once"
REMAINING_PHASE = "remaining67_diagnostic_once"
REMAINING_LEDGER = (
    REPO / "docs/implementation/evidence/issue190-c-fifth-diagnostic-20260831b/cost-ledger.json"
)
REMAINING_LEDGER_SHA = "0bd04be15c1c6e1eeb96f96cdadf994aa14b5a0f2d894e38c3426193896b40f8"
REMAINING_MANIFEST = Path(__file__).with_name("knowledge_sufficiency_remaining_v1.json")
REMAINING_MANIFEST_SHA = "d9e11464642afb0de4fe2b4cf170f62b298284f681f2f7843e5e53c349e13bf1"
V2_OPT_IN = "issue-190-c-v2-whole-development-once"
V2_PHASE = "seen_development_c_v2_once"
V2_LEDGER = (
    REPO / "docs/implementation/evidence/issue190-c-remaining-diagnostic-20260831a/cost-ledger.json"
)
V2_LEDGER_SHA = "c11630710263c473fbf938b60e789b33ef93b776021e258976825fdf47206a50"
V2_REQUESTS = V2_ASSETS / "requests.json"
V2_REQUESTS_SHA = "7234a4f5812e976f3e3efc594fc3e2b0760b46b760b0f2a8d403525fbfd5cd91"
DEVELOPMENT_OPT_IN = "issue-190-versioned-synthetic-development"
DEVELOPMENT_ANCHOR = (
    REPO / "docs/implementation/evidence/issue190-c-v2-development-20260831a/cost-ledger.json"
)
DEVELOPMENT_ANCHOR_SHA = "0800a19d7111b2838d7131734a62cdf6a64be48dcac1fc8c9b44d3435b9646f0"


def remaining_manifest() -> dict[str, Any]:
    content = REMAINING_MANIFEST.read_bytes()
    if sha256(content) != REMAINING_MANIFEST_SHA:
        raise SufficiencyBlocked("REMAINING_MANIFEST_CHANGED")
    return json.loads(content)


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
        self.phase = PHASE
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
        phase_attempts = [entry for entry in self.state["attempts"] if entry["phase"] == self.phase]
        limit = {DIAGNOSTIC_PHASE: 1, REMAINING_PHASE: 67}.get(self.phase, 72)
        if self.phase == DIAGNOSTIC_PHASE and (
            query_id != FIFTH_QUERY_ID or request_sha != FIFTH_REQUEST_SHA
        ):
            raise SufficiencyBlocked("DIAGNOSTIC_REQUEST_MISMATCH")
        if len(phase_attempts) >= limit or any(
            entry["query_id"] == query_id for entry in phase_attempts
        ):
            raise SufficiencyBlocked("CALL_LIMIT_NO_RETRY")
        if self.phase in {REMAINING_PHASE, V2_PHASE} or self.phase.startswith("development_"):
            expected = self.state["phases"][self.phase]["requests"][len(phase_attempts)]
            if expected != {"query_id": query_id, "request_sha256": request_sha}:
                raise SufficiencyBlocked("REMAINING_REQUEST_ORDER_MISMATCH")
        entry = {
            "phase": self.phase,
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
        self.state["phases"][self.phase]["status"] = status
        write_json(self.path, self.state)

    def begin_fifth_diagnostic(
        self, run_id: str, assets: dict[str, str], query_id: str, request_sha: str
    ) -> None:
        if DIAGNOSTIC_PHASE in self.state["phases"]:
            raise SufficiencyBlocked("DIAGNOSTIC_ALREADY_STARTED_NO_RETRY")
        original = ORIGINAL_LEDGER.read_bytes()
        if sha256(original) != ORIGINAL_LEDGER_SHA:
            raise SufficiencyBlocked("ORIGINAL_LEDGER_ARCHIVE_CHANGED")
        # 本次授权精确绑定原5次调用后的账本,不重置STOPPED或接受丢失的历史费用。
        if self.state != json.loads(original):
            raise SufficiencyBlocked("DIAGNOSTIC_LEDGER_PRECONDITION_CHANGED")
        if (
            query_id != FIFTH_QUERY_ID
            or request_sha != FIFTH_REQUEST_SHA
            or assets != self.state["phases"][PHASE]["assets"]
        ):
            raise SufficiencyBlocked("DIAGNOSTIC_REQUEST_MISMATCH")
        self.phase = DIAGNOSTIC_PHASE
        self.state["phases"][self.phase] = {
            "run_id": run_id,
            "status": "RUNNING",
            "assets": assets,
            "original_run_id": self.state["phases"][PHASE]["run_id"],
            "request_sha256": request_sha,
            "maximum_requests": 1,
            "quality_evaluation": False,
        }
        write_json(self.path, self.state)

    def begin_remaining_diagnostic(
        self, run_id: str, assets: dict[str, str], requests: list[dict[str, str]]
    ) -> None:
        if REMAINING_PHASE in self.state["phases"]:
            raise SufficiencyBlocked("REMAINING_ALREADY_STARTED_NO_RETRY")
        original = REMAINING_LEDGER.read_bytes()
        if sha256(original) != REMAINING_LEDGER_SHA:
            raise SufficiencyBlocked("REMAINING_LEDGER_ARCHIVE_CHANGED")
        if self.state != json.loads(original):
            raise SufficiencyBlocked("REMAINING_LEDGER_PRECONDITION_CHANGED")
        manifest = remaining_manifest()
        if assets != manifest["asset_sha256"] or [request["query_id"] for request in requests] != [
            request["query_id"] for request in manifest["requests"]
        ]:
            raise SufficiencyBlocked("REMAINING_REQUEST_MANIFEST_MISMATCH")
        self.phase = REMAINING_PHASE
        self.state["phases"][self.phase] = {
            "run_id": run_id,
            "status": "RUNNING",
            "assets": assets,
            "manifest_sha256": REMAINING_MANIFEST_SHA,
            "requests": requests,
            "maximum_requests": 67,
            "quality_evaluation": False,
        }
        write_json(self.path, self.state)

    def begin_v2(self, run_id: str, assets: dict[str, str], requests: list[dict[str, str]]) -> None:
        if V2_PHASE in self.state["phases"]:
            raise SufficiencyBlocked("V2_ALREADY_STARTED_NO_RETRY")
        original = V2_LEDGER.read_bytes()
        if sha256(original) != V2_LEDGER_SHA:
            raise SufficiencyBlocked("V2_LEDGER_ARCHIVE_CHANGED")
        if self.state != json.loads(original):
            raise SufficiencyBlocked("V2_LEDGER_PRECONDITION_CHANGED")
        content = V2_REQUESTS.read_bytes()
        if sha256(content) != V2_REQUESTS_SHA:
            raise SufficiencyBlocked("V2_REQUEST_MANIFEST_CHANGED")
        manifest = json.loads(content)
        if assets != manifest["asset_sha256"] or requests != manifest["requests"]:
            raise SufficiencyBlocked("V2_REQUEST_MANIFEST_MISMATCH")
        self.phase = V2_PHASE
        self.state["phases"][self.phase] = {
            "run_id": run_id,
            "status": "RUNNING",
            "assets": assets,
            "manifest_sha256": V2_REQUESTS_SHA,
            "requests": requests,
            "maximum_requests": 72,
            "quality_evaluation": "SEEN_DEVELOPMENT_ONLY",
        }
        write_json(self.path, self.state)

    def begin_version(
        self, version: str, run_id: str, assets: dict[str, str], requests: list[dict[str, str]]
    ) -> None:
        phase = f"development_{version}"
        if phase in self.state["phases"]:
            raise SufficiencyBlocked("VERSION_ALREADY_RUN")
        if self.totals()["unsettled_reserved_micro_cny"]:
            raise SufficiencyBlocked("UNSETTLED_COST_REQUIRES_COORDINATOR")
        content = DEVELOPMENT_ANCHOR.read_bytes()
        if sha256(content) != DEVELOPMENT_ANCHOR_SHA:
            raise SufficiencyBlocked("DEVELOPMENT_HISTORY_CHANGED")
        anchor = json.loads(content)
        if (
            self.state["prior_paid_micro_cny"] != anchor["prior_paid_micro_cny"]
            or self.state["attempts"][: len(anchor["attempts"])] != anchor["attempts"]
            or any(
                self.state["phases"].get(key) != value for key, value in anchor["phases"].items()
            )
        ):
            raise SufficiencyBlocked("DEVELOPMENT_HISTORY_CHANGED")
        self.phase = phase
        self.state["phases"][phase] = {
            "run_id": run_id,
            "status": "RUNNING",
            "version": version,
            "assets": assets,
            "requests": requests,
            "maximum_requests": 72,
            "quality_evaluation": "SEEN_DEVELOPMENT_ONLY",
        }
        write_json(self.path, self.state)


async def run_development(
    report: dict[str, Any],
    ledger: ExperimentLedger,
    frozen: dict[str, Any],
    *,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
    diagnose_fifth_once: bool = False,
    diagnose_remaining_once: bool = False,
    c_v2_whole_once: bool = False,
    development_version: str | None = None,
) -> None:
    if (
        sum(
            (
                diagnose_fifth_once,
                diagnose_remaining_once,
                c_v2_whole_once,
                development_version is not None,
            )
        )
        > 1
    ):
        raise SufficiencyBlocked("DIAGNOSTIC_MODES_ARE_EXCLUSIVE")
    modern_contract = c_v2_whole_once or development_version is not None
    # 不允许把v2解析规则用到旧请求,或把旧解析器用于新版方法。
    if (
        frozen["asset_sha256"]
        != contract(c_v2=c_v2_whole_once, development_version=development_version)["asset_sha256"]
    ):
        raise SufficiencyBlocked("METHOD_MODE_MISMATCH")
    if modern_contract and frozen["config"]["quality_thresholds"] != QUALITY:
        raise SufficiencyBlocked("QUALITY_THRESHOLDS_CHANGED")
    rows = development_rows()
    if diagnose_fifth_once:
        rows = [rows[4]]
    elif diagnose_remaining_once:
        rows = rows[5:]
    bodies = [request_body(row, frozen) for row in rows]
    encoded_bodies = [
        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        for body in bodies
    ]
    if development_version is not None:
        requests = [
            {"query_id": row["id"], "request_sha256": sha256(encoded)}
            for row, encoded in zip(rows, encoded_bodies, strict=True)
        ]
        ledger.begin_version(
            development_version, report["run_id"], frozen["asset_sha256"], requests
        )
        report.update(request_manifest=requests, development_version=development_version)
    elif c_v2_whole_once:
        requests = [
            {"query_id": row["id"], "request_sha256": sha256(encoded)}
            for row, encoded in zip(rows, encoded_bodies, strict=True)
        ]
        ledger.begin_v2(report["run_id"], frozen["asset_sha256"], requests)
        report.update(request_manifest=requests, source_manifest_sha256=V2_REQUESTS_SHA)
    elif diagnose_remaining_once:
        requests = [
            {"query_id": row["id"], "request_sha256": sha256(encoded)}
            for row, encoded in zip(rows, encoded_bodies, strict=True)
        ]
        ledger.begin_remaining_diagnostic(report["run_id"], frozen["asset_sha256"], requests)
        report["request_manifest"] = requests
        report["source_manifest_sha256"] = REMAINING_MANIFEST_SHA
    elif diagnose_fifth_once:
        ledger.begin_fifth_diagnostic(
            report["run_id"], frozen["asset_sha256"], rows[0]["id"], sha256(encoded_bodies[0])
        )
    else:
        ledger.begin(report["run_id"], frozen["asset_sha256"])
    report["rows"] = []
    config = frozen["config"]
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15, connect=3),
        transport=transport,
        follow_redirects=False,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        for row, encoded in zip(rows, encoded_bodies, strict=True):
            entry = ledger.reserve(row["id"], sha256(encoded))
            started = time.perf_counter()
            observation: dict[str, Any] = {"usage_trusted": False}
            if modern_contract:
                observation["contract_checks"] = dict.fromkeys(
                    CONTRACT_CHECK_LAYERS, "NOT_EVALUATED"
                )
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
                try:
                    parsed = parse_response(
                        payload,
                        row,
                        expected_identity=(identity[0], identity[1])
                        if identity is not None
                        else None,
                        duration_ms=elapsed,
                        c_v2=modern_contract,
                    )
                except SufficiencyBlocked as error:
                    if modern_contract:
                        observation["contract_checks"] = error.observation["contract_checks"]
                    if str(error) in {
                        "INVALID_DECISION_JSON",
                        "INVALID_DECISION_SCHEMA",
                        "INVALID_EVIDENCE",
                    }:
                        # 仅在固定envelope/单个output_text检查通过后取证。
                        # 不复制error正文/请求头,仍由外层finally结算并抛原错。
                        observation["decision_diagnostic"] = decision_diagnostic(
                            payload["output"][0]["content"][0]["text"], api_key
                        )
                    raise
                if modern_contract:
                    observation["contract_checks"] = parsed["observation"]["contract_checks"]
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
                if modern_contract:
                    # 保留所有原始摘录;文章统计去重,不把多段摘录当多个独立来源。
                    evidence = parsed["decision"]["evidence"]
                    source_ids = list(
                        dict.fromkeys(
                            row["fusedCandidates"][item["chunk"] - 1]["articleId"]
                            for item in evidence
                        )
                    )
                    report["rows"][-1].update(
                        evidence_item_count=len(evidence),
                        cited_article_ids=source_ids,
                        distinct_cited_article_count=len(source_ids),
                        contract_validation="PASS",
                    )
            except (TimeoutError, httpx.TransportError):
                observation["failure"] = "SUPPLIER_TIMEOUT_OR_TRANSPORT_ERROR"
                raise SufficiencyBlocked("SUPPLIER_TIMEOUT_OR_TRANSPORT_ERROR") from None
            except SufficiencyBlocked as error:
                observation["failure"] = str(error)
                raise
            finally:
                observation["duration_ms"] = round((time.perf_counter() - started) * 1000)
                ledger.settle(entry, observation)
    if diagnose_fifth_once or diagnose_remaining_once:
        report.update(status="DIAGNOSTIC_COMPLETED", metrics=None)
        return
    decisions = [entry["decision"]["sufficient"] for entry in report["rows"]]
    report.update(replay_metrics(rows, decisions))
    if modern_contract:
        report.update(
            contract_validation="PASS_72_OF_72",
            semantic_validation=report["status"],
            quality_scope="SEEN_DEVELOPMENT_NOT_HOLDOUT_OR_DELIVERY",
            confusion_counts={
                "answerable_accepted": sum(
                    r["answerable"] and d for r, d in zip(rows, decisions, strict=True)
                ),
                "answerable_rejected": sum(
                    r["answerable"] and not d for r, d in zip(rows, decisions, strict=True)
                ),
                "unanswerable_accepted": sum(
                    not r["answerable"] and d for r, d in zip(rows, decisions, strict=True)
                ),
                "unanswerable_rejected": sum(
                    not r["answerable"] and not d for r, d in zip(rows, decisions, strict=True)
                ),
            },
        )
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
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--diagnose-fifth-once", action="store_true")
    modes.add_argument("--diagnose-remaining-once", action="store_true")
    modes.add_argument("--c-v2-whole-once", action="store_true")
    modes.add_argument("--development-version")
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
    expected_opt_in = DIAGNOSTIC_OPT_IN if args.diagnose_fifth_once else OPT_IN
    if args.diagnose_remaining_once:
        expected_opt_in = REMAINING_OPT_IN
    if args.c_v2_whole_once:
        expected_opt_in = V2_OPT_IN
    if args.development_version:
        expected_opt_in = DEVELOPMENT_OPT_IN
    if os.environ.get("KNOWLEDGE_SUFFICIENCY_EXPERIMENT") != expected_opt_in:
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
    frozen = contract(c_v2=args.c_v2_whole_once, development_version=args.development_version)
    is_diagnostic = args.diagnose_fifth_once or args.diagnose_remaining_once
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
            "partition": "fifth_request_diagnostic_not_quality"
            if args.diagnose_fifth_once
            else "seen_development_not_unseen",
            "query_count": 1 if args.diagnose_fifth_once else 72,
            "diagnose_fifth_once": args.diagnose_fifth_once,
            "diagnose_remaining_once": args.diagnose_remaining_once,
            "contract": frozen,
            "budget_plan": budget_plan(frozen),
            "pricing_and_context_verified_date": args.pricing_and_context_verified_date,
            "environment": {"python": platform.python_version(), "platform": platform.platform()},
            "rows": [],
            "metrics": None,
        }
        if args.diagnose_remaining_once:
            report.update(
                partition="remaining67_development_diagnostic_not_quality", query_count=67
            )
        if args.c_v2_whole_once:
            report.update(
                schema="knowledge-sufficiency-experiment-run-v2",
                partition="seen_development_c_v2_not_unseen",
                contract_validation="INCOMPLETE",
                semantic_validation="NOT_EVALUATED",
            )
        if args.development_version:
            report.update(
                schema="knowledge-sufficiency-development-run-v1",
                partition="seen_development_not_unseen",
                development_version=args.development_version,
                contract_validation="INCOMPLETE",
                semantic_validation="NOT_EVALUATED",
            )
        ledger: ExperimentLedger | None = None
        try:
            if (
                is_diagnostic or args.c_v2_whole_once or args.development_version
            ) and not ledger_path.exists():
                raise SufficiencyBlocked("DIAGNOSTIC_REQUIRES_EXISTING_LEDGER")
            ledger = ExperimentLedger(ledger_path, frozen)
            report["cost_totals_before"] = ledger.totals()
            asyncio.run(
                run_development(
                    report,
                    ledger,
                    frozen,
                    api_key=api_key,
                    diagnose_fifth_once=args.diagnose_fifth_once,
                    diagnose_remaining_once=args.diagnose_remaining_once,
                    c_v2_whole_once=args.c_v2_whole_once,
                    development_version=args.development_version,
                )
            )
        except SufficiencyBlocked as error:
            report.update(status="STOPPED", stopped_reason=str(error))
        except Exception as error:
            # 不记录异常正文,避免凭据/供应商payload进入归档。
            report.update(status="ERROR", error_type=type(error).__name__)
        finally:
            if ledger is not None:
                phase = ledger.state["phases"].get(ledger.phase, {})
                if phase.get("run_id") == args.run_id and phase.get("status") == "RUNNING":
                    ledger.finish(report["status"])
                report["cost_ledger"] = ledger.state
                report["cost_totals"] = ledger.totals()
            report["elapsed_seconds"] = time.perf_counter() - started
            json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
    if report["status"] not in {"PASS", "DIAGNOSTIC_COMPLETED"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
