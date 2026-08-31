"""仅受锁离线物化冻结请求字节hash,不创建账本或HTTP客户端。"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo / "agent/src"))
from baseline_agent.knowledge_sufficiency import (
    ARCHIVE_SHA256, DATA_SHA256, contract, development_rows, request_body, sha256,
)
from baseline_agent.knowledge_sufficiency_run import REMAINING_MANIFEST_SHA, remaining_manifest

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--run-id", required=True)
args = parser.parse_args()
subprocess.run(["pwsh", "-NoProfile", "-File", str(repo / "scripts/test-gate-lock.ps1"),
                "-AssertInherited"], check=True, capture_output=True)
started = time.perf_counter()
frozen = contract()
manifest = remaining_manifest()
rows = development_rows()[5:]
assert [row["id"] for row in rows] == [item["query_id"] for item in manifest["requests"]]
assert len(rows) == 67
requests = []
byte_lengths = []
for row in rows:
    encoded = json.dumps(request_body(row, frozen), ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    requests.append({"query_id": row["id"], "request_sha256": sha256(encoded)})
    byte_lengths.append(len(encoded))
result = {
    "schema": "issue190-remaining67-request-bytes-v1",
    "source_manifest_sha256": REMAINING_MANIFEST_SHA,
    "archive_sha256": ARCHIVE_SHA256,
    "dataset_sha256": DATA_SHA256,
    "asset_sha256": frozen["asset_sha256"],
    "requests": requests,
}
content = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
args.output.mkdir(parents=True, exist_ok=True)
with (args.output / "request-list.json").open("xb") as output:
    output.write(content)
evidence = {
    "run_id": args.run_id,
    "head_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
    "base_sha": subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=repo, text=True).strip(),
    "request_count": len(requests),
    "request_list_sha256": sha256(content),
    "utf8_byte_lengths": byte_lengths,
    "elapsed_seconds": time.perf_counter() - started,
    "http_calls": 0,
    "model_calls": 0,
    "ledger_modified": False,
}
(args.output / "materialization.json").write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps({key: evidence[key] for key in
                  ("request_count", "request_list_sha256", "http_calls", "model_calls")}))
