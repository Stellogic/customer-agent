from baseline_agent.knowledge_calibration import choose_threshold, classification
from baseline_agent.knowledge_calibration_v1 import load_development_data


def test_threshold_separates_independent_examples_and_ignores_audit_labels():
    rows = [
        {"split": "calibration", "score": 0.7, "expected_chunks": ["a"]},
        {"split": "calibration", "score": 0.6, "expected_chunks": ["b"]},
        {"split": "calibration", "score": 0.4, "expected_chunks": []},
        {"split": "calibration", "score": 0.3, "expected_chunks": []},
    ]
    threshold = choose_threshold(rows)
    assert threshold == 0.5
    assert classification(rows, threshold) == {
        "answerable_acceptance": 1.0,
        "unanswerable_rejection": 1.0,
    }
    # 留出组故意与校准组矛盾,不允许选择器读取其分数/标签反向调参。
    audit = [
        {"split": "audit", "score": 0.1, "expected_chunks": ["c"]},
        {"split": "audit", "score": 0.9, "expected_chunks": []},
    ]
    assert choose_threshold(rows + audit) == threshold
    assert classification(audit, threshold) == {
        "answerable_acceptance": 0.0,
        "unanswerable_rejection": 0.0,
    }


def test_development_questions_reference_real_chunks_and_keep_topics_separate():
    documents, queries = load_development_data()
    assert len(documents) == 18
    assert len(queries) == 48
    topics = {}
    for split, expected_count in (("calibration", 32), ("audit", 16)):
        selected = [query for query in queries if query.split == split]
        assert len(selected) == expected_count
        assert sum(bool(query.expected_chunks) for query in selected) == expected_count // 2
        topics[split] = {query.id.split("-")[0] for query in selected}
    assert topics["calibration"].isdisjoint(topics["audit"])
    for query in queries:
        assert query.reason
        assert all(key in documents for key in query.expected_chunks)
