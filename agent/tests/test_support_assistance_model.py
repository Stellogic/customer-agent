"""合成 transport 仅验证170单次调用与结构边界, 不是回答质量证据。"""

import json

import httpx
import pytest

from baseline_agent.support_assistance_model import (
    generate_support_answer,
    validate_answer,
)

KNOWLEDGE = {
    "schema": "agent-knowledge-v1",
    "indexGeneration": 7,
    "results": [
        {
            "articleId": "fixture",
            "version": "v1",
            "chunkId": "chunk",
            "title": "合成政策",
            "updatedAt": "2026-09-01T00:00:00Z",
            "applicability": ["SUPPORT"],
            "startLine": 1,
            "endLine": 1,
            "snippet": "这是只用于测试的合成片段，超过二十四个字符，不能作为产品真实知识质量证明。",
        }
    ],
}
ANSWER = {
    "decision": "SUPPORTED",
    "text": "合成测试建议",
    "followUp": None,
    "citations": [{"chunkId": "chunk", "quote": KNOWLEDGE["results"][0]["snippet"]}],
}
REQUEST = {
    "kind": "draft",
    "query": "合成问题",
    "context": {"description": "合成工单"},
    "knowledge": KNOWLEDGE,
}
ENV = {"INVESTIGATION_MODEL_MODE": "deepseek-formal", "DEEPSEEK_API_KEY": "fixture-only"}


@pytest.mark.asyncio
async def test_one_call_both_decides_and_drafts_and_retains_usage():
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "fixture-response",
                "model": "deepseek-v4-flash",
                "status": "completed",
                "usage": {"input_tokens": 30, "output_tokens": 40, "total_tokens": 70},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(ANSWER)}],
                    }
                ],
            },
        )

    result = await generate_support_answer(REQUEST, ENV, transport=httpx.MockTransport(respond))
    assert len(calls) == 1
    assert result["answer"] == ANSWER
    assert result["audit"]["total_tokens"] == 70
    assert calls[0]["text"]["format"]["schema"]["properties"]["decision"]
    assert calls[0]["max_output_tokens"] == 1800


@pytest.mark.asyncio
async def test_nonformal_mode_never_generates_a_fake_product_answer():
    result = await generate_support_answer(REQUEST, {})
    assert result == {"status": "failed", "code": "MODEL_UNAVAILABLE", "audit": {"attempts": 0}}


@pytest.mark.asyncio
async def test_provider_failure_is_not_insufficient_and_does_not_retry():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503)

    result = await generate_support_answer(REQUEST, ENV, transport=httpx.MockTransport(respond))
    assert len(calls) == 1
    assert result["status"] == "failed"
    assert result["code"] == "MODEL_UNAVAILABLE"
    assert "answer" not in result


def test_no_match_may_become_explicit_insufficiency_but_is_not_a_decision_itself():
    answer = {
        "decision": "INSUFFICIENT_INFORMATION",
        "text": "现有资料不足，无法确定规则。",
        "followUp": "请补充适用情形。",
        "citations": [],
    }
    assert validate_answer(answer, {**KNOWLEDGE, "results": []}, "knowledge") == answer
    with pytest.raises(ValueError):
        validate_answer(
            {**answer, "decision": "NO_MATCH"}, {**KNOWLEDGE, "results": []}, "knowledge"
        )


@pytest.mark.parametrize("kind", ["knowledge", "policy"])
def test_supported_knowledge_and_policy_require_at_least_one_citation(kind):
    with pytest.raises(ValueError):
        validate_answer({**ANSWER, "citations": []}, KNOWLEDGE, kind)


@pytest.mark.parametrize(
    "citation",
    [
        {"chunkId": "other-request", "quote": "合成"},
        {"chunkId": "chunk", "quote": "伪造原文"},
    ],
)
def test_citation_identity_and_verbatim_quote_must_match_this_top_five(citation):
    with pytest.raises(ValueError):
        validate_answer({**ANSWER, "citations": [citation]}, KNOWLEDGE, "knowledge")


def test_model_metadata_and_reasoning_are_not_accepted():
    with pytest.raises(ValueError):
        validate_answer({**ANSWER, "reasoning": "不允许输出"}, KNOWLEDGE, "knowledge")
