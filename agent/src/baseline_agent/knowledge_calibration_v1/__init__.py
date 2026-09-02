"""独立合成开发语料,不加载 rag-eval-v1 的查询或期望。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_PATH = Path(__file__).with_name("data.json")


@dataclass(frozen=True)
class CalibrationQuery:
    id: str
    split: str
    text: str
    expected_chunks: tuple[str, ...]
    reason: str


def load_development_data() -> tuple[dict[str, str], list[CalibrationQuery]]:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    documents: dict[str, str] = {}
    queries: list[CalibrationQuery] = []
    for topic in data["topics"]:
        prefix = topic["id"]
        documents[f"{prefix}-title"] = "# " + topic["title"]
        for index, text in enumerate(topic["paragraphs"], 1):
            documents[f"{prefix}-p{index}"] = text
        for index, query in enumerate(topic["answerable"], 1):
            queries.append(
                CalibrationQuery(
                    f"{prefix}-answerable-{index}",
                    topic["split"],
                    query["query"],
                    (f"{prefix}-p{query['paragraph']}",),
                    "指定段落直接支持回答",
                )
            )
        for index, query in enumerate(topic["unanswerable"], 1):
            queries.append(
                CalibrationQuery(
                    f"{prefix}-unanswerable-{index}",
                    topic["split"],
                    query["query"],
                    (),
                    query["reason"],
                )
            )
    return documents, queries
