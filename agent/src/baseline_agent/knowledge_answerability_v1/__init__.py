"""独立训练/校准数据格式;留出只由协调指定的独立运行者读取。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
VERSION = "development-v1"


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_data(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    split = data["split"]
    expected_topics = {"training": 6, "calibration": 3, "holdout": 3}[split]
    if (
        data["schema"] != "knowledge-answerability-data-v1"
        or len(data["topics"]) != expected_topics
    ):
        raise ValueError("独立数据协议或主题数量不符")
    ids = [topic["id"] for topic in data["topics"]]
    if len(set(ids)) != len(ids) or any(
        not re.fullmatch(r"[a-z][a-z0-9-]{2,30}", key) for key in ids
    ):
        raise ValueError("主题ID重复或无效")
    for topic in data["topics"]:
        if set(topic["articles"]) != {"a", "b", "c", "d"} or len(topic["facts"]) != 6:
            raise ValueError("每主题必须四篇文档和六条事实")
        if {fact["article"] for fact in topic["facts"]} != set(topic["articles"]):
            raise ValueError("事实必须覆盖四篇文档")
        negatives = topic["negatives"]
        if len(negatives) != 12 or any(
            sum(row["kind"] == kind for row in negatives) != 6 for kind in ("missing", "mismatch")
        ):
            raise ValueError("负例配额不符")
        for fact in topic["facts"]:
            if not 1 <= len(fact["text"]) < 800 or "\n" in fact["text"]:
                raise ValueError("支持事实必须是单一短段落")
        for query in queries({"topics": [topic]}):
            if not 1 <= len(query["text"]) <= 200 or not query["reason"]:
                raise ValueError("问题或标注理由无效")
    return data


def articles(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    result = {}
    for topic in data["topics"]:
        for key, title in topic["articles"].items():
            article_id = f"development-{topic['id']}-{key}"
            body = "\n\n".join(fact["text"] for fact in topic["facts"] if fact["article"] == key)
            result[article_id] = {"title": f"{topic['title']}：{title}", "body": body}
    return result


def queries(data: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for topic in data["topics"]:
        for index, fact in enumerate(topic["facts"], 1):
            for kind in ("direct", "paraphrase"):
                result.append(
                    {
                        "id": f"{topic['id']}-{kind}-{index}",
                        "topic": topic["id"],
                        "kind": kind,
                        "text": fact[kind],
                        "answerable": True,
                        "article_id": f"development-{topic['id']}-{fact['article']}",
                        "support": fact["text"],
                        "reason": "指定事实段落完整支持所问内容",
                    }
                )
        for index, negative in enumerate(topic["negatives"], 1):
            result.append(
                {
                    "id": f"{topic['id']}-negative-{index}",
                    "topic": topic["id"],
                    "kind": negative["kind"],
                    "text": negative["text"],
                    "answerable": False,
                    "article_id": None,
                    "support": None,
                    "reason": negative["reason"],
                }
            )
    return result


def prepare_corpus(data: dict[str, Any], output: Path) -> None:
    # 独占创建本轮目录,不清空或改写任何现有知识源/数据库。
    output.mkdir(parents=True, exist_ok=False)
    for article_id, article in articles(data).items():
        text = (
            f"---\nid: {article_id}\ntitle: {article['title']}\nversion: {VERSION}\n"
            "updated_at: 2026-08-31T00:00:00Z\napplicability: [INTERNAL]\n"
            f"status: PUBLISHED\ncurrent: true\n---\n{article['body']}\n"
        )
        (output / f"{article_id}.md").write_text(text, encoding="utf-8", newline="\n")
