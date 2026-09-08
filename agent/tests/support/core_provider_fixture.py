"""#230 同订单双票的 HTTP 供应商夹具;正式 Agent 工厂通过 endpoint 接入。

运行: python tests/support/core_provider_fixture.py --port 8099 --mode normal
GET /evidence 仅返回受控计量元数据,GET /health 用于 runner 就绪检查。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from baseline_agent.customer_communication_model import (
    CustomerCommunicationInput,
    CustomerConversationMessage,
    FixedFakeCustomerCommunicationModel,
    PaymentCommunicationFacts,
)
from baseline_agent.deepseek_intake_model import _QUESTIONS
from baseline_agent.intake_model import (
    FixedFakeIntakeModel,
    IntakeIssue,
    IntakeModelInput,
    VisibleOrder,
    _confirms_pending_issue,
    _denies_pending_issue,
)
from baseline_agent.investigation_action_loop import DeterministicActionModel

SCHEMAS = frozenset(
    {
        "customer_intake_issue_assessments",
        "customer_intake_clarification",
        "customer_intake_understanding",
        "customer_agent_investigation_action",
        "customer_agent_investigation_judgment",
        "customer_agent_public_reply",
    }
)
ISSUE_LABELS = {
    "LOGISTICS_DELAY": "物流延迟",
    "PACKAGE_NOT_RECEIVED": "包裹未收到",
    "DUPLICATE_CHARGE": "重复扣款",
}


async def _intake(schema: str, value: dict[str, Any]) -> dict[str, Any]:
    if schema == "customer_intake_clarification":
        # 正式请求在澄清阶段仅携带问题与客户回答,不携带订单。
        kind = next(kind for kind, question in _QUESTIONS.items() if question == value["question"])
        answer = (
            "AFFIRMED"
            if _confirms_pending_issue(kind, value["customerText"])
            else "DENIED"
            if _denies_pending_issue(kind, value["customerText"])
            else "UNCLEAR"
        )
        return {"answer": answer}
    result = await FixedFakeIntakeModel().understand(
        IntakeModelInput(
            customer_message=value["customerText"],
            visible_orders=tuple(VisibleOrder(**order) for order in value["visibleOrders"]),
            current_order_reference=value["currentOrderReference"],
            current_issue_summary=value["currentIssueSummary"],
            current_issues=tuple(IntakeIssue(**issue) for issue in value["currentIssues"]),
            current_pending_issue_kinds=tuple(value["currentPendingIssueKinds"]),
            current_remaining_order_references=tuple(value["currentRemainingOrderReferences"]),
        )
    )
    if schema == "customer_intake_issue_assessments":
        issues = {issue.kind: issue.summary for issue in result.issues}
        pending = set(result.pending_issue_kinds)
        if (result.candidate_order_reference or "").startswith("ORDER-CORE-NO-COMPENSATION-2-"):
            issues.pop("LOGISTICS_DELAY", None)
            pending.discard("LOGISTICS_DELAY")
        if (result.candidate_order_reference or "").startswith("ORDER-CORE-PENDING-APPROVAL-2-"):
            pending.add("LOGISTICS_DELAY")
        return {
            "candidateOrderReference": result.candidate_order_reference,
            # 故意把请求中的其余候选都排队,覆盖显式订单范围回归。
            "remainingOrderReferences": [
                order["reference"]
                for order in value["visibleOrders"]
                if order["reference"] != result.candidate_order_reference
            ],
            "issueAssessments": {
                kind: {
                    "assessment": "UNCERTAIN"
                    if kind in pending
                    else "ASSERTED"
                    if kind in issues
                    else "NOT_MENTIONED",
                    "summary": issues.get(kind, label if kind in pending else ""),
                }
                for kind, label in ISSUE_LABELS.items()
            },
        }
    return {
        "intent": result.intent,
        "status": result.status,
        "candidateOrderReference": result.candidate_order_reference,
        "issues": [{"kind": issue.kind, "summary": issue.summary} for issue in result.issues],
        "pendingIssueKinds": list(result.pending_issue_kinds),
        "remainingOrderReferences": list(result.remaining_order_references),
        "assistantMessage": result.assistant_message,
    }


async def _content(schema: str, value: dict[str, Any], output_schema: dict) -> dict[str, Any]:
    if schema.startswith("customer_intake_"):
        return await _intake(schema, value)
    if schema == "customer_agent_investigation_action":
        decision = await DeterministicActionModel().choose(value["syntheticInvestigationFacts"])
        action = decision.action.kind.value
        assert action in output_schema["properties"]["action"]["enum"]
        result: dict[str, Any] = {"action": action}
        if "evidence" in output_schema["required"]:
            result["evidence"] = [
                {
                    "evidenceReference": claim.evidence_reference,
                    "applicability": list(claim.applicability),
                }
                for claim in decision.evidence_claims
            ]
        if "knowledgeQuery" in output_schema["required"]:
            result["knowledgeQuery"] = None
        return result
    if schema == "customer_agent_investigation_judgment":
        # 供应商实际只收到 delaySeconds,不能为调用 FixedFake judge 而捏造订单/refs。
        review = value["syntheticInvestigationFacts"]["delaySeconds"] >= 86400
        return {
            "compensationReviewRequired": review,
            "reasonCode": "LOGISTICS_DELAY" if review else "DELAY_UNDER_24_HOURS",
        }
    authorized = value["authorizedInvestigation"]
    customer = value["untrustedCustomerData"]
    payment = authorized.get("paymentFacts")
    reply = await FixedFakeCustomerCommunicationModel().compose(
        CustomerCommunicationInput(
            order_reference=authorized["orderReference"],
            delay_seconds=authorized.get("delaySeconds"),
            compensation_review_required=authorized["compensationReviewRequired"],
            evidence_refs=tuple(authorized["evidenceRefs"]),
            synthetic_customer_text=customer["syntheticCustomerText"],
            public_conversation=tuple(
                CustomerConversationMessage(**message) for message in customer["publicConversation"]
            ),
            risk_scenario=authorized.get("riskScenario"),
            payment_facts=PaymentCommunicationFacts(
                paid=payment["paid"],
                cancelled=payment["cancelled"],
                fully_refunded=payment["fullyRefunded"],
                duplicate_charge_suspected=payment["duplicateChargeSuspected"],
            )
            if payment is not None
            else None,
        )
    )
    return reply.as_request_value()


def _completed(content: dict, response_id: str, model: str, usage: dict | None) -> dict:
    # 与现有 adapter tests 的 completed response 封装一致。
    return {
        "id": response_id,
        "status": "completed",
        "model": model,
        "system_fingerprint": "synthetic-core-fixture",
        "output": [
            {
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": json.dumps(content, ensure_ascii=False)}
                ],
            }
        ],
        **({"usage": usage} if usage is not None else {}),
    }


def _streamed(payload: dict) -> bytes:
    text = payload["output"][0]["content"][0]["text"]
    midpoint = len(text) // 2
    events = [
        {"type": "response.output_text.delta", "sequence_number": 0, "delta": text[:midpoint]},
        {"type": "response.output_text.delta", "sequence_number": 1, "delta": text[midpoint:]},
        {"type": "response.completed", "sequence_number": 2, "response": payload},
    ]
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        for event in events
    ).encode()


class CoreProviderFixture:
    def __init__(
        self,
        mode: str,
        *,
        barrier_timeout: float = 8,
        audit_file: Path | None = None,
        stream_pause_seconds: float = 0,
    ):
        self.mode = mode
        self.stream_pause_seconds = stream_pause_seconds
        self.barrier_timeout = barrier_timeout
        self.audit_file = audit_file
        self.condition = threading.Condition()
        self.records: list[dict[str, Any]] = []
        self.action_kinds: set[str] = set()
        self.barrier_passed = False

    def snapshot(self) -> dict:
        with self.condition:
            return {
                "attemptCount": len(self.records),
                "actionBarrierParticipants": len(self.action_kinds),
                "actionBarrierPassed": self.barrier_passed,
                "attempts": [dict(record) for record in self.records],
            }

    def respond(self, request: dict) -> tuple[int, str, bytes]:
        schema = request["text"]["format"]["name"]
        assert schema in SCHEMAS
        value = json.loads(request["input"])
        with self.condition:
            number = len(self.records) + 1
            response_id = f"core-fixture-{uuid.uuid4()}"
            record: dict[str, Any] = {
                "attemptNumber": number,
                "schema": schema,
                "responseId": response_id,
                "httpStatus": None,
                "usage": None,
            }
            self.records.append(record)
        if schema == "customer_agent_investigation_action" and self.barrier_timeout > 0:
            kind = value["syntheticInvestigationFacts"]["issueKind"]
            assert kind in {"LOGISTICS_DELAY", "DUPLICATE_CHARGE"}
            with self.condition:
                self.action_kinds.add(kind)
                self.condition.notify_all()
                assert self.condition.wait_for(
                    lambda: len(self.action_kinds) == 2, timeout=self.barrier_timeout
                ), "CORE_FIXTURE_ACTION_BARRIER_TIMEOUT"
                self.barrier_passed = True
        payment_reply = (
            schema == "customer_agent_public_reply"
            and value["authorizedInvestigation"].get("riskScenario") == "DUPLICATE_CHARGE"
        )
        status = 400 if payment_reply and self.mode == "provider400" else 200
        usage = None
        if status == 200 and not (payment_reply and self.mode == "missing_usage"):
            usage = {
                "input_tokens": 80 + number,
                "output_tokens": 20 + number,
                "total_tokens": 100 + 2 * number,
                "input_tokens_details": {"cached_tokens": 16},
                "output_tokens_details": {"reasoning_tokens": 0},
            }
        if status == 400:
            payload = {"error": {"code": "synthetic_provider_rejected"}}
            content_type, body = "application/json", json.dumps(payload).encode()
        else:
            content = asyncio.run(_content(schema, value, request["text"]["format"]["schema"]))
            payload = _completed(content, response_id, request["model"], usage)
            content_type, body = (
                ("text/event-stream", _streamed(payload))
                if request["stream"]
                else ("application/json", json.dumps(payload, ensure_ascii=False).encode())
            )
        with self.condition:
            record.update(
                httpStatus=status, usage=usage, responseId=response_id if status == 200 else None
            )
            if self.audit_file is not None:
                self.audit_file.write_text(
                    json.dumps(self.snapshot(), ensure_ascii=False), encoding="utf-8"
                )
        return status, content_type, body


def make_server(host: str, port: int, fixture: CoreProviderFixture) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(200, "application/json", b'{"ready":true}')
            elif self.path == "/evidence":
                self._send(200, "application/json", json.dumps(fixture.snapshot()).encode())
            else:
                self._send(404, "application/json", b"{}")

        def do_POST(self) -> None:
            if self.path not in {"/responses", "/v1/responses"}:
                self._send(404, "application/json", b"{}")
                return
            try:
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                status, content_type, body = fixture.respond(request)
            except Exception:
                # 不让 stdlib traceback 或访问日志记录请求、密钥和模型原文。
                self._send(500, "application/json", b'{"error":{"code":"CORE_FIXTURE_FAILURE"}}')
                return
            self._send(status, content_type, body)

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if content_type == "text/event-stream" and fixture.stream_pause_seconds > 0:
                # 只延迟离线夹具的真实网络流,首个 SSE 事件先交给正式适配器;浏览器另行验证公开持久化。
                first, remaining = body.split(b"\n\n", 1)
                self.wfile.write(first + b"\n\n")
                self.wfile.flush()
                time.sleep(fixture.stream_pause_seconds)
                self.wfile.write(remaining)
            else:
                self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument(
        "--mode", choices=("normal", "missing_usage", "provider400"), default="normal"
    )
    parser.add_argument("--action-barrier-timeout", type=float, default=8)
    parser.add_argument("--stream-pause-seconds", type=float, default=0)
    parser.add_argument("--audit-file", type=Path)
    args = parser.parse_args()
    fixture = CoreProviderFixture(
        args.mode,
        barrier_timeout=args.action_barrier_timeout,
        audit_file=args.audit_file,
        stream_pause_seconds=args.stream_pause_seconds,
    )
    with make_server(args.host, args.port, fixture) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
