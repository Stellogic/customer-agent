import httpx
import pytest

from baseline_agent import knowledge_evaluation
from baseline_agent.knowledge_evaluation import failure_observation, metrics, retrieval_metrics
from baseline_agent.rag_eval_v1 import EvalPrincipal, EvalQuery


def test_quality_metrics_penalize_answered_abstention_and_forbidden_results():
    def row(kind, recall, rank, hits, violations=()):
        return {
            "kind": kind,
            "recall": recall,
            "reciprocal_rank": rank,
            "results": hits,
            "violations": violations,
            "checked_prohibitions": ["wrong_version", "out_of_scope", "unauthorized"],
        }

    measured = metrics(
        [
            row("answered", 1, 1, ["hit"]),
            row("answered", 1, 0.5, ["hit"]),
            row("answered", 1, 1, ["hit"]),
            row("answered", 0, 0, []),
            row("unanswered", 0, 0, []),
            row("unanswered", 0, 0, ["wrong"], ["wrong_version"]),
        ]
    )
    assert measured["answered_recall_at_5"] == 0.75
    assert measured["answered_mrr_at_5"] == 0.625
    assert measured["unanswered_precision"] == 0.5
    assert measured["unanswered_recall"] == 0.5
    assert measured["wrong_version_top5_hit_rate"] == 1 / 6
    assert measured["out_of_scope_top5_hit_rate"] == 0
    assert measured["unauthorized_top5_hit_rate"] == 0


def test_layered_retrieval_does_not_treat_legal_candidates_as_an_answer():
    def row(kind, hits, violations=()):
        return {
            "kind": kind,
            "recall": 1.0 if kind == "answered" else 0.0,
            "reciprocal_rank": 0.5 if kind == "answered" else 0.0,
            "results": hits,
            "violations": violations,
            "checked_prohibitions": ["wrong_version", "out_of_scope", "unauthorized"],
        }

    measured = retrieval_metrics(
        [row("answered", ["supported"]), row("unanswered", ["legal_but_insufficient"])]
    )
    assert measured == {
        "answered_recall_at_5": 1.0,
        "answered_mrr_at_5": 0.5,
        "wrong_version_top5_hit_rate": 0.0,
        "out_of_scope_top5_hit_rate": 0.0,
        "unauthorized_top5_hit_rate": 0.0,
    }
    forbidden = retrieval_metrics(
        [row("answered", ["supported"]), row("unanswered", ["retired"], ["wrong_version"])]
    )
    assert forbidden["wrong_version_top5_hit_rate"] == 0.5


def test_failed_query_evidence_keeps_location_without_response_or_credentials():
    request = httpx.Request("GET", "https://user:secret@example.test/search?q=private")
    response = httpx.Response(
        503, request=request, json={"code": "INDEX_STALE", "message": "private payload"}
    )
    error = httpx.HTTPStatusError("private payload", request=request, response=response)
    assert failure_observation(error, "synthetic-query") == {
        "query_id": "synthetic-query",
        "error_type": "HTTPStatusError",
        "http_status": 503,
        "code": "INDEX_STALE",
    }


@pytest.mark.parametrize(
    ("schema", "context", "status", "error"),
    [
        ("knowledge-hybrid-v2", "CUSTOMER_PUBLIC", 403, None),
        ("knowledge-hybrid-v2", "INTERNAL", 403, httpx.HTTPStatusError),
        ("knowledge-hybrid-v1", "CUSTOMER_PUBLIC", 403, httpx.HTTPStatusError),
        ("knowledge-hybrid-v2", "CUSTOMER_PUBLIC", 200, ValueError),
    ],
)
def test_layered_scope_denial_is_explicit_without_swallowing_other_errors(
    monkeypatch, schema, context, status, error
):
    query = EvalQuery(
        "synthetic-scope",
        "out_of_scope",
        "温室浇水",
        (),
        EvalPrincipal("INTERNAL", ("SUPPORT",), ("KNOWLEDGE_READ_ACCESS",), ("INTERNAL",)),
        context,
        (),
        (),
    )
    client_type = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"code": "KNOWLEDGE_ACCESS_DENIED"})
    )
    monkeypatch.setattr(
        knowledge_evaluation.httpx,
        "Client",
        lambda **kwargs: client_type(**kwargs, transport=transport),
    )
    monkeypatch.setattr(knowledge_evaluation, "login", lambda client, query: None)
    if error is not None:
        with pytest.raises(error):
            knowledge_evaluation.run_query("https://example.test", query, schema)
    else:
        result = knowledge_evaluation.run_query("https://example.test", query, schema)
        assert result["http_status"] == 403
        assert result["results"] == []
        assert result["lexicalCandidates"] == result["vectorCandidates"] == []
