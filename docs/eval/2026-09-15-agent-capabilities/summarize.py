"""汇总冻结的 12 例原始证据；不调用模型，也不自动判定正文语义质量。"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import statistics


DIRECTORY = Path(__file__).resolve().parent
DEFAULT_RAW = DIRECTORY.parents[2] / ".local/gate-evidence/issue242-capabilities-20260915"
TITLE = re.compile(r"^Agent capabilities 20260915 ([a-z0-9_]+)$")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def timestamp(value):
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000
    return None


def stats(values):
    observed = sorted(value for value in values if isinstance(value, (int, float)) and value >= 0)
    if not observed:
        return {"n": 0, "meanMs": None, "p50Ms": None, "p90Ms": None, "minMs": None, "maxMs": None}
    return {
        "n": len(observed),
        "meanMs": round(statistics.mean(observed), 2),
        "p50Ms": statistics.median(observed),
        "p90Ms": observed[math.ceil(len(observed) * 0.9) - 1],
        "minMs": observed[0],
        "maxMs": observed[-1],
    }


def specs(suite):
    yield from suite.get("specs", [])
    for child in suite.get("suites", []):
        yield from specs(child)


def attachment(result, raw: Path):
    item = next((value for value in result.get("attachments", []) if value["name"] == "evaluation-case"), None)
    if item is None:
        return {}, "没有 evaluation-case 附件"
    try:
        if "body" in item:
            return json.loads(base64.b64decode(item["body"]).decode("utf-8-sig")), None
        if "path" in item:
            recorded = str(item["path"]).replace("\\", "/")
            relative = recorded.split("/artifacts/", 1)[-1]
            for path in (raw / "artifacts" / relative, raw / recorded, raw / "artifacts" / Path(recorded).name):
                if path.is_file():
                    return read(path), None
        return {}, "附件存在但正文或本机文件不可读取"
    except (ValueError, UnicodeError, OSError) as error:
        return {}, f"附件解析失败: {error}"


def browser_runs(report, raw: Path):
    found = {}
    for suite in report.get("suites", []):
        for spec in specs(suite):
            match = TITLE.fullmatch(spec.get("title", ""))
            if not match:
                continue
            for test in spec.get("tests", []):
                for result in test.get("results", []):
                    evidence, capture_error = attachment(result, raw)
                    found.setdefault(match[1], []).append({
                        "browserStatus": result["status"],
                        "durationMs": result.get("duration"),
                        "startedAt": result.get("startTime"),
                        "retry": result.get("retry", 0),
                        "annotations": test.get("annotations", []),
                        "errors": [ANSI.sub("", error.get("message", "")) for error in result.get("errors", [])],
                        "attachmentError": capture_error,
                        "evidence": evidence,
                    })
    return found


def identify(case):
    ticket_ids, intake_ids, generation_ids = set(), set(), set()
    for run in case["browserRuns"]:
        evidence = run["evidence"]
        ticket_ids.update(evidence.get("ticketIds", []))
        for intake in evidence.get("intakeSnapshots", []):
            intake_ids.add(intake.get("intakeId"))
            ticket_ids.update(intake.get("ticketIds", []))
        for customer in evidence.get("customerSnapshots", []):
            ticket_ids.add(customer.get("ticketId"))
        for name in ("initialBusiness", "business"):
            business = evidence.get(name) or {}
            ticket_ids.update(ticket.get("id") for ticket in business.get("tickets", []))
            generation_ids.update(generation.get("id") for generation in business.get("generations", []))
            intake_ids.update(call.get("intakeId") for call in business.get("intakeCalls", []))
    case["ticketIds"] = sorted(value for value in ticket_ids if value)
    case["intakeIds"] = sorted(value for value in intake_ids if value)
    case["generationIds"] = sorted(value for value in generation_ids if value)


def timing(evidence):
    phases = {phase["name"]: phase["at"] for phase in evidence.get("phases", [])}
    issues = []

    def difference(start, end):
        if start not in phases or end not in phases:
            return None
        duration = phases[end] - phases[start]
        if duration < 0:
            issues.append(f"阶段时间倒序: {start} -> {end}")
            return None
        return duration

    confirmations = sorted(int(match[1]) for name in phases if (match := re.fullmatch(r"confirmation_(\d+)_clicked", name)))
    first = f"confirmation_{confirmations[0]}_clicked" if confirmations else "missing_confirmation"
    last = f"confirmation_{confirmations[-1]}_clicked" if confirmations else "missing_confirmation"
    first_ui = evidence.get("firstReplyUi")
    if isinstance(first_ui, dict) and isinstance(first_ui.get("at"), (int, float)):
        phases["first_reply_ui"] = first_ui["at"]
    final_terminal = "followup_terminal" if "followup_clicked" in phases else "all_terminal"
    return {
        "intakeClickToResponseMs": difference("intake_clicked", "intake_response"),
        "confirmationToTicketsMs": difference(first, f"tickets_{confirmations[0]}_created") if confirmations else None,
        "confirmationToTerminalMs": difference(first, "all_terminal"),
        "lastConfirmationToTerminalMs": difference(last, "all_terminal"),
        "confirmationToReplyUiMs": difference(first, "first_reply_ui"),
        "intakeClickToTerminalMs": difference("intake_clicked", "all_terminal"),
        "followupClickToTerminalMs": difference("followup_clicked", "followup_terminal"),
        "intakeClickToFinalTerminalMs": difference("intake_clicked", final_terminal),
    }, [
        {
            "orderIndex": index,
            "confirmationToTicketsMs": difference(f"confirmation_{index}_clicked", f"tickets_{index}_created"),
            "confirmationToAllInitialTerminalsMs": difference(f"confirmation_{index}_clicked", "all_terminal"),
        }
        for index in confirmations
    ], issues


def assign_attempt(attempt, cases, allow_window):
    owners = []
    for field, case_field in (("ticketId", "ticketIds"), ("intakeId", "intakeIds"), ("generationId", "generationIds")):
        value = attempt.get(field)
        if value:
            owners.extend((case["id"], field) for case in cases if value in case[case_field])
    candidates = sorted({case_id for case_id, _ in owners})
    if len(candidates) == 1:
        return candidates[0], "+".join(sorted({field for _, field in owners})), []
    if len(candidates) > 1:
        return None, "CONFLICTING_BUSINESS_IDS", candidates
    # 受理可能在返回 intakeId 前失败；只有冻结为单 worker 才使用唯一时间窗。
    if allow_window and attempt.get("role") == "intake":
        at = timestamp(attempt.get("startedAt"))
        matches = []
        for case in cases:
            for run in case["browserRuns"]:
                if run["browserStatus"] == "skipped":
                    continue
                evidence = run["evidence"]
                start = timestamp(evidence.get("startedAt", run.get("startedAt")))
                end = timestamp(evidence.get("endedAt"))
                if end is None and start is not None and run.get("durationMs") is not None:
                    end = start + run["durationMs"]
                if at is not None and start is not None and end is not None and start <= at <= end:
                    matches.append(case["id"])
        if len(set(matches)) == 1:
            return matches[0], "serial-browser-case-time-window", []
    return None, "UNATTRIBUTED", []


def usage(attempts, complete_source, applicable=True):
    known_tokens = sum(attempt[key] for attempt in attempts for key in ("inputTokens", "outputTokens") if isinstance(attempt.get(key), int))
    costs = [attempt.get("estimatedCostMicros") for attempt in attempts]
    unknown_usage = sum(any(attempt.get(key) is None for key in ("inputTokens", "outputTokens")) for attempt in attempts)
    known_cost = sum(cost for cost in costs if cost is not None)
    complete = complete_source and unknown_usage == 0 and None not in costs
    return {
        "recordedAttempts": len(attempts),
        "attempts": len(attempts) if complete_source and applicable else None,
        "attemptNumbers": [attempt["number"] for attempt in attempts],
        "allUsageKnown": complete if applicable else None,
        "unknownUsageAttempts": unknown_usage if complete_source and applicable else None,
        "observedUnknownUsageAttempts": unknown_usage,
        "knownTokens": known_tokens if attempts or (complete_source and applicable) else None,
        "tokens": known_tokens if complete and applicable else None,
        "knownEstimatedCostMicros": known_cost if attempts or (complete_source and applicable) else None,
        "estimatedCostMicros": known_cost if complete and applicable else None,
        "statuses": dict(Counter(attempt.get("status", "UNKNOWN") for attempt in attempts)),
    }


def public_replies(case):
    messages = {}
    for run in case["browserRuns"]:
        for name in ("initialBusiness", "business"):
            for message in (run["evidence"].get(name) or {}).get("messages", []):
                if message.get("author") == "AGENT":
                    key = (message.get("ticketId"), message.get("sequence"), message.get("body"))
                    messages[key] = message
    return list(messages.values())


def summarize(raw: Path, out: Path):
    paths = {
        "plan": raw / "plan.json",
        "result": raw / "result.json",
        "ledger": raw / "ledger.final.json",
        "metrics": raw / "metrics.json",
        "capabilities": raw / "capabilities.json",
        "playwright": raw / "artifacts/playwright.json",
    }
    if not paths["playwright"].is_file() and (raw / "playwright.json").is_file():
        paths["playwright"] = raw / "playwright.json"
    sources = {name: read(path) if path.is_file() else None for name, path in paths.items()}
    plan, result = sources["plan"] or {}, sources["result"] or {}
    scenarios = plan.get("scenarios")
    scenario_source = str(paths["plan"])
    if scenarios is None:
        scenario_path = raw / "scenarios.json" if (raw / "scenarios.json").is_file() else DIRECTORY / "scenarios.json"
        scenarios, scenario_source = read(scenario_path), str(scenario_path)
    if len(scenarios) != 12 or len({scenario["id"] for scenario in scenarios}) != 12:
        raise ValueError("本轮必须保留冻结的 12 个不同场景，禁止使用其他轮次的分母")
    report = sources["playwright"] or {}
    runs = browser_runs(report, raw)
    matrix = {entry["case"]: entry["status"] for entry in result.get("matrix", [])}
    cases = []
    for scenario in scenarios:
        current_runs = runs.get(scenario["id"], [])
        statuses = [run["browserStatus"] for run in current_runs]
        status = "FAIL" if any(value not in ("passed", "skipped") for value in statuses) else "PASS" if "passed" in statuses else "NOT_RUN"
        status_source = "playwright" if current_runs else "no-browser-result"
        if not current_runs and scenario["id"] in matrix:
            status, status_source = matrix[scenario["id"]], "runner-matrix-without-browser-result"
        repeated = len(current_runs) > 1 or any(run["retry"] != 0 for run in current_runs)
        if repeated:
            status = "FAIL"
        evidence = current_runs[-1]["evidence"] if current_runs else {}
        case = {
            "id": scenario["id"], "title": scenario["title"], "scenario": scenario,
            "status": status, "statusSource": status_source,
            "browserStatus": statuses[-1] if statuses else None,
            "browserRuns": current_runs, "unexpectedRepeatedExecution": repeated,
            "durationMs": sum(run["durationMs"] for run in current_runs if run.get("durationMs") is not None) if current_runs and status != "NOT_RUN" else None,
            "evidence": evidence,
            "errors": [error for run in current_runs for error in run["errors"]],
            "annotations": [annotation for run in current_runs for annotation in run["annotations"]],
            "captureErrors": [error for run in current_runs for error in run["evidence"].get("captureErrors", [])],
            "evidenceAvailable": any(bool(run["evidence"]) for run in current_runs),
            "semanticReviewStatus": "PENDING" if status != "NOT_RUN" else "NOT_RUN",
            "capabilityAcceptance": None,
        }
        if repeated:
            case["errors"].append("发现重复执行，违反本轮每例一次/retries=0；完整保留所有尝试，不挑选通过结果")
        case["timing"], case["confirmationStages"], case["timingIssues"] = timing(evidence)
        identify(case)
        case["publicReplies"] = public_replies(case)
        case["publicReplyCount"] = len(case["publicReplies"]) if case["evidenceAvailable"] else None
        cases.append(case)

    ledger, metrics = sources["ledger"] or {}, sources["metrics"] or {}
    entries = ledger.get("entries", [])
    measured = {entry["attemptId"]: entry for entry in metrics.get("attempts", [])}
    attempts = []
    for entry in entries:
        independent = measured.get(entry["attemptId"], {})
        value = {key: value for key, value in entry.items() if key != "session"}
        value["attempt"] = {**independent, **(entry.get("attempt") or {})}
        value.update(source="persistent-ledger", independentMetrics=independent or None)
        for field in ("intakeId", "generationId", "ticketId", "internalCallId", "role"):
            value[field] = entry.get(field) or independent.get(field)
        attempts.append(value)
    recorded_ids = {entry["attemptId"] for entry in entries}
    for attempt_id, independent in measured.items():
        if attempt_id not in recorded_ids:
            attempts.append({**independent, "source": "independent-metrics-only", "status": "MISSING_LEDGER", "attempt": independent, "independentMetrics": independent})
    for number, attempt in enumerate(attempts, 1):
        attempt["number"] = number
        attempt["caseId"], attempt["caseAttributionMethod"], attempt["conflictingCaseIds"] = assign_attempt(attempt, cases, plan.get("workers") == 1)
    unattributed = [attempt["attemptId"] for attempt in attempts if attempt["caseId"] is None]
    metrics_only = [attempt["attemptId"] for attempt in attempts if attempt["source"] != "persistent-ledger"]
    attribution_complete = sources["ledger"] is not None and not unattributed and not metrics_only
    capabilities = sources["capabilities"] or {}
    capability_generations = []
    for generation in capabilities.get("generations", []):
        owners = [case["id"] for case in cases if generation.get("ticketId") in case["ticketIds"]]
        capability_generations.append({**generation, "caseId": owners[0] if len(owners) == 1 else None, "caseAttributionMethod": "ticketId" if len(owners) == 1 else "UNATTRIBUTED"})
    for case in cases:
        linked = [attempt for attempt in attempts if attempt["caseId"] == case["id"]]
        case["usage"] = usage(linked, attribution_complete, case["status"] != "NOT_RUN")
        case["capabilityGenerations"] = [generation for generation in capability_generations if generation["caseId"] == case["id"]]
        case["actions"] = [{**action, "generationId": generation["generationId"], "ticketId": generation["ticketId"]} for generation in case["capabilityGenerations"] for action in generation.get("actions", [])]
        case["modelSelections"] = [{**call, "generationId": generation["generationId"], "ticketId": generation["ticketId"]} for generation in case["capabilityGenerations"] for call in generation.get("modelCalls", []) if call.get("selectedAction")]
        available = {generation["generationId"] for generation in case["capabilityGenerations"] if generation.get("checkpointStatus") == "AVAILABLE"}
        case["capabilityCollection"] = {
            "sourceAvailable": sources["capabilities"] is not None,
            "status": "NOT_COLLECTED" if sources["capabilities"] is None else "INCOMPLETE" if set(case["generationIds"]) - available else "COLLECTED" if available else "NO_OBSERVED_GENERATION",
            "observedOrigins": dict(Counter(action.get("origin", "UNKNOWN") for action in case["actions"])),
            "expectedGenerationIds": case["generationIds"],
            "availableGenerationIds": sorted(available),
            "missingOrUnavailableGenerationIds": sorted(set(case["generationIds"]) - available),
        }
    ledger_totals = usage([attempt for attempt in attempts if attempt["source"] == "persistent-ledger"], sources["ledger"] is not None)
    ledger_totals.update({
        "source": "persistent-budget-ledger",
        "supplierChargeMicros": metrics.get("supplierChargeMicros"),
        "pendingReservedMicros": sum(entry["reservedMicros"] for entry in entries if entry["status"] == "PENDING") if sources["ledger"] is not None else None,
        "inFlightReservedMicros": sum(entry["reservedMicros"] for entry in entries if entry["status"] == "IN_FLIGHT") if sources["ledger"] is not None else None,
    })
    reconciliation = None
    mismatched_attempt_ids = []
    if sources["metrics"] is not None and sources["ledger"] is not None:
        mismatched_attempt_ids = [entry["attemptId"] for entry in entries if entry["attemptId"] in measured and any(entry.get(field) != measured[entry["attemptId"]].get(field) for field in ("inputTokens", "outputTokens", "estimatedCostMicros"))]
        reconciliation = (set(measured) == recorded_ids and not mismatched_attempt_ids and metrics.get("missingEvidenceSources") == 0 and metrics.get("unknownUsageAttempts") == 0 and ledger_totals["allUsageKnown"] and metrics.get("tokens") == ledger_totals["tokens"] and metrics.get("estimatedCostMicros") == ledger_totals["estimatedCostMicros"])
    counts = {status: sum(case["status"] == status for case in cases) for status in ("PASS", "FAIL", "NOT_RUN")}
    executed = counts["PASS"] + counts["FAIL"]
    roles = sorted({attempt.get("role") for attempt in attempts if attempt.get("role")} | {"intake", "action", "judgment", "communication"})
    summary = {
        "schemaVersion": "agent-capabilities-summary-v1",
        "runId": plan.get("runId", result.get("runId", raw.name)),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "testedHead": plan.get("testedHead", result.get("head")),
        "scenarioSource": scenario_source,
        "sourceAvailability": {name: {"available": value is not None, "path": str(paths[name])} for name, value in sources.items()},
        "denominator": 12, "counts": counts,
        "pathCounts": {path: {status: sum(case["status"] == status and bool(case["scenario"].get("legacy")) == legacy for case in cases) for status in ("PASS", "FAIL", "NOT_RUN")} for path, legacy in (("core", False), ("legacy", True))},
        "automaticBusinessPassFraction": counts["PASS"] / 12,
        "executedBusinessPassFraction": counts["PASS"] / executed if executed else None,
        "executionCoverage": executed / 12,
        "semanticReviewStatus": "PENDING", "capabilityAcceptance": None,
        "browserStats": report.get("stats"),
        "caseLatency": stats([case["durationMs"] for case in cases]),
        "timings": {key: stats([case["timing"][key] for case in cases]) for key in cases[0]["timing"]},
        "roleLatency": {role: stats([(attempt.get("attempt") or {}).get("durationMs") for attempt in attempts if attempt.get("role") == role]) for role in roles},
        "roleUsage": {role: usage([attempt for attempt in attempts if attempt.get("role") == role], sources["ledger"] is not None and not metrics_only) for role in roles},
        "ledgerTotals": ledger_totals,
        "independentMetricsReconciliation": reconciliation,
        "ledgerMetricsMismatchAttemptIds": mismatched_attempt_ids,
        "independentMetricsTotals": {key: value for key, value in metrics.items() if key not in ("attempts", "generationDiagnostics")},
        "unattributedAttemptIds": unattributed,
        "metricsOnlyAttemptIds": metrics_only,
        "timeWindowAttributedAttemptIds": [attempt["attemptId"] for attempt in attempts if attempt["caseAttributionMethod"] == "serial-browser-case-time-window"],
        "unattributedCapabilityGenerationIds": [generation["generationId"] for generation in capability_generations if generation["caseId"] is None],
        "casesWithoutBrowserEvidence": [case["id"] for case in cases if case["status"] != "NOT_RUN" and not case["evidenceAvailable"]],
        "unexpectedBrowserCaseIds": sorted(set(runs) - {case["id"] for case in cases}),
        "result": result or None,
        "definitions": {
            "status": "自动业务合同结果；FAIL 包含浏览器断言/运行失败，不自动推导语义能力失败原因。",
            "unknown": "null 表示未采集、不完整或不适用；known 字段只统计已知部分。NOT_RUN 不计零消耗或零延迟。",
            "latency": "P50 为中位数，P90 为 nearest-rank。小样本描述，不计算或宣称生产 P95。模型 durationMs 是完整请求/响应时间，非 TTFT；整例含登录、采集和断言。",
            "confirmationToTerminalMs": "第一次确认至全部首代终态；多订单另保留每次确认阶段和最后一次确认至终态。",
            "confirmationToReplyUiMs": "第一次确认至页面首次观察到 reply-sources；近似正文 UI 时点，非供应商首 token。缺失或时间倒序记 null。",
            "usage": "账本金额保持原样，独立 metrics 仅核对及补归属；PENDING 不因已有其他计量证据而自动结算。预留不是实扣。",
            "actions": "保留采集器给出的 MODEL_SELECTED/PROGRAM_REQUIRED/UNKNOWN；动作存在或引文逐字匹配不等于语义充分。",
        },
    }
    data = {**summary, "plan": plan or None, "cases": cases, "attempts": attempts, "metrics": sources["metrics"], "capabilities": {**capabilities, "generations": capability_generations} if sources["capabilities"] is not None else None, "ledgerMetadata": {key: value for key, value in ledger.items() if key != "entries"} if sources["ledger"] is not None else None}
    out.mkdir(parents=True, exist_ok=True)
    write(out / "data.json", data)
    write(out / "summary.json", summary)
    with (out / "cases.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["场景ID", "名称", "自动结果", "结果来源", "语义审阅", "整例毫秒", "受理至响应毫秒", "首确认至终态毫秒", "追加至终态毫秒", "确认至正文UI毫秒", "已记录请求数", "完整请求数", "已知token", "完整token", "已知估算微元", "完整估算微元", "未知用量次数", "工单ID", "受理ID", "Agent正文数", "动作来源计数", "错误"])
        for case in cases:
            measured_usage = case["usage"]
            writer.writerow([case["id"], case["title"], case["status"], case["statusSource"], case["semanticReviewStatus"], case["durationMs"], case["timing"]["intakeClickToResponseMs"], case["timing"]["confirmationToTerminalMs"], case["timing"]["followupClickToTerminalMs"], case["timing"]["confirmationToReplyUiMs"], measured_usage["recordedAttempts"], measured_usage["attempts"], measured_usage["knownTokens"], measured_usage["tokens"], measured_usage["knownEstimatedCostMicros"], measured_usage["estimatedCostMicros"], measured_usage["unknownUsageAttempts"], "|".join(case["ticketIds"]), "|".join(case["intakeIds"]), case["publicReplyCount"], json.dumps(case["capabilityCollection"]["observedOrigins"], ensure_ascii=False), "\n".join(case["errors"] + case["captureErrors"])])
    with (out / "attempts.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["序号", "请求ID", "场景ID", "归属方式", "数据来源", "角色", "工单ID", "受理ID", "开始时间", "结算状态", "完整请求毫秒", "输入token", "输出token", "缓存token", "HTTP", "响应终态", "失败分类", "请求模型", "响应模型", "估算微元", "预留微元"])
        for attempt in attempts:
            provider = attempt.get("attempt") or {}
            writer.writerow([attempt["number"], attempt["attemptId"], attempt["caseId"], attempt["caseAttributionMethod"], attempt["source"], attempt.get("role"), attempt.get("ticketId"), attempt.get("intakeId"), attempt.get("startedAt"), attempt.get("status"), provider.get("durationMs"), attempt.get("inputTokens"), attempt.get("outputTokens"), provider.get("cachedTokens"), provider.get("providerHttpStatus"), provider.get("responseStatus"), provider.get("failureClassification"), provider.get("requestModel"), provider.get("responseModel"), attempt.get("estimatedCostMicros"), attempt.get("reservedMicros")])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--out", type=Path, default=DIRECTORY)
    arguments = parser.parse_args()
    summarize(arguments.raw.resolve(), arguments.out.resolve())


if __name__ == "__main__":
    main()
