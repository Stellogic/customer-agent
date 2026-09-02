"""#169 冻结客户集调用真实产品回答接缝;沿唯一累计账本,不是独立充分性模型。"""

import asyncio
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

import httpx
from issue169_customer_knowledge_acceptance import ORDER, prepare, retrieve, submit

from baseline_agent.customer_communication_model import (
    CustomerCommunicationFailure,
    CustomerCommunicationFailureCode,
    CustomerCommunicationInput,
)
from baseline_agent.deepseek_customer_communication_model import (
    DeepSeekCustomerCommunicationConfig,
    DeepSeekResponsesCustomerCommunicationModel,
)
from baseline_agent.knowledge_retrieval import parse_knowledge_response
from baseline_agent.knowledge_sufficiency_run import write_json


class BudgetStop(Exception):
    pass


BUDGET_LIMIT_MICRO_CNY = 5_000_000


def request_reserve_micro_cny(request_content: bytes, max_output_tokens: int) -> int:
    # UTF-8 BPE input tokens cannot outnumber input bytes; output is capped by the request.
    return len(request_content) * 3 + max_output_tokens * 9


def valid_timeout_release(item: dict) -> bool:
    if item["status"] != "TIMEOUT_RELEASED":
        return False
    release = item.get("release", {})
    observation = item.get("observation", {})
    return (
        release.get("authority") == "USER"
        and release.get("reason") == "CONNECTION_TIMEOUT_NO_USAGE"
        and release.get("supplier_nonbilling_confirmed") is False
        and isinstance(release.get("authorized_retry_run"), str)
        and bool(release["authorized_retry_run"])
        and observation.get("failure_classification") == "CONNECTION_TIMEOUT"
        and observation.get("usage_reported") is False
        and all(
            observation.get(name) is None
            for name in ("input_tokens", "output_tokens", "total_tokens")
        )
        and "charged_upper_micro_cny" not in item
    )


def unresolved_attempt(item: dict) -> bool:
    if item["status"] == "SETTLED":
        return False
    return not valid_timeout_release(item)


def pending_micro_cny(attempts: list[dict]) -> int:
    return sum(item["reserved_micro_cny"] for item in attempts if unresolved_attempt(item))


def provider_transport() -> httpx.AsyncHTTPTransport:
    proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("ALL_PROXY")
    )
    return httpx.AsyncHTTPTransport(proxy=proxy, retries=0)


