from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

DATASET_ID = "rag-eval-v1"
_ASSET_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class RequiredSnippet:
    text: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class AllowedHit:
    article_id: str
    version: str
    applicability: tuple[str, ...]
    source_file: str
    required_snippets: tuple[RequiredSnippet, ...]


@dataclass(frozen=True)
class ForbiddenHit:
    article_id: str
    version: str
    reason: str
    source_file: str


@dataclass(frozen=True)
class EvalPrincipal:
    subject_type: str
    roles: tuple[str, ...]
    capabilities: tuple[str, ...]
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class EvalQuery:
    id: str
    kind: str
    query: str
    query_styles: tuple[str, ...]
    principal: EvalPrincipal
    search_context: str
    allowed_hits: tuple[AllowedHit, ...]
    forbidden_hits: tuple[ForbiddenHit, ...]


@dataclass(frozen=True)
class ModelFile:
    sha256: str | None
    git_blob_sha1: str | None
    size_bytes: int | None
    required_at_runtime: bool


@dataclass(frozen=True)
class EmbeddingProtocol:
    name: str
    revision: str
    query_instruction: str
    document_instruction: str
    pooling: str
    normalize: str
    max_seq_length: int
    truncation: bool
    truncation_strategy: str
    truncation_side: str
    output_dimensions: int
    weights_not_in_git: bool
    files: dict[str, ModelFile]


@dataclass(frozen=True)
class CorpusArticle:
    article_id: str
    version: str
    status: str
    current: bool
    applicability: tuple[str, ...]
    source_file: str
    sha256: str
    body: str


@dataclass(frozen=True)
class EvalProtocol:
    model: EmbeddingProtocol
    corpus_snapshot: tuple[CorpusArticle, ...]


@dataclass(frozen=True)
class RetrievalThresholds:
    answered_recall_at_5: float
    answered_mrr_at_5: float
    unanswered_precision: float
    unanswered_recall: float
    wrong_version_top5_hit_rate: float
    out_of_scope_top5_hit_rate: float
    unauthorized_top5_hit_rate: float
    k: int


@dataclass(frozen=True)
class EvalManifest:
    content_sha256: str
    original_content_sha256: str
    review_source: str
    repeatable_execution: str
    corrections: tuple[str, ...]


@dataclass(frozen=True)
class RagEvalDataset:
    dataset_id: str
    queries: tuple[EvalQuery, ...]
    protocol: EvalProtocol
    thresholds: RetrievalThresholds
    manifest: EvalManifest


