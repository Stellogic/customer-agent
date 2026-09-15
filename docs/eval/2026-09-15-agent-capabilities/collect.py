"""只读采集本轮计量、受控行动和引用；不保存提示词或模型思维链。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx
import psycopg

from baseline_agent.core_validation_metrics import collect_core_metrics


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_actions() -> dict:
    with psycopg.connect(os.environ["SPRING_FORMAL_DATABASE_URI"]) as connection:
        rows = connection.execute(
            "select g.id,g.ticket_id,g.thread_id,g.status,t.issue_kind,t.order_reference "
            "from agent_processing_generation g join support_ticket t on t.id=g.ticket_id "
            "where starts_with(t.order_reference,'ORDER-CAP-0915-') order by g.created_at,g.id"
        ).fetchall()
        receipts = connection.execute(
            "select c.generation_id,c.response_payload from agent_command_request c "
            "join agent_processing_generation g on g.id=c.generation_id "
            "join support_ticket t on t.id=g.ticket_id "
            "where c.operation='SEARCH_KNOWLEDGE' "
            "and starts_with(t.order_reference,'ORDER-CAP-0915-')"
        ).fetchall()
    knowledge_receipts = {str(generation): response for generation, response in receipts}
    generations = []
    for generation_id, ticket_id, thread_id, status, issue_kind, reference in rows:
        result = {
            "generationId": str(generation_id),
            "ticketId": str(ticket_id),
            "orderReference": reference,
            "issueKind": issue_kind,
            "status": status,
        }
        response = httpx.get(
            f"{os.environ['AGENT_SERVER_URL']}/threads/{thread_id}/state",
            headers={"Authorization": f"Bearer {os.environ['SPRING_TO_AGENT_TOKEN']}"},
            timeout=20,
        )
        if response.status_code == 404:
            result["checkpointStatus"] = "NOT_FOUND"
            generations.append(result)
            continue
        response.raise_for_status()
        values = response.json()["values"]
        run = values.get("investigation_run_evidence") or {}
        calls = run.get("modelCalls", [])
        # 每次实际模型选择明确记录；核心路径未出现在该集合的工具读取才来自程序必读。
        selected = {call["selectedAction"] for call in calls if call.get("selectedAction")}
        actions = [
            {
                **action,
                "origin": "MODEL_SELECTED"
                if action["actionType"] in selected
                else "PROGRAM_REQUIRED"
                if issue_kind in {"LOGISTICS_DELAY", "DUPLICATE_CHARGE"}
                else "UNKNOWN",
            }
            for action in values.get("investigation_actions", [])
        ]
        result.update(
            checkpointStatus="AVAILABLE",
            actions=actions,
            modelCalls=calls,
            investigationOutcome=run.get("outcome"),
            failureClassification=run.get("failureClassification"),
            conclusion=values.get("conclusion"),
            customerReply=values.get("customer_reply"),
            knowledgeReceipt=knowledge_receipts.get(str(generation_id)),
        )
        reply = values.get("customer_reply") or {}
        knowledge = reply.get("knowledge")
        if knowledge:
            sources = (knowledge_receipts.get(str(generation_id)) or {}).get("results", [])
            result["citationChecks"] = [
                {
                    "articleId": citation["articleId"],
                    "version": citation["version"],
                    "chunkId": citation["chunkId"],
                    "exactQuoteInAuthorizedReceipt": any(
                        source["articleId"] == citation["articleId"]
                        and source["version"] == citation["version"]
                        and source["chunkId"] == citation["chunkId"]
                        and citation["quote"] in source["snippet"]
                        for source in sources
                    ),
                }
                for citation in knowledge.get("citations", [])
            ]
        generations.append(result)
    return {
        "schemaVersion": "agent-capability-actions-v1",
        "generations": generations,
        "notes": [
            "必需读取归程序，明确出现在modelCalls.selectedAction的动作才记模型选择。",
            "UNKNOWN或缺失checkpoint不是零调用；已执行业务事实以Spring记录为准。",
            "引用来源/版本/逐字匹配不等于语义支持或回答充分，另做人工评分。",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger-path", type=Path, required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    arguments = parser.parse_args()
    metrics = collect_core_metrics(arguments.ledger_path)
    write(arguments.report_path, metrics)
    actions = collect_actions()
    write(arguments.report_path.with_name("capabilities.json"), actions)
    print(json.dumps({"knownProviderAttempts": metrics["knownProviderAttempts"], "generations": len(actions["generations"])}))


if __name__ == "__main__":
    main()
