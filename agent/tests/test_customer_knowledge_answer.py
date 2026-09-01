import pytest

from baseline_agent.customer_knowledge_answer import (
    parse_customer_knowledge_answer,
    validate_customer_knowledge_citations,
)
from baseline_agent.knowledge_retrieval import KnowledgeRetrievalResult, KnowledgeSource

TEXT = "包裹显示签收但未收到时，先检查代收点和同住人员；仍无法找到时，可以在当前工单补充说明。"


def retrieval(scope="CUSTOMER_PUBLIC"):
    return KnowledgeRetrievalResult(
        7,
        (
            KnowledgeSource(
                "signed-package",
                "v1",
                "signed-package:1",
                "签收核实指引",
                "2026-09-01T00:00:00Z",
                (scope,),
                1,
                2,
                TEXT,
            ),
        ),
    )


def payload(**citation_changes):
    return {
        "status": "SUPPORTED",
        "answer": "您可以先检查代收点，并询问同住人员。",
        "citations": [
            {
                "articleId": "signed-package",
                "version": "v1",
                "chunkId": "signed-package:1",
                "quote": TEXT,
                **citation_changes,
            }
        ],
    }


def test_keeps_a_complete_long_quote_without_claiming_semantic_sufficiency():
    answer = parse_customer_knowledge_answer(payload())
    validate_customer_knowledge_citations(answer, retrieval())
    assert answer.citations[0].quote == TEXT
    assert len(answer.citations[0].quote) > 24
    assert answer.as_request_value() == payload()


@pytest.mark.parametrize(
    "changes", [{"version": "v0"}, {"articleId": "other"}, {"quote": "已经为您退款"}]
)
def test_rejects_wrong_version_another_article_or_invented_quote(changes):
    answer = parse_customer_knowledge_answer(payload(**changes))
    with pytest.raises(ValueError, match="this customer retrieval"):
        validate_customer_knowledge_citations(answer, retrieval())


def test_internal_only_source_cannot_support_a_customer_answer():
    answer = parse_customer_knowledge_answer(payload())
    with pytest.raises(ValueError, match="this customer retrieval"):
        validate_customer_knowledge_citations(answer, retrieval("INTERNAL"))


def test_insufficiency_is_a_model_output_and_not_inferred_from_an_empty_result():
    answer = parse_customer_knowledge_answer(
        {
            "status": "INSUFFICIENT_INFORMATION",
            "answer": "现有资料不足以确认，请补充包裹情况。",
            "citations": [],
        }
    )
    validate_customer_knowledge_citations(answer, retrieval())
    validate_customer_knowledge_citations(answer, KnowledgeRetrievalResult(7, ()))
    assert answer.citations == ()


def test_supported_answer_requires_a_real_reference():
    value = payload()
    value["citations"] = []
    with pytest.raises(ValueError):
        parse_customer_knowledge_answer(value)
