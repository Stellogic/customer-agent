from baseline_agent.knowledge_evaluation import metrics


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
