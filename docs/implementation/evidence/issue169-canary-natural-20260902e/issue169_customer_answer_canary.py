import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

from baseline_agent.customer_communication_model import (
    CustomerCommunicationInput,
)
from baseline_agent.deepseek_customer_communication_model import (
    DeepSeekCustomerCommunicationConfig,
    DeepSeekResponsesCustomerCommunicationModel,
)
from baseline_agent.knowledge_retrieval import parse_knowledge_response
from baseline_agent.knowledge_sufficiency_run import write_json
from issue169_customer_answer_run import BudgetTransport, pending_micro_cny
from issue169_customer_knowledge_acceptance import ORDER, prepare, retrieve, submit


def completed_shape(body: str) -> dict[str, object]:
    completed = []
    for block in body.split("\n\n"):
        lines = block.splitlines()
        if lines and lines[0] == "event: response.completed":
            completed.append(json.loads(next(line[6:] for line in lines if line.startswith("data: "))))
    if len(completed) != 1:
        return {"completed_frames": len(completed)}
    response = completed[0].get("response", {})
    output = response.get("output", []) if isinstance(response, dict) else []
    text = None
    if isinstance(output, list) and len(output) == 1 and isinstance(output[0], dict):
        content = output[0].get("content", [])
        if isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict):
            text = content[0].get("text")
    try:
        value = json.loads(text) if isinstance(text, str) else None
    except json.JSONDecodeError:
        value = None
    keys = sorted(value) if isinstance(value, dict) else []
    return {
        "completed_frames": 1,
        "response_status": response.get("status") if isinstance(response, dict) else None,
        "response_model": response.get("model") if isinstance(response, dict) else None,
        "output_top_level_keys": keys,
        "schema_description_wrapper": keys == ["properties", "type"],
    }


async def main() -> None:
    repo = Path(os.environ["ISSUE169_REPO"])
    data = json.loads(
        (repo / "docs/eval/issue-169-customer-answer-v1.json").read_text(encoding="utf-8")
    )
    sample = data["answered"][0]
    run_id = os.environ["ISSUE169_RUN_ID"]
    output = Path(os.environ["ISSUE169_OUTPUT"])
    report = {
        "schema": "issue169-official-json-schema-canary-v1",
        "run_id": run_id,
        "head_sha": os.environ["ISSUE169_HEAD"],
        "authority": "USER_COORDINATION",
        "frozen_query_id": f"{sample['id']}-a",
        "maximum_compose_calls": 1,
        "status": "RUNNING",
    }
    budget = BudgetTransport(Path(os.environ["ISSUE169_LEDGER"]), run_id)
    try:
        case = prepare(sample["questions"][0])
        retrieval_response = retrieve(case)
        retrieval = parse_knowledge_response(
            retrieval_response.status_code, retrieval_response.json()
        )
        facts = case["facts"]
        model_input = CustomerCommunicationInput(
            order_reference=ORDER,
            delay_seconds=facts["delaySeconds"],
            compensation_review_required=False,
            evidence_refs=tuple(facts["evidenceRefs"]),
            synthetic_customer_text=sample["questions"][0],
            risk_scenario="LOGISTICS_DELAY",
            logistics_status=facts.get("logisticsStatus"),
            knowledge=retrieval,
        )
        budget.query_id = report["frozen_query_id"]
        envelope = await DeepSeekResponsesCustomerCommunicationModel(
            DeepSeekCustomerCommunicationConfig.from_environment(os.environ),
            transport=budget,
            audit_sink=budget,
        ).compose(model_input)
        reply = envelope.as_request_value()
        reply["knowledgeRequestId"] = "knowledge"
        accepted = submit(case, reply)
        report.update(
            status="PASS" if accepted.status_code == 200 else "SPRING_REJECTED",
            acceptance_http=accepted.status_code,
            acceptance_body=accepted.json(),
        )
    except Exception as error:
        report.update(status="FAIL", error_type=type(error).__name__)
    finally:
        report["provider_attempt_count"] = sum(
            item["phase"] == run_id for item in budget.state["attempts"]
        )
        report["attempts"] = [asdict(record) for record in budget.records]
        report["completed_shape"] = (
            completed_shape(budget.responses[-1]["body"]) if budget.responses else None
        )
        report["ledger_pending_micro_cny"] = pending_micro_cny(budget.state["attempts"])
        budget.state["phases"][run_id]["status"] = report["status"]
        write_json(budget.path, budget.state)
        await budget.inner.aclose()
        write_json(output, report)
    if report["provider_attempt_count"] != 1 or report["status"] != "PASS":
        raise SystemExit(2)


asyncio.run(main())