class BudgetTransport(httpx.AsyncBaseTransport):
    """只为本次验收拦截实际provider请求记账,不改请求、回复或产品重试。"""

    def __init__(self, ledger: Path, run_id: str):
        self.path = ledger
        self.state = json.loads(ledger.read_text(encoding="utf-8"))
        if self.state["schema"] != "issue190-sufficiency-cost-v1":
            raise BudgetStop("账本schema不符")
        if run_id in self.state["phases"]:
            raise BudgetStop("同一冻结运行已启动,禁止覆盖结果")
        if any(unresolved_attempt(item) for item in self.state["attempts"]):
            raise BudgetStop("存在未结算预留")
        releases = [item for item in self.state["attempts"] if valid_timeout_release(item)]
        if releases:
            authorized_retry = releases[-1]["release"]["authorized_retry_run"]
            authorization_consumed = any(
                item["phase"] == authorized_retry for item in self.state["attempts"]
            )
            if not authorization_consumed and authorized_retry != run_id:
                raise BudgetStop("最新超时释放未授权本次运行")
        self.phase = run_id
        self.state["phases"][run_id] = {
            "status": "RUNNING",
            "dataset": "issue169-customer-answer-v1",
        }
        self.inner = provider_transport()
        self.records = []
        self.responses = []
        self.query_id = ""
        self.stopped = None
        write_json(self.path, self.state)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.stopped:
            raise BudgetStop(self.stopped)
        body = json.loads(request.content)
        if body["model"] != "deepseek-v4-flash" or not 1 <= body["max_output_tokens"] <= 1536:
            raise BudgetStop("请求超出冻结模型/输出上限")
        if any(unresolved_attempt(item) for item in self.state["attempts"]):
            raise BudgetStop("未知usage,停止后续调用")
        spent = self.state["prior_paid_micro_cny"] + sum(
            item.get("charged_upper_micro_cny", 0) for item in self.state["attempts"]
        )
        reserve = request_reserve_micro_cny(request.content, body["max_output_tokens"])
        if spent + reserve > BUDGET_LIMIT_MICRO_CNY:
            raise BudgetStop("BUDGET_INCOMPLETE")
        self.state["attempts"].append(
            {
                "phase": self.phase,
                "query_id": self.query_id,
                "request_sha256": hashlib.sha256(request.content).hexdigest(),
                "status": "PENDING",
                "reserved_micro_cny": reserve,
            }
        )
        write_json(self.path, self.state)
        response = await self.inner.handle_async_request(request)
        observation = {"query_id": self.query_id, "http_status": response.status_code}
        self.responses.append(observation)
        original_stream = response.stream
        received = []

        class ObservedStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                async for chunk in original_stream:
                    received.append(chunk)
                    yield chunk

            async def aclose(self):
                await original_stream.aclose()
                text = b"".join(received).decode("utf-8", errors="replace")
                key = os.environ.get("DEEPSEEK_API_KEY", "")
                observation["body"] = text.replace(key, "[REDACTED]") if key else text

        response.stream = ObservedStream()
        return response

    async def aclose(self) -> None:
        # 产品每次compose创建Client;连接池只在整个串行验收结束后释放。
        pass

    async def record(self, record) -> None:
        self.records.append(record)
        entry = self.state["attempts"][-1]
        entry["observation"] = asdict(record)
        values = (record.input_tokens, record.output_tokens, record.total_tokens)
        trusted = (
            all(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0
                for value in values
            )
            and record.total_tokens == record.input_tokens + record.output_tokens
            and record.input_tokens <= 1048576
            and record.output_tokens <= 1536
            and record.response_model == "deepseek-v4-flash"
        )
        if trusted:
            charged = record.input_tokens * 3 + record.output_tokens * 9
            if charged > entry["reserved_micro_cny"]:
                raise BudgetStop("COST_BOUND_VIOLATED")
            entry.update(status="SETTLED", charged_upper_micro_cny=charged)
        else:
            self.stopped = "UNKNOWN_USAGE_OR_MODEL_IDENTITY"
        if (
            record.failure_classification
            and str(record.failure_classification) != "SCHEMA_MISMATCH"
        ):
            self.stopped = f"SUPPLIER_FAILURE:{record.failure_classification}"
        write_json(self.path, self.state)


