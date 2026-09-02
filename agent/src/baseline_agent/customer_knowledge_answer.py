"""客户知识回答的结构与引用约束;不检索、不调用模型,也不判定语义正确。"""

import re
from dataclasses import dataclass
from enum import StrEnum

from baseline_agent.knowledge_retrieval import KnowledgeRetrievalResult


class CustomerKnowledgeStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class CustomerKnowledgeCitation:
    article_id: str
    version: str
    chunk_id: str
    quote: str

    def as_request_value(self) -> dict[str, str]:
        return {
            "articleId": self.article_id,
            "version": self.version,
            "chunkId": self.chunk_id,
            "quote": self.quote,
        }


@dataclass(frozen=True)
class CustomerKnowledgeAnswer:
    status: CustomerKnowledgeStatus
    answer: str
    citations: tuple[CustomerKnowledgeCitation, ...]

    def as_request_value(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "answer": self.answer,
            "citations": [citation.as_request_value() for citation in self.citations],
        }


def parse_customer_knowledge_answer(raw: object) -> CustomerKnowledgeAnswer:
    if not isinstance(raw, dict) or set(raw) != {"status", "answer", "citations"}:
        raise ValueError("invalid customer knowledge answer")
    status = CustomerKnowledgeStatus(raw["status"])
    answer = raw["answer"]
    citations = raw["citations"]
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 1500:
        raise ValueError("invalid customer knowledge answer")
    if not isinstance(citations, list) or len(citations) > 5:
        raise ValueError("invalid customer knowledge citations")
    parsed = []
    for citation in citations:
        if (
            not isinstance(citation, dict)
            or set(citation) != {"articleId", "version", "chunkId", "quote"}
            or not all(isinstance(value, str) and value.strip() for value in citation.values())
        ):
            raise ValueError("invalid customer knowledge citation")
        parsed.append(
            CustomerKnowledgeCitation(
                citation["articleId"],
                citation["version"],
                citation["chunkId"],
                citation["quote"],
            )
        )
    if (status is CustomerKnowledgeStatus.SUPPORTED) != bool(parsed):
        raise ValueError("only a supported answer may cite knowledge")
    public_answer = _without_inline_citation_ids(answer, parsed)
    if not public_answer:
        raise ValueError("invalid customer knowledge answer")
    return CustomerKnowledgeAnswer(status, public_answer, tuple(parsed))


def _without_inline_citation_ids(answer: str, citations: list[CustomerKnowledgeCitation]) -> str:
    identifiers = sorted(
        {
            identifier
            for citation in citations
            for identifier in (citation.article_id, citation.chunk_id)
        },
        key=len,
        reverse=True,
    )
    cleaned = answer
    for identifier in identifiers:
        escaped = re.escape(identifier)
        cleaned = re.sub(rf"\s*[（(][^（）()]*{escaped}[^（）()]*[）)]", "", cleaned)
        cleaned = cleaned.replace(identifier, "")
    cleaned = re.sub(r"[（(]\s*[）)]", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def validate_customer_knowledge_citations(
    answer: CustomerKnowledgeAnswer,
    retrieval: KnowledgeRetrievalResult,
) -> None:
    """仅证明本次 CUSTOMER_PUBLIC 片段和逐字引文;当前版本须再由 Spring 核对。"""
    sources = {
        (source.article_id, source.version, source.chunk_id): source
        for source in retrieval.sources
        if "CUSTOMER_PUBLIC" in source.applicability
    }
    seen: set[tuple[str, str, str]] = set()
    for citation in answer.citations:
        key = (citation.article_id, citation.version, citation.chunk_id)
        source = sources.get(key)
        if key in seen or source is None or citation.quote not in source.snippet:
            raise ValueError("citation is not supported by this customer retrieval")
        seen.add(key)


def customer_knowledge_answer_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": [status.value for status in CustomerKnowledgeStatus],
            },
            "answer": {"type": "string", "minLength": 1, "maxLength": 1500},
            "citations": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        name: {"type": "string", "minLength": 1}
                        for name in ("articleId", "version", "chunkId", "quote")
                    },
                    "required": ["articleId", "version", "chunkId", "quote"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["status", "answer", "citations"],
        "additionalProperties": False,
    }
