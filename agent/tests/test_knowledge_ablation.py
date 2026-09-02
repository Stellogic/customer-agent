import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from baseline_agent.knowledge_ablation import (
    MODES,
    report_template,
    run_ablation,
    run_layered_ablation,
    run_reference_rrf,
    score_candidates,
)
from baseline_agent.rag_eval_v1 import load_rag_eval_v1


def test_template_has_no_invented_measurements_or_default_decision():
    report = report_template(
        {"evidence": "synthetic-test"}, {"rrf_k": "not-frozen"}, protocol="rag-eval-v1"
    )
    assert report["schema"] == "knowledge-ablation-v1"
    assert report["status"] == "NOT_RUN"
    assert all(item["metrics"] is None for item in report["modes"].values())
    assert report["thresholds"] == asdict(load_rag_eval_v1().thresholds)
    assert report["default_change"] == "NOT_AUTHORIZED"


def test_all_modes_receive_every_frozen_query_and_independent_metrics(tmp_path):
    dataset = load_rag_eval_v1()
    calls = []
    thresholds = asdict(dataset.thresholds)
    thresholds.pop("k")

    def query_runner(mode, query):
        calls.append((mode, query.id))
        return {"id": query.id, "kind": query.kind, "results": [], "test_mode": mode}

    def metrics(rows):
        assert len(rows) == len(dataset.queries)
        modes = {row["test_mode"] for row in rows}
        assert len(modes) == 1
        values = dict(thresholds)
        if modes == {"lexical"}:
            values["answered_recall_at_5"] = 0.5
        return values

    output = tmp_path / "ablation.json"
    report = run_ablation(
        query_runner,
        metrics,
        environment={"evidence": "synthetic-test"},
        parameters={},
        output=output,
        protocol="rag-eval-v1",
    )
    assert calls == [(mode, query.id) for mode in MODES for query in dataset.queries]
    assert report["modes"]["lexical"]["status"] == "FAIL"
    assert report["modes"]["rrf"]["status"] == "PASS"
    assert report["status"] == "MEASURED"
    assert report["baseline_qualification"] == "NOT_ESTABLISHED_BY_THIS_REPORT"
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_retrieval_error_preserves_partial_evidence_and_never_counts_as_abstention(tmp_path):
    output = tmp_path / "error.json"
    calls = 0

    def unavailable(mode, query):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("must not persist secret-bearing exception text")
        return {"id": query.id, "kind": query.kind, "results": []}

    with pytest.raises(RuntimeError):
        run_ablation(unavailable, lambda rows: {}, environment={}, parameters={}, output=output)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == report["modes"]["lexical"]["status"] == "ERROR"
    assert report["modes"]["lexical"]["metrics"] is None
    assert len(report["modes"]["lexical"]["rows"]) == 1
    assert report["modes"]["dense"]["status"] == "NOT_RUN"
    assert "secret-bearing" not in output.read_text(encoding="utf-8")


def test_mismatched_query_is_not_accepted_as_frozen_evidence(tmp_path):
    with pytest.raises(ValueError, match="冻结查询"):
        run_ablation(
            lambda mode, query: {"id": "wrong", "kind": query.kind, "results": []},
            lambda rows: {},
            environment={},
            parameters={},
            output=tmp_path / "report.json",
        )


def test_reference_rrf_delegates_scoring_without_relabeling_candidates(monkeypatch, tmp_path):
    dataset = load_rag_eval_v1()
    rows = []
    measured = asdict(dataset.thresholds)
    measured.pop("k")

    def upstream_query(base_url, query):
        assert base_url == "http://reference.invalid"
        row = {
            "id": query.id,
            "kind": query.kind,
            "results": [],
            "lexicalCandidates": [{"chunkId": "lexical-only"}],
            "vectorCandidates": [{"chunkId": "dense-only"}],
            "recall": 0.0,
            "reciprocal_rank": 0.0,
        }
        rows.append(row)
        return row

    def upstream_metrics(received):
        assert len(received) == len(dataset.queries)
        assert all(actual is expected for actual, expected in zip(received, rows, strict=True))
        return measured

    def import_evaluation(name):
        assert name == "baseline_agent.knowledge_evaluation"
        return SimpleNamespace(run_query=upstream_query, metrics=upstream_metrics)

    monkeypatch.setattr("baseline_agent.knowledge_ablation.import_module", import_evaluation)
    report = run_reference_rrf(
        "http://reference.invalid",
        environment={"evidence": "synthetic-test"},
        parameters={},
        output=tmp_path / "rrf.json",
    )
    assert [row["id"] for row in rows] == [query.id for query in dataset.queries]
    assert report["status"] == "PARTIAL"
    assert report["schema"] == "knowledge-ablation-v1"
    assert report["modes"]["rrf"]["metrics"] == measured
    for mode in ("lexical", "dense"):
        assert report["modes"][mode] == {"rows": [], "metrics": None, "status": "NOT_RUN"}


