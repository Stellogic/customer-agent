from __future__ import annotations

import inspect
from collections import Counter

import baseline_agent.rag_eval_v1 as rag_eval_v1
from baseline_agent.rag_eval_v1 import (
    DATASET_ID,
    FROZEN_CONTENT_SHA256,
    FROZEN_THRESHOLDS,
    compute_content_sha256,
    load_rag_eval_v1,
)

_CURRENT_ARTICLES = frozenset(
    {("approval-review", "v1"), ("logistics-delay", "v2"), ("refund-policy", "v1")}
)
_COLLOQUIAL_STYLES = frozenset({"colloquial", "ellipsis"})
_VARIANT_STYLES = frozenset({"typo", "abbreviation", "synonym"})


def test_dataset_id_and_offline_loader_do_not_touch_network_or_models() -> None:
    source = inspect.getsource(load_rag_eval_v1)
    assert "http" not in source.lower()
    assert "deepseek" not in source.lower()
    assert "sentence_transformers" not in source
    assert "torch" not in source
    dataset = load_rag_eval_v1()
    assert dataset.dataset_id == DATASET_ID == "rag-eval-v1"
    assert dataset.protocol.model.revision == "7999e1d3359715c523056ef9478215996d62a620"


def test_query_counts_cover_current_articles_and_expression_styles() -> None:
    dataset = load_rag_eval_v1()
    kinds = Counter(query.kind for query in dataset.queries)
    assert len(dataset.queries) >= 60
    assert kinds["answered"] >= 36
    assert kinds["unanswered"] >= 12
    assert kinds["wrong_version"] + kinds["out_of_scope"] >= 12

    answered = [query for query in dataset.queries if query.kind == "answered"]
    coverage = Counter()
    for query in answered:
        for hit in query.allowed_hits:
            coverage[(hit.article_id, hit.version)] += 1
    for article in _CURRENT_ARTICLES:
        assert coverage[article] >= 3, article

    colloquial = sum(1 for query in answered if _COLLOQUIAL_STYLES.intersection(query.query_styles))
    variants = sum(1 for query in answered if _VARIANT_STYLES.intersection(query.query_styles))
    assert colloquial >= 12
    assert variants >= 8


def test_answered_queries_record_allowed_article_version_scope_and_snippet() -> None:
    dataset = load_rag_eval_v1()
    for query in dataset.queries:
        if query.kind != "answered":
            continue
        assert query.allowed_hits, query.id
        for hit in query.allowed_hits:
            assert (hit.article_id, hit.version) in _CURRENT_ARTICLES
            assert hit.applicability
            assert hit.source_file.startswith("backend/src/main/resources/knowledge/")
            assert hit.required_snippets
            for snippet in hit.required_snippets:
                assert snippet.text.strip()
                assert snippet.start_line in {12, 14}
                assert snippet.end_line == snippet.start_line


def test_negative_queries_forbid_wrong_version_out_of_scope_and_unauthorized_hits() -> None:
    dataset = load_rag_eval_v1()
    wrong_version = [query for query in dataset.queries if query.kind == "wrong_version"]
    out_of_scope = [query for query in dataset.queries if query.kind == "out_of_scope"]
    unanswered = [query for query in dataset.queries if query.kind == "unanswered"]
    assert len(wrong_version) >= 6
    assert len(out_of_scope) >= 6
    assert all(not query.allowed_hits for query in unanswered)
    assert any(
        any(hit.reason == "wrong_version" for hit in query.forbidden_hits)
        for query in wrong_version
    )
    assert any(
        any(hit.reason == "out_of_scope" for hit in query.forbidden_hits) for query in out_of_scope
    )
    assert any(
        any(hit.reason == "unauthorized" for hit in query.forbidden_hits)
        for query in dataset.queries
        if query.kind == "unauthorized"
    )
    unauthorized = [query for query in dataset.queries if query.kind == "unauthorized"]
    assert len(unauthorized) >= 4
    assert all(not query.allowed_hits for query in unauthorized)
    assert all(
        "KNOWLEDGE_READ_ACCESS" not in query.principal.capabilities for query in unauthorized
    )
    assert all(
        query.forbidden_hits and all(hit.reason == "unauthorized" for hit in query.forbidden_hits)
        for query in unauthorized
    )


def test_protocol_freezes_embedding_contract_without_implementing_retrieval() -> None:
    protocol = load_rag_eval_v1().protocol
    model = protocol.model
    assert model.name == "BAAI/bge-small-zh-v1.5"
    assert model.revision == "7999e1d3359715c523056ef9478215996d62a620"
    assert model.query_instruction == "为这个句子生成表示以用于检索相关文章："
    assert model.document_instruction == ""
    assert model.pooling == "cls"
    assert model.normalize == "l2"
    assert model.max_seq_length == 512
    assert model.truncation is True
    assert model.truncation_strategy == "longest_first"
    assert model.truncation_side == "right"
    assert model.output_dimensions == 512
    assert model.weights_not_in_git is True
    assert "model.safetensors" in model.files
    assert (
        model.files["model.safetensors"].sha256
        == "354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026"
    )
    source = inspect.getsource(rag_eval_v1)
    assert "pgvector" not in source
    assert "reciprocal" not in source.lower()


def test_thresholds_are_frozen_before_any_retrieval_result() -> None:
    thresholds = load_rag_eval_v1().thresholds
    assert thresholds == FROZEN_THRESHOLDS
    assert thresholds.answered_recall_at_5 == 0.90
    assert thresholds.answered_mrr_at_5 == 0.75
    assert thresholds.unanswered_precision == 0.90
    assert thresholds.unanswered_recall == 0.85
    assert thresholds.wrong_version_top5_hit_rate == 0.0
    assert thresholds.out_of_scope_top5_hit_rate == 0.0
    assert thresholds.unauthorized_top5_hit_rate == 0.0


def test_required_snippets_are_substrings_of_frozen_corpus_bodies() -> None:
    dataset = load_rag_eval_v1()
    bodies = {
        (article.article_id, article.version): article.body
        for article in dataset.protocol.corpus_snapshot
    }
    assert {("approval-review", "v1"), ("logistics-delay", "v2"), ("refund-policy", "v1")} <= set(
        bodies
    )
    for query in dataset.queries:
        for hit in query.allowed_hits:
            body = bodies[(hit.article_id, hit.version)]
            for snippet in hit.required_snippets:
                assert snippet.text in body, query.id


def test_content_hash_matches_frozen_manifest_and_original_hash_is_retained() -> None:
    dataset = load_rag_eval_v1()
    digest = compute_content_sha256()
    assert digest == FROZEN_CONTENT_SHA256
    assert dataset.manifest.content_sha256 == FROZEN_CONTENT_SHA256
    assert dataset.manifest.original_content_sha256 == FROZEN_CONTENT_SHA256
    assert dataset.manifest.corrections == ()
    assert dataset.manifest.review_source.startswith("GitHub Issue #189")
    assert "offline" in dataset.manifest.repeatable_execution.lower()
