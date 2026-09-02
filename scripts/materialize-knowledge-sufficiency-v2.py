"""受锁物化C-v2完整72题请求hash;没有HTTP客户端、模型或账本写入。"""

import argparse
import json
import subprocess
from pathlib import Path

from baseline_agent.knowledge_sufficiency import (
    ARCHIVE_SHA256,
    DATA_SHA256,
    REPO,
    contract,
    development_rows,
    request_body,
    sha256,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPO / "scripts/test-gate-lock.ps1"),
            "-AssertInherited",
        ],
        check=True,
    )
    frozen = contract(c_v2=True)
    rows = development_rows()
    manifest = {
        "schema": "knowledge-sufficiency-c-v2-requests-v1",
        "dataset_sha256": DATA_SHA256,
        "archive_sha256": ARCHIVE_SHA256,
        "asset_sha256": frozen["asset_sha256"],
        "maximum_requests": 72,
        "requests": [
            {
                "query_id": row["id"],
                "request_sha256": sha256(
                    json.dumps(
                        request_body(row, frozen), ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
                ),
            }
            for row in rows
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(f"72 requests; sha256={sha256(args.output.read_bytes())}; API=0; ledger writes=0")


if __name__ == "__main__":
    main()
