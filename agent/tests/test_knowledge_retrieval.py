"""#169/#170 消费者契约源码。合成 JSON fixture 不发请求且不证明真实检索质量。"""

from dataclasses import FrozenInstanceError

import pytest

from baseline_agent.knowledge_retrieval import (
    KnowledgeFailureCode,
    KnowledgeResultStatus,
    KnowledgeRetrievalFailure,
    parse_knowledge_response,
)


def response(scope: str = "CUSTOMER_PUBLIC") -> dict:
    return {
        "schema": "agent-knowledge-v1",
        "indexGeneration": 7,
        "results": [
            {
                "articleId": "delivery-rules",
                "version": "v1",
                "chunkId": "chunk-test",
                "title": "配送规则（测试）",
                "updatedAt": "2026-08-01T00:00:00Z",
                "applicability": [scope],
                "startLine": 12,
                "endLine": 16,
                "snippet": "一般规则（测试）：这里保留超过二十四个字符的完整授权片段，不代表订单事实或已经足够回答。",
            }
        ],
    }


@pytest.mark.parametrize("scope", ["CUSTOMER_PUBLIC", "SUPPORT"])
def test_both_consumers_receive_candidates_without_an_answer_decision(scope: str) -> None:
    payload = response(scope)
    result = parse_knowledge_response(200, payload)
    source = result.sources[0]
    assert result.status is KnowledgeResultStatus.CANDIDATES_AVAILABLE
    assert result.index_generation == 7
    assert (source.article_id, source.version, source.chunk_id) == (
        "delivery-rules",
        "v1",
        "chunk-test",
    )
    assert source.updated_at == "2026-08-01T00:00:00Z"
    assert source.applicability == (scope,)
    assert (source.start_line, source.end_line) == (12, 16)
    assert source.snippet == payload["results"][0]["snippet"]
    # DTO 脱离原始可变 JSON。消费者不能把响应对象后续变更当新授权。
    payload["results"][0]["applicability"].clear()
    payload["results"].clear()
    assert result.sources == (source,)
    assert source.applicability == (scope,)
    with pytest.raises(FrozenInstanceError):
        # 故意违反只读属性约束以验证运行时也拒绝变更。
        source.title = "被修改"  # pyright: ignore[reportAttributeAccessIssue]


def test_empty_formal_results_are_no_match_not_a_model_refusal() -> None:
    payload = response()
    payload["results"] = []
    result = parse_knowledge_response(200, payload)
    assert result.status is KnowledgeResultStatus.NO_MATCH
    assert result.sources == ()


@pytest.mark.parametrize("field", ["lexicalCandidates", "vectorCandidates", "policy"])
def test_raw_retrieval_extras_never_become_answers(field: str) -> None:
    payload = response()
    payload[field] = payload["results"]
    assert_unavailable(200, payload)


@pytest.mark.parametrize("field", ["sourceFile", "score", "body"])
def test_source_payload_does_not_accept_private_fields(field: str) -> None:
    payload = response()
    payload["results"][0][field] = "private-value"
    assert_unavailable(200, payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"version": ""},
        {"updatedAt": "2026-08-01"},
        {"applicability": []},
        {"startLine": 0},
        {"endLine": 11},
    ],
)
def test_incomplete_citation_is_failure_not_partial_success(changes: dict) -> None:
    payload = response()
    payload["results"][0].update(changes)
    assert_unavailable(200, payload)


def test_invalid_success_schema_generation_or_top_five_contract_fails() -> None:
    payload = response()
    assert_unavailable(200, {**payload, "schema": "knowledge-hybrid-v1"})
    assert_unavailable(200, {**payload, "indexGeneration": True})
    assert_unavailable(200, {**payload, "results": payload["results"] * 6})


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "INDEX_STALE", KnowledgeFailureCode.ACCESS_DENIED),
        (403, None, KnowledgeFailureCode.ACCESS_DENIED),
        (404, None, KnowledgeFailureCode.ACCESS_DENIED),
        (400, None, KnowledgeFailureCode.INVALID_QUERY),
        (409, None, KnowledgeFailureCode.REQUEST_CONFLICT),
        (503, "INDEX_STALE", KnowledgeFailureCode.INDEX_STALE),
        (503, "CALIBRATION_REQUIRED", KnowledgeFailureCode.RETRIEVAL_UNAVAILABLE),
        (503, "MODEL_UNAVAILABLE", KnowledgeFailureCode.MODEL_UNAVAILABLE),
        (503, "FUSION_UNAVAILABLE", KnowledgeFailureCode.RETRIEVAL_UNAVAILABLE),
        (500, "internal-trace", KnowledgeFailureCode.RETRIEVAL_UNAVAILABLE),
        (422, "INVALID_KNOWLEDGE_CITATION", KnowledgeFailureCode.INVALID_KNOWLEDGE_CITATION),
        (422, "KNOWLEDGE_CONFLICT", KnowledgeFailureCode.KNOWLEDGE_CONFLICT),
        (422, "UNSAFE_KNOWLEDGE", KnowledgeFailureCode.UNSAFE_KNOWLEDGE),
    ],
)
def test_controlled_errors_preserve_meaning_without_raw_payload(
    status: int,
    code: str | None,
    expected: KnowledgeFailureCode,
) -> None:
    with pytest.raises(KnowledgeRetrievalFailure) as failure:
        parse_knowledge_response(status, {"code": code, "message": "private traceback"})
    assert failure.value.code is expected
    assert "private traceback" not in str(failure.value)
    assert not hasattr(failure.value, "payload")


def assert_unavailable(status: int, payload: object) -> None:
    with pytest.raises(KnowledgeRetrievalFailure) as failure:
        parse_knowledge_response(status, payload)
    assert failure.value.code is KnowledgeFailureCode.RETRIEVAL_UNAVAILABLE
