"""仅验证 #170 计数语义的合成 fixture；不是 DeepSeek 质量运行。"""

from dataclasses import replace

import pytest

from baseline_agent.support_assistance_evaluation import (
    SupportAnswerObservation,
    summarize_support_answers,
)


def refusal(sample_id: str) -> SupportAnswerObservation:
    return SupportAnswerObservation(
        sample_id, "completed", "INSUFFICIENT_INFORMATION", True, True, True, True,
    )


def test_wrong_refusal_stays_in_precision_denominator():
    report = summarize_support_answers(
        {"no-answer": True, "answerable": False},
        [refusal("no-answer"), replace(refusal("answerable"), semantic_valid=False)],
    )
    assert report["refusalPrecision"] == 0.5
    assert report["refusalRecall"] == 1.0
    assert report["refusalTargetsMet"] is False
    assert report["checks"]["semantic"] == {"passed": 1, "failed": 1, "notAssessed": 0, "total": 2}


@pytest.mark.parametrize("semantic_valid", [False, None])
def test_unanswerable_label_does_not_make_invalid_or_unreviewed_refusal_correct(semantic_valid):
    report = summarize_support_answers(
        {"q": True}, [replace(refusal("q"), semantic_valid=semantic_valid)],
    )
    assert report["normalRefusals"] == 1
    assert report["correctRefusals"] == 0
    assert report["refusalPrecision"] == 0
    assert report["refusalRecall"] == 0
    assert report["allSamplesValidated"] is False


@pytest.mark.parametrize("outcome", ["retrieval_failure", "model_failure", "format_failure"])
def test_failures_are_not_correct_refusals_and_remain_in_full_denominator(outcome):
    report = summarize_support_answers(
        {"good": True, "failed": True, "not-run": True},
        [refusal("good"), replace(refusal("failed"), outcome=outcome, structure_valid=False)],
    )
    assert report["normalRefusals"] == 1
    assert report["refusalRecall"] == 1 / 3
    assert report["totalSamples"] == 3
    assert report["failureCounts"] == {outcome: 1}
    assert report["missingSampleIds"] == ["not-run"]
    assert report["allSamplesValidated"] is False
    assert report["checks"]["semantic"]["notAssessed"] == 2


def test_metrics_alone_do_not_hide_failure_on_an_answerable_sample():
    report = summarize_support_answers(
        {"no-answer": True, "answerable": False},
        [refusal("no-answer"), SupportAnswerObservation("answerable", "model_failure")],
    )
    assert report["refusalTargetsMet"] is True
    assert report["allSamplesValidated"] is False
    assert report["checks"]["structure"]["total"] == 2
    assert "PASS" not in report.values()


@pytest.mark.parametrize("change", [
    {"decision": "SUPPORTED"}, {"insufficiency_explained": False},
    {"structure_valid": False}, {"citation_valid": False},
])
def test_only_explicit_and_valid_insufficiency_counts(change):
    report = summarize_support_answers({"q": True}, [replace(refusal("q"), **change)])
    assert report["normalRefusals"] == 0
    assert report["refusalPrecision"] is None
    assert report["refusalRecall"] == 0


def test_empty_retrieval_itself_cannot_be_counted_as_a_refusal():
    # 检索空结果尚未有回答观察记录；不得生成一条假 INSUFFICIENT_INFORMATION。
    report = summarize_support_answers({"q": True}, [])
    assert report["normalRefusals"] == 0
    assert report["missingSampleIds"] == ["q"]
    assert report["allSamplesValidated"] is False


def test_complete_synthetic_rows_only_prove_counter_math():
    report = summarize_support_answers({"q": True}, [refusal("q")])
    assert report["refusalTargetsMet"] is True
    assert report["allSamplesValidated"] is True
    assert "overallPass" not in report


def test_duplicate_unknown_and_empty_sample_sets_fail_fast():
    with pytest.raises(ValueError):
        summarize_support_answers({"q": True}, [refusal("q"), refusal("q")])
    with pytest.raises(ValueError):
        summarize_support_answers({"q": True}, [refusal("other")])
    with pytest.raises(ValueError):
        summarize_support_answers({}, [])
