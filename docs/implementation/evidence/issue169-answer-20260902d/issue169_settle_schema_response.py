import copy
import hashlib
import json
import os
import sys
from pathlib import Path


ledger_path = Path(sys.argv[1])
answers_path = Path(sys.argv[2])
evidence_path = Path(sys.argv[3])
expected_ledger_sha = "9362d1c6cbd47988f9a323973c138809cece6525c1f40286a1f554376729ffe5"
expected_answers_sha = "9e2598b7764b428d0b53fe84d4dc3c01259b198af79dc7ec6fddb87e02e9a711"

ledger_bytes = ledger_path.read_bytes()
answers_bytes = answers_path.read_bytes()
ledger_sha = hashlib.sha256(ledger_bytes).hexdigest()
answers_sha = hashlib.sha256(answers_bytes).hexdigest()
if ledger_sha != expected_ledger_sha or answers_sha != expected_answers_sha:
    raise SystemExit(f"evidence drift: ledger={ledger_sha} answers={answers_sha}")

answers = json.loads(answers_bytes)
responses = [
    item for item in answers["provider_responses"] if item.get("query_id") == "delivery-04-a"
]
if len(responses) != 1 or responses[0].get("http_status") != 200:
    raise SystemExit("expected one HTTP 200 provider response")

completed = []
for block in responses[0]["body"].split("\n\n"):
    lines = block.splitlines()
    if lines and lines[0] == "event: response.completed":
        completed.append(json.loads(next(line[6:] for line in lines if line.startswith("data: "))))
if len(completed) != 1:
    raise SystemExit(f"expected one completed frame, found {len(completed)}")

response = completed[0]["response"]
usage = response.get("usage", {})
tokens = (usage.get("input_tokens"), usage.get("output_tokens"), usage.get("total_tokens"))
if not (
    response.get("status") == "completed"
    and response.get("model") == "deepseek-v4-flash"
    and all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in tokens)
    and usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    and usage["input_tokens"] <= 1048576
    and usage["output_tokens"] <= 1536
):
    raise SystemExit("completed frame has untrusted identity or usage")

state = json.loads(ledger_bytes)
targets = [
    item
    for item in state["attempts"]
    if item.get("phase") == "issue169-answer-20260902d"
    and item.get("query_id") == "delivery-04-a"
    and item.get("status") == "PENDING"
]
if len(targets) != 1 or targets[0] is not state["attempts"][-1]:
    raise SystemExit(f"expected latest pending attempt, found {len(targets)}")
target = targets[0]
if not (
    target.get("reserved_micro_cny") == 3159552
    and target.get("observation", {}).get("failure_classification") == "SCHEMA_MISMATCH"
    and target["observation"].get("provider_http_status") == 200
    and target["observation"].get("usage_reported") is False
    and "charged_upper_micro_cny" not in target
):
    raise SystemExit("pending attempt does not match saved schema failure")

before_attempt = copy.deepcopy(target)
charged = usage["input_tokens"] * 3 + usage["output_tokens"] * 9
if charged > target["reserved_micro_cny"]:
    raise SystemExit("settled charge exceeds reservation")
target.update(status="SETTLED", charged_upper_micro_cny=charged)
target["observation"].update(
    provider_response_id=response["id"],
    response_status=response["status"],
    response_model=response["model"],
    input_tokens=usage["input_tokens"],
    output_tokens=usage["output_tokens"],
    total_tokens=usage["total_tokens"],
    cached_tokens=usage.get("input_tokens_details", {}).get("cached_tokens"),
    cache_hit=None,
    usage_reported=True,
    cache_metrics_reported="cached_tokens" in usage.get("input_tokens_details", {}),
    reasoning_tokens=usage.get("output_tokens_details", {}).get("reasoning_tokens"),
)
target["reconciliation"] = {
    "source": "docs/implementation/evidence/issue169-answer-20260902d/answers.json",
    "source_sha256": answers_sha,
    "event": "response.completed",
}

encoded = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()
temporary = ledger_path.with_suffix(".issue169-settle.tmp")
temporary.write_bytes(encoded)
os.replace(temporary, ledger_path)
after_sha = hashlib.sha256(ledger_path.read_bytes()).hexdigest()

evidence = {
    "schema": "issue169-saved-response-settlement-v1",
    "ledger_before_sha256": ledger_sha,
    "ledger_after_sha256": after_sha,
    "answers_sha256": answers_sha,
    "completed_response": {
        "id": response["id"],
        "status": response["status"],
        "model": response["model"],
        "usage": usage,
    },
    "before_attempt": before_attempt,
    "after_attempt": target,
    "settled_charged_micro_cny": sum(
        item.get("charged_upper_micro_cny", 0)
        for item in state["attempts"]
        if item["status"] == "SETTLED"
    ),
    "unresolved_attempts": sum(item["status"] == "PENDING" for item in state["attempts"]),
    "note": "供应商HTTP 200完成帧已归档；按该帧的模型身份与usage结算，schema失败保持不变。",
}
evidence_path.parent.mkdir(parents=True, exist_ok=True)
evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"before": ledger_sha, "after": after_sha, "charged": charged}))
