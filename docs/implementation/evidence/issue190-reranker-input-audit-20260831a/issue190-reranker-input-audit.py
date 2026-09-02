import json
import sys
from pathlib import Path

from baseline_agent.knowledge_reranker import protocol, verify_directory
from baseline_agent.knowledge_sufficiency import development_rows
from transformers import AutoTokenizer

directory = verify_directory(Path(sys.argv[1]))
fixed = protocol()
tokenizer = AutoTokenizer.from_pretrained(
    str(directory), use_fast=True, local_files_only=True, trust_remote_code=False,
    truncation_side=fixed["truncation_side"],
)
observations = []
for row in development_rows():
    for hit in row["fusedCandidates"]:
        full = tokenizer(row["text"], hit["snippet"], truncation=False)["input_ids"]
        actual = tokenizer(
            row["text"], hit["snippet"], padding=True, truncation=fixed["truncation"],
            max_length=fixed["max_length"],
        )["input_ids"]
        observations.append({
            "query_id": row["id"], "chunk_id": hit["chunkId"],
            "untruncated_tokens": len(full), "actual_tokens": len(actual),
            "identical_input_ids": full == actual,
        })
report = {
    "status": "INPUT_AUDIT_COMPLETED", "model_scoring_run": False,
    "pair_count": len(observations),
    "max_untruncated_pair_tokens": max(row["untruncated_tokens"] for row in observations),
    "changed_pairs": sum(not row["identical_input_ids"] for row in observations),
    "observations": observations,
}
Path(sys.argv[2]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in report.items() if key != "observations"}))