async def main() -> None:
    repo = Path(os.environ["ISSUE169_REPO"])
    manifest = json.loads(
        (repo / "docs/eval/issue-169-customer-answer-v1-manifest.json").read_text(encoding="utf-8")
    )
    for name, expected in manifest["files"].items():
        content = (repo / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        if hashlib.sha256(content.encode()).hexdigest() != expected:
            raise BudgetStop(f"冻结文件改变: {name}")
    dataset_path = repo / "docs/eval/issue-169-customer-answer-v1.json"
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    samples = []
    for item in data["answered"]:
        for suffix, question in zip(("a", "b"), item["questions"], strict=True):
            samples.append(
                {"id": f"{item['id']}-{suffix}", "question": question, "label": "answered"}
            )
    samples.extend(
        {"id": item["id"], "question": item["question"], "label": "unanswered"}
        for item in data["unanswered"]
    )
    if len(samples) != 48:
        raise BudgetStop("冻结分母变化")
    output = Path(os.environ["ISSUE169_OUTPUT"])
    report = {
        "protocol": "rag-layered-v2-answer",
        "dataset": data["dataset_id"],
        "status": "RUNNING",
        "head_sha": os.environ["ISSUE169_HEAD"],
        "manifest": manifest,
        "rows": [
            {**sample, "status": "NOT_RUN", "semantic_review": "NOT_EVALUATED"}
            for sample in samples
        ],
    }
    run_id = os.environ["ISSUE169_RUN_ID"]
    budget = None
    current_row = None
    try:
        budget = BudgetTransport(Path(os.environ["ISSUE169_LEDGER"]), run_id)
        model = DeepSeekResponsesCustomerCommunicationModel(
            DeepSeekCustomerCommunicationConfig.from_environment(os.environ),
            transport=budget,
            audit_sink=budget,
        )
        for current_row in report["rows"]:
            budget.query_id = current_row["id"]
            start = len(budget.records)
            current_row["status"] = "PREPARING"
            case = prepare(current_row["question"])
            current_row["status"] = "RETRIEVING"
            response = retrieve(case)
            current_row.update(
                ticket=case["ticket"],
                retrieval_http=response.status_code,
                retrieval=response.json(),
            )
            retrieval = parse_knowledge_response(response.status_code, response.json())
            facts = case["facts"]
            model_input = CustomerCommunicationInput(
                order_reference=ORDER,
                delay_seconds=facts["delaySeconds"],
                compensation_review_required=False,
                evidence_refs=tuple(facts["evidenceRefs"]),
                synthetic_customer_text=current_row["question"],
                risk_scenario="LOGISTICS_DELAY",
                logistics_status=facts.get("logisticsStatus"),
                knowledge=retrieval,
            )
            current_row["compositions"] = []
            for correction in range(2):
                current_row["status"] = "COMPOSING"
                current_row["compose_count"] = correction + 1
                observation = {"number": correction + 1}
                current_row["compositions"].append(observation)
                try:
                    envelope = await model.compose(model_input)
                except BudgetStop:
                    raise
                except Exception as error:
                    observation["error"] = type(error).__name__
                    current_row["status"] = (
                        "PARSE_OR_VALIDATION_FAILED"
                        if isinstance(error, CustomerCommunicationFailure)
                        and error.code == CustomerCommunicationFailureCode.INVALID_OUTPUT
                        else "MODEL_FAILED"
                    )
                    if budget.stopped:
                        raise BudgetStop(budget.stopped) from None
                    continue
                reply = envelope.as_request_value()
                current_row["reply"] = reply.copy()
                observation["reply"] = reply.copy()
                if budget.stopped:
                    raise BudgetStop(budget.stopped)
                reply["knowledgeRequestId"] = "knowledge"
                current_row["status"] = "SUBMITTING"
                accepted = submit(case, reply)
                current_row["acceptance_http"] = accepted.status_code
                current_row["acceptance_body"] = accepted.json()
                observation.update(
                    acceptance_http=accepted.status_code, acceptance_body=accepted.json()
                )
                if accepted.status_code == 200:
                    current_row["status"] = "ACCEPTED_AWAITING_SEMANTIC_REVIEW"
                    break
                current_row["status"] = "SPRING_REJECTED"
                if accepted.status_code != 422 or accepted.json().get("code") != "UNSAFE_KNOWLEDGE":
                    break
            current_row["attempts"] = [asdict(record) for record in budget.records[start:]]
            write_json(output, report)
            print(current_row["id"], current_row["status"], flush=True)
        report["status"] = "COMPLETED_AWAITING_SEMANTIC_REVIEW"
    except Exception as error:
        if current_row is not None:
            if current_row["status"] in {"PREPARING", "RETRIEVING", "COMPOSING", "SUBMITTING"}:
                current_row["status"] += "_FAILED"
            current_row["error"] = (
                str(error) if isinstance(error, BudgetStop) else type(error).__name__
            )
        report["status"] = "STOPPED"
        report["error"] = str(error) if isinstance(error, BudgetStop) else type(error).__name__
        raise
    finally:
        if budget is not None:
            report["provider_responses"] = budget.responses
            report["attempts"] = [asdict(record) for record in budget.records]
            report["provider_attempt_count"] = sum(
                item["phase"] == run_id for item in budget.state["attempts"]
            )
            report["ledger_settled_micro_cny"] = budget.state["prior_paid_micro_cny"] + sum(
                item.get("charged_upper_micro_cny", 0) for item in budget.state["attempts"]
            )
            report["ledger_pending_micro_cny"] = pending_micro_cny(budget.state["attempts"])
            budget.state["phases"][run_id]["status"] = report["status"]
            write_json(budget.path, budget.state)
            await budget.inner.aclose()
        write_json(output, report)


if __name__ == "__main__":
    asyncio.run(main())
