import pytest

from baseline_agent.knowledge_resources import ResourceWorkload, measure_encoder, summarize_latencies


class SmallEncoder:
    """仅验证进程/计数边界，不提供 BGE 性能或质量证据。"""

    def __init__(self, directory):
        pass

    def encode(self, texts, *, query):
        return [[1.0, 0.0] for _ in texts]


class BrokenEncoder(SmallEncoder):
    def encode(self, texts, *, query):
        raise ValueError("synthetic failure")


def test_nearest_rank_and_document_throughput_have_different_units():
    metrics = summarize_latencies([10.0, 50.0, 20.0, 30.0], documents=12, elapsed_ms=120.0)
    assert metrics == {"p50_batch_ms": 20.0, "p95_batch_ms": 50.0, "documents_per_second": 100.0}


def test_fresh_process_records_peak_rss_and_excludes_warmup_from_latency_count(tmp_path):
    workload = ResourceWorkload((("甲", "乙"), ("丙",)), True, 2, 3)
    result = measure_encoder(
        "test_knowledge_resources:SmallEncoder", tmp_path, workload,
        timeout_seconds=30, hardware_id="synthetic-test-host",
    )
    assert result["status"] == "MEASURED"
    assert len(result["latencies_batch_ms"]) == 6
    assert result["peak_rss_bytes"] > 0
    assert result["cold_start_to_first_result_ms"] >= result["first_encode_ms"]
    assert result["environment"]["threads"] == 1
    assert result["filesystem_cache"] == "UNCONTROLLED_OS_CACHE"


def test_inference_failure_is_error_without_successful_resource_metrics(tmp_path):
    result = measure_encoder(
        "test_knowledge_resources:BrokenEncoder", tmp_path,
        ResourceWorkload((("甲",),), False, 0, 1),
        timeout_seconds=30, hardware_id="synthetic-test-host",
    )
    assert result["status"] == "ERROR"
    assert result["metrics"] is None
    assert result["error_type"] == "ValueError"


def test_empty_workload_is_not_a_benchmark():
    with pytest.raises(ValueError):
        ResourceWorkload((), True, 0, 1)
