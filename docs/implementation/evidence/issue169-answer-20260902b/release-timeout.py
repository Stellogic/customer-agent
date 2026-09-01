import copy
import hashlib
import json
import os
import sys
from pathlib import Path


ledger_path = Path(sys.argv[1])
evidence_path = Path(sys.argv[2])
expected_before = "b864ce95d2786e020d5eb2ff12150086bf2264f0af2fa5a6676c91d427f64058"
before_bytes = ledger_path.read_bytes()
before_sha = hashlib.sha256(before_bytes).hexdigest()
if before_sha != expected_before:
    raise SystemExit(f"ledger drift: {before_sha}")

state = json.loads(before_bytes)
targets = [
    item
    for item in state["attempts"]
    if item.get("phase") == "issue169-answer-20260902b"
    and item.get("query_id") == "delivery-01-a"
    and item.get("status") == "PENDING"
    and item.get("reserved_micro_cny") == 3159552
]
if len(targets) != 1:
    raise SystemExit(f"expected one timeout reservation, found {len(targets)}")

target = targets[0]
observation = target.get("observation", {})
if not (
    observation.get("failure_classification") == "CONNECTION_TIMEOUT"
    and observation.get("usage_reported") is False
    and all(observation.get(name) is None for name in ("input_tokens", "output_tokens", "total_tokens"))
    and "charged_upper_micro_cny" not in target
):
    raise SystemExit("timeout reservation has usage or settlement drift")

before_attempt = copy.deepcopy(target)
target["status"] = "TIMEOUT_RELEASED"
target["release"] = {
    "authority": "USER",
    "reason": "CONNECTION_TIMEOUT_NO_USAGE",
    "supplier_nonbilling_confirmed": False,
    "authorized_retry_run": "issue169-answer-20260902c",
}

encoded = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()
temporary = ledger_path.with_suffix(".issue169-release.tmp")
temporary.write_bytes(encoded)
os.replace(temporary, ledger_path)
after_sha = hashlib.sha256(ledger_path.read_bytes()).hexdigest()

evidence = {
    "schema": "issue169-timeout-release-v1",
    "before_sha256": before_sha,
    "after_sha256": after_sha,
    "before_attempt": before_attempt,
    "after_attempt": target,
    "settled_charged_micro_cny": sum(
        item.get("charged_upper_micro_cny", 0)
        for item in state["attempts"]
        if item["status"] == "SETTLED"
    ),
    "unresolved_attempts": sum(item["status"] == "PENDING" for item in state["attempts"]),
    "note": "用户授权释放连接超时的未知usage预留；供应商未确认不计费。",
}
evidence_path.parent.mkdir(parents=True, exist_ok=True)
evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"before": before_sha, "after": after_sha, "status": target["status"]}))