def test_reference_rrf_error_leaves_single_routes_unrun(monkeypatch, tmp_path):
    def unavailable(base_url, query):
        raise RuntimeError("reference unavailable")

    monkeypatch.setattr(
        "baseline_agent.knowledge_ablation.import_module",
        lambda name: SimpleNamespace(run_query=unavailable, metrics=lambda rows: {}),
    )
    output = tmp_path / "rrf-error.json"
    with pytest.raises(RuntimeError):
        run_reference_rrf("http://reference.invalid", environment={}, parameters={}, output=output)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == report["modes"]["rrf"]["status"] == "ERROR"
    assert report["modes"]["rrf"]["metrics"] is None
    assert report["modes"]["lexical"]["status"] == report["modes"]["dense"]["status"] == "NOT_RUN"


def test_layered_template_separates_answer_thresholds_without_rewriting_v1():
    legacy = report_template({}, {}, protocol="rag-eval-v1")
    report = report_template({}, {})
    assert report["schema"] == "knowledge-ablation-v2"
    assert report["protocol"] == "rag-layered-v2"
    assert report["status"] == "NOT_RUN"
    assert report["pass_scope"] == "RETRIEVAL_ONLY"
    assert report["dataset_sha256"] == legacy["dataset_sha256"]
    assert report["model_revision"] == legacy["model_revision"]
    assert report["answer_evaluation"] == {
        "owners": [169, 170],
        "status": "NOT_EVALUATED",
        "thresholds": {"unanswered_precision": 0.90, "unanswered_recall": 0.85},
        "metrics": None,
    }
    assert report["thresholds"] == {
        "k": 5,
        "answered_recall_at_5": 0.90,
        "answered_mrr_at_5": 0.75,
        "wrong_version_top5_hit_rate": 0.0,
        "out_of_scope_top5_hit_rate": 0.0,
        "unauthorized_top5_hit_rate": 0.0,
    }
    assert legacy["thresholds"] == asdict(load_rag_eval_v1().thresholds)
    assert "answer_evaluation" not in legacy


@pytest.mark.parametrize(
    ("metric", "value", "expected"),
    [
        ("answered_recall_at_5", 0.90, "PASS"),
        ("answered_recall_at_5", 0.89, "FAIL"),
        ("unauthorized_top5_hit_rate", 0.01, "FAIL"),
    ],
)
def test_layered_retrieval_gate_keeps_unanswered_candidates(tmp_path, metric, value, expected):
    dataset = load_rag_eval_v1()
    calls = []
    measured = dict(report_template({}, {})["thresholds"])
    measured.pop("k")
    measured[metric] = value

    def query_runner(mode, query):
        calls.append((mode, query.id))
        # 合成输入仅验证编排,不是合法性或模型质量证据。
        return {
            "id": query.id,
            "kind": query.kind,
            "results": [{"chunkId": "synthetic-authorized-fragment", "score": 0.01}],
        }

    def metrics(rows):
        assert [row["id"] for row in rows] == [query.id for query in dataset.queries]
        assert any(row["kind"] == "unanswered" and row["results"] for row in rows)
        return measured

    output = tmp_path / "layered.json"
    report = run_ablation(query_runner, metrics, environment={}, parameters={}, output=output)
    assert calls == [(mode, query.id) for mode in MODES for query in dataset.queries]
    assert report["status"] == "MEASURED"
    for mode in MODES:
        assert report["modes"][mode]["status"] == expected
        assert report["modes"][mode]["metrics"] == measured
        assert all(row["results"][0]["score"] == 0.01 for row in report["modes"][mode]["rows"])
    assert report["answer_evaluation"]["status"] == "NOT_EVALUATED"
    assert report["answer_evaluation"]["metrics"] is None
    assert report["default_change"] == "NOT_AUTHORIZED"
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_single_route_scoring_counts_its_own_ranks_versions_and_forbidden_hits():
    original = load_rag_eval_v1().queries[0]
    allowed = original.allowed_hits[0]
    query = replace(original, allowed_hits=(allowed, replace(allowed, article_id="another")))
    hits = [
        {"articleId": original.forbidden_hits[0].article_id, "version": "v1"},
        {"articleId": allowed.article_id, "version": allowed.version},
    ]
    calls = []

    def matches(hit, expected):
        calls.append((hit, expected))
        return hit["articleId"] == expected.article_id and hit["version"] == expected.version

    row = score_candidates(query, hits, matches)
    assert calls
    assert row["results"] is hits
    assert row["recall"] == 0.5
    assert row["reciprocal_rank"] == 0.5
    assert row["violations"] == row["checked_prohibitions"] == ["wrong_version"]


