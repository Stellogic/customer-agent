"""#169/#170 共用的受控响应 DTO 与纯解析。未接线且不发送 HTTP 请求。

只接受 Spring 适配后的正式 results 而不接受内部检索候选。结构正确不代表
当前工单有权访问或知识内容安全。授权/回执/引用校验仍由 Spring 完成。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast

KNOWLEDGE_SCHEMA = "agent-knowledge-v1"


class KnowledgeResultStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    NO_ANSWER = "NO_ANSWER"


class KnowledgeFailureCode(StrEnum):
    ACCESS_DENIED = "ACCESS_DENIED"
    INVALID_QUERY = "INVALID_QUERY"
    REQUEST_CONFLICT = "REQUEST_CONFLICT"
    CALIBRATION_REQUIRED = "CALIBRATION_REQUIRED"
    INDEX_STALE = "INDEX_STALE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"  # 指 Embedding 而不是辅助生成模型。
    RETRIEVAL_UNAVAILABLE = "RETRIEVAL_UNAVAILABLE"
    INVALID_KNOWLEDGE_CITATION = "INVALID_KNOWLEDGE_CITATION"
    KNOWLEDGE_CONFLICT = "KNOWLEDGE_CONFLICT"
    UNSAFE_KNOWLEDGE = "UNSAFE_KNOWLEDGE"


class KnowledgeRetrievalFailure(Exception):
    def __init__(self, code: KnowledgeFailureCode) -> None:
        self.code = code
        super().__init__("知识检索未返回可用的受控响应")


@dataclass(frozen=True)
class KnowledgeSource:
    article_id: str
    version: str
    chunk_id: str
    title: str
    updated_at: str
    applicability: tuple[str, ...]
    start_line: int
    end_line: int
    snippet: str


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    index_generation: int
    sources: tuple[KnowledgeSource, ...]

    @property
    def status(self) -> KnowledgeResultStatus:
        return KnowledgeResultStatus.AVAILABLE if self.sources else KnowledgeResultStatus.NO_ANSWER


def parse_knowledge_response(status_code: int, payload: object) -> KnowledgeRetrievalResult:
    """解析已解码的 JSON 值。不重试、不缓存且不把错误正文放入异常。

    200 的空 results 是 NO_ANSWER。HTTP 错误或畸形成功载荷必须失败而不能降为无答案。
    调用方仍须把 JSON 解码失败/传输异常归为 RETRIEVAL_UNAVAILABLE。
    """
    if status_code != 200:
        raise KnowledgeRetrievalFailure(_failure_code(status_code, payload))
    value = _record(payload, {"schema", "indexGeneration", "results"})
    if value["schema"] != KNOWLEDGE_SCHEMA:
        raise _unavailable()
    generation = _integer(value["indexGeneration"])
    results = value["results"]
    if generation < 0 or not isinstance(results, list) or len(results) > 5:
        raise _unavailable()
    return KnowledgeRetrievalResult(generation, tuple(_source(item) for item in results))


def _failure_code(status_code: int, payload: object) -> KnowledgeFailureCode:
    if status_code in {401, 403, 404}:
        return KnowledgeFailureCode.ACCESS_DENIED
    if status_code == 400:
        return KnowledgeFailureCode.INVALID_QUERY
    if status_code == 409:
        return KnowledgeFailureCode.REQUEST_CONFLICT
    allowed = {
        503: {
            KnowledgeFailureCode.CALIBRATION_REQUIRED,
            KnowledgeFailureCode.INDEX_STALE,
            KnowledgeFailureCode.MODEL_UNAVAILABLE,
        },
        422: {
            KnowledgeFailureCode.INVALID_KNOWLEDGE_CITATION,
            KnowledgeFailureCode.KNOWLEDGE_CONFLICT,
            KnowledgeFailureCode.UNSAFE_KNOWLEDGE,
        },
    }.get(status_code, set())
    code = payload.get("code") if isinstance(payload, Mapping) else None
    for candidate in allowed:
        if code == candidate.value:
            return candidate
    return KnowledgeFailureCode.RETRIEVAL_UNAVAILABLE


def _source(payload: object) -> KnowledgeSource:
    value = _record(
        payload,
        {
            "articleId",
            "version",
            "chunkId",
            "title",
            "updatedAt",
            "applicability",
            "startLine",
            "endLine",
            "snippet",
        },
    )
    scopes = value["applicability"]
    if not isinstance(scopes, list) or not scopes:
        raise _unavailable()
    applicability = tuple(_text(scope) for scope in scopes)
    if not set(applicability).issubset({"CUSTOMER_PUBLIC", "INTERNAL", "SUPPORT", "APPROVER"}):
        raise _unavailable()
    start_line = _integer(value["startLine"])
    end_line = _integer(value["endLine"])
    if start_line < 1 or end_line < start_line:
        raise _unavailable()
    updated_at = _text(value["updatedAt"])
    try:
        timestamp = datetime.fromisoformat(updated_at)
    except ValueError:
        raise _unavailable() from None
    if timestamp.tzinfo is None:
        raise _unavailable()
    return KnowledgeSource(
        article_id=_text(value["articleId"]),
        version=_text(value["version"]),
        chunk_id=_text(value["chunkId"]),
        title=_text(value["title"]),
        updated_at=updated_at,
        applicability=applicability,
        start_line=start_line,
        end_line=end_line,
        snippet=_text(value["snippet"]),
    )


def _record(value: object, fields: set[str]) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise _unavailable()
    return cast(Mapping[str, object], value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _unavailable()
    return value


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _unavailable()
    return value


def _unavailable() -> KnowledgeRetrievalFailure:
    return KnowledgeRetrievalFailure(KnowledgeFailureCode.RETRIEVAL_UNAVAILABLE)