def _read_json(name: str) -> dict[str, Any]:
    payload = json.loads((_ASSET_DIR / name).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be an object")
    return cast(dict[str, Any], payload)


def compute_content_sha256() -> str:
    lines: list[str] = []
    for name in ("protocol.json", "queries.json"):
        digest = hashlib.sha256((_ASSET_DIR / name).read_bytes()).hexdigest()
        lines.append(f"{name}  {digest}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _snippet(raw: dict[str, Any]) -> RequiredSnippet:
    return RequiredSnippet(
        text=str(raw["text"]),
        start_line=int(raw["start_line"]),
        end_line=int(raw["end_line"]),
    )


def _allowed(raw: dict[str, Any]) -> AllowedHit:
    snippets = tuple(
        _snippet(item) for item in cast(list[dict[str, Any]], raw["required_snippets"])
    )
    return AllowedHit(
        article_id=str(raw["article_id"]),
        version=str(raw["version"]),
        applicability=tuple(str(item) for item in cast(list[str], raw["applicability"])),
        source_file=str(raw["source_file"]),
        required_snippets=snippets,
    )


def _forbidden(raw: dict[str, Any]) -> ForbiddenHit:
    return ForbiddenHit(
        article_id=str(raw["article_id"]),
        version=str(raw["version"]),
        reason=str(raw["reason"]),
        source_file=str(raw["source_file"]),
    )


def _principal(raw: dict[str, Any]) -> EvalPrincipal:
    return EvalPrincipal(
        subject_type=str(raw["subject_type"]),
        roles=tuple(str(item) for item in cast(list[str], raw["roles"])),
        capabilities=tuple(str(item) for item in cast(list[str], raw["capabilities"])),
        scopes=tuple(str(item) for item in cast(list[str], raw["scopes"])),
    )


def _query(raw: dict[str, Any]) -> EvalQuery:
    return EvalQuery(
        id=str(raw["id"]),
        kind=str(raw["kind"]),
        query=str(raw["query"]),
        query_styles=tuple(str(item) for item in cast(list[str], raw["query_styles"])),
        principal=_principal(cast(dict[str, Any], raw["principal"])),
        search_context=str(raw["search_context"]),
        allowed_hits=tuple(
            _allowed(item) for item in cast(list[dict[str, Any]], raw["allowed_hits"])
        ),
        forbidden_hits=tuple(
            _forbidden(item) for item in cast(list[dict[str, Any]], raw["forbidden_hits"])
        ),
    )


def _model_file(raw: dict[str, Any]) -> ModelFile:
    sha256 = raw.get("sha256")
    git_blob = raw.get("git_blob_sha1")
    size = raw.get("size_bytes")
    return ModelFile(
        sha256=str(sha256) if sha256 is not None else None,
        git_blob_sha1=str(git_blob) if git_blob is not None else None,
        size_bytes=int(size) if size is not None else None,
        required_at_runtime=bool(raw.get("required_at_runtime", True)),
    )


def _protocol(raw: dict[str, Any]) -> tuple[EvalProtocol, RetrievalThresholds]:
    model_raw = cast(dict[str, Any], raw["model"])
    files_raw = cast(dict[str, dict[str, Any]], model_raw["files"])
    model = EmbeddingProtocol(
        name=str(model_raw["name"]),
        revision=str(model_raw["revision"]),
        query_instruction=str(model_raw["query_instruction"]),
        document_instruction=str(model_raw["document_instruction"]),
        pooling=str(model_raw["pooling"]),
        normalize=str(model_raw["normalize"]),
        max_seq_length=int(model_raw["max_seq_length"]),
        truncation=bool(model_raw["truncation"]),
        truncation_strategy=str(model_raw["truncation_strategy"]),
        truncation_side=str(model_raw["truncation_side"]),
        output_dimensions=int(model_raw["output_dimensions"]),
        weights_not_in_git=bool(model_raw["weights_not_in_git"]),
        files={name: _model_file(meta) for name, meta in files_raw.items()},
    )
    threshold_raw = cast(dict[str, Any], raw["thresholds"])
    thresholds = RetrievalThresholds(
        answered_recall_at_5=float(threshold_raw["answered_recall_at_5"]),
        answered_mrr_at_5=float(threshold_raw["answered_mrr_at_5"]),
        unanswered_precision=float(threshold_raw["unanswered_precision"]),
        unanswered_recall=float(threshold_raw["unanswered_recall"]),
        wrong_version_top5_hit_rate=float(threshold_raw["wrong_version_top5_hit_rate"]),
        out_of_scope_top5_hit_rate=float(threshold_raw["out_of_scope_top5_hit_rate"]),
        unauthorized_top5_hit_rate=float(threshold_raw["unauthorized_top5_hit_rate"]),
        k=int(threshold_raw["k"]),
    )
    corpus = tuple(
        CorpusArticle(
            article_id=str(item["article_id"]),
            version=str(item["version"]),
            status=str(item["status"]),
            current=bool(item["current"]),
            applicability=tuple(str(scope) for scope in cast(list[str], item["applicability"])),
            source_file=str(item["source_file"]),
            sha256=str(item["sha256"]),
            body=str(item["body"]),
        )
        for item in cast(list[dict[str, Any]], raw["corpus_snapshot"])
    )
    return EvalProtocol(model=model, corpus_snapshot=corpus), thresholds


def _manifest(raw: dict[str, Any]) -> EvalManifest:
    return EvalManifest(
        content_sha256=str(raw["content_sha256"]),
        original_content_sha256=str(raw["original_content_sha256"]),
        review_source=str(raw["review_source"]),
        repeatable_execution=str(raw["repeatable_execution"]),
        corrections=tuple(str(item) for item in cast(list[str], raw.get("corrections", []))),
    )


@lru_cache(maxsize=1)
def load_rag_eval_v1() -> RagEvalDataset:
    queries_raw = _read_json("queries.json")
    protocol_raw = _read_json("protocol.json")
    manifest_raw = _read_json("manifest.json")
    protocol, thresholds = _protocol(protocol_raw)
    return RagEvalDataset(
        dataset_id=str(queries_raw["dataset_id"]),
        queries=tuple(_query(item) for item in cast(list[dict[str, Any]], queries_raw["queries"])),
        protocol=protocol,
        thresholds=thresholds,
        manifest=_manifest(manifest_raw),
    )


_manifest_raw = _read_json("manifest.json")
FROZEN_CONTENT_SHA256 = str(_manifest_raw["content_sha256"])
FROZEN_THRESHOLDS = load_rag_eval_v1().thresholds
