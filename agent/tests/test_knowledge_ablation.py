import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from baseline_agent.knowledge_ablation import MODES, report_template, run_ablation, run_reference_rrf
from baseline_agent.rag_eval_v1 import load_rag_eval_v1


def test_template_has_no_invented_measurements_or_default_decision():
    report = report_template({"evidence": "synthetic-test"}, {"rrf_k": "not-frozen"})
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
    report = run_ablation(query_runner, metrics, environment={"evidence": "synthetic-test"}, parameters={}, output=output)
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
            lambda rows: {}, environment={}, parameters={}, output=tmp_path / "report.json",
        )


def test_reference_rrf_delegates_scoring_without_relabeling_candidates(monkeypatch, tmp_path):
    dataset = load_rag_eval_v1()
    rows = []
    measured = asdict(dataset.thresholds)
    measured.pop("k")

    def upstream_query(base_url, query):
        assert base_url == "http://reference.invalid"
        row = {
            "id": query.id, "kind": query.kind, "results": [],
            "lexicalCandidates": [{"chunkId": "lexical-only"}],
            "vectorCandidates": [{"chunkId": "dense-only"}],
            "recall": 0.0, "reciprocal_rank": 0.0,
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
        "http://reference.invalid", environment={"evidence": "synthetic-test"},
        parameters={}, output=tmp_path / "rrf.json",
    )
    assert [row["id"] for row in rows] == [query.id for query in dataset.queries]
    assert report["status"] == "PARTIAL"
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