def test_layered_adapter_uses_one_response_and_independent_route_counts(monkeypatch, tmp_path):
    dataset = load_rag_eval_v1()
    calls = []
    received = []
    original_rows = {}
    measured = dict(report_template({}, {})["thresholds"])
    measured.pop("k")

    def upstream_query(base_url, query, *, expected_schema):
        assert base_url == "http://reference.invalid"
        assert expected_schema == "knowledge-hybrid-v2"
        calls.append(query.id)
        row = {
            "id": query.id,
            "kind": query.kind,
            "schema": expected_schema,
            "http_status": 403 if query.kind == "unauthorized" else 200,
            "results": [],
            "lexicalCandidates": (
                [{"articleId": "synthetic", "version": str(i), "score": 0.01} for i in range(7)]
                if query.kind == "unanswered"
                else []
            ),
            "vectorCandidates": [],
            "recall": 0.25,
            "reciprocal_rank": 0.125,
            "checked_prohibitions": [],
            "violations": ["synthetic-rrf-only"],
        }
        original_rows[query.id] = row
        return row

    def retrieval_metrics(rows):
        received.append(rows)
        return measured

    monkeypatch.setattr(
        "baseline_agent.knowledge_ablation.import_module",
        lambda name: SimpleNamespace(
            run_query=upstream_query,
            retrieval_metrics=retrieval_metrics,
            matches=lambda hit, allowed: False,
        ),
    )
    report = run_layered_ablation(
        "http://reference.invalid", environment={}, parameters={}, output=tmp_path / "routes.json"
    )
    assert calls == [query.id for query in dataset.queries]
    assert len(received) == 3
    for mode in ("lexical", "dense"):
        for row in report["modes"][mode]["rows"]:
            assert row["recall"] == row["reciprocal_rank"] == 0.0
            assert row["violations"] == []
            assert row["http_status"] == original_rows[row["id"]]["http_status"]
    for row in report["modes"]["lexical"]["rows"]:
        if row["kind"] == "unanswered":
            assert len(row["results"]) == 5
            assert len(row["lexicalCandidates"]) == 7
    assert all(row is original_rows[row["id"]] for row in report["modes"]["rrf"]["rows"])
    assert report["answer_evaluation"]["status"] == "NOT_EVALUATED"


def test_layered_adapter_propagates_service_failure(monkeypatch, tmp_path):
    def unavailable(base_url, query, *, expected_schema):
        raise RuntimeError("retrieval unavailable")

    monkeypatch.setattr(
        "baseline_agent.knowledge_ablation.import_module",
        lambda name: SimpleNamespace(
            run_query=unavailable, retrieval_metrics=lambda rows: {}, matches=lambda *args: False
        ),
    )
    output = tmp_path / "layered-error.json"
    with pytest.raises(RuntimeError):
        run_layered_ablation(
            "http://reference.invalid", environment={}, parameters={}, output=output
        )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "ERROR"
    assert report["modes"]["lexical"]["rows"] == []
    assert report["answer_evaluation"]["metrics"] is None
    assert report["default_change"] == "NOT_AUTHORIZED"
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_layered_rejects_legacy_metrics_instead_of_relabeling_them(tmp_path):
    legacy_metrics = asdict(load_rag_eval_v1().thresholds)
    legacy_metrics.pop("k")
    output = tmp_path / "mixed-protocol.json"
    with pytest.raises(ValueError, match="指标不满足冻结协议"):
        run_ablation(
            lambda mode, query: {"id": query.id, "kind": query.kind, "results": []},
            lambda rows: legacy_metrics,
            environment={},
            parameters={},
            output=output,
        )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == report["modes"]["lexical"]["status"] == "ERROR"
    assert report["answer_evaluation"]["metrics"] is None
