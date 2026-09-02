"""Issue #169 客户回答集的离线冻结一致性检查。"""

import hashlib
import json
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
DATASET = REPO / "docs/eval/issue-169-customer-answer-v1.json"
MANIFEST = REPO / "docs/eval/issue-169-customer-answer-v1-manifest.json"
pytestmark = pytest.mark.skipif(
    not DATASET.is_file() and not MANIFEST.is_file(),
    reason="仓库级冻结资料不在 Agent 单目录镜像构建上下文中",
)


def canonical_sha256(path: Path) -> str:
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(content.encode()).hexdigest()


def article_metadata_and_paragraphs(path: Path) -> tuple[dict[str, str], list[str]]:
    _, front_matter, body = path.read_text(encoding="utf-8").split("---", 2)
    metadata = dict(line.split(":", 1) for line in front_matter.strip().splitlines())
    paragraphs = [
        paragraph
        for paragraph in body.split("\n\n")
        if paragraph.strip() and not paragraph.lstrip().startswith("#")
    ]
    return metadata, paragraphs


def test_customer_answer_dataset_matches_public_articles() -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    answered = dataset["answered"]
    unanswered = dataset["unanswered"]
    questions = [question for item in answered for question in item["questions"]]

    assert dataset["scope"] == "CUSTOMER_PUBLIC"
    assert len(questions) == dataset["semantic_denominator"]["answered"] == 36
    assert len(unanswered) == dataset["semantic_denominator"]["unanswered"] == 12
    assert len(dataset["boundaries"]) == 8
    assert len(questions) == len(set(questions))
    assert len({item["id"] for item in answered + unanswered}) == len(answered) + len(unanswered)

    articles: dict[tuple[str, str], list[str]] = {}
    for article_id in {item["article_id"] for item in answered}:
        path = REPO / "backend/src/main/resources/knowledge" / f"{article_id}-v1.md"
        metadata, paragraphs = article_metadata_and_paragraphs(path)
        assert metadata["id"].strip() == article_id
        assert metadata["applicability"].strip() == "[CUSTOMER_PUBLIC]"
        assert metadata["status"].strip() == "PUBLISHED"
        assert metadata["current"].strip() == "true"
        articles[(article_id, metadata["version"].strip())] = paragraphs

    for item in answered:
        paragraphs = articles[(item["article_id"], item["version"])]
        assert 1 <= item["paragraph"] <= len(paragraphs)
        assert item["required_meaning"].strip()


def test_answer_freeze_manifest_matches_canonical_files() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["model_calls_at_freeze"] == 0
    assert manifest["answered"] == 36
    assert manifest["unanswered"] == 12
    assert manifest["semantic_samples"] == 48
    assert manifest["independent_boundaries"] == 8
    assert {name: canonical_sha256(REPO / name) for name in manifest["files"]} == manifest["files"]
