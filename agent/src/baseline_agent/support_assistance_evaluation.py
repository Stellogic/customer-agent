"""#170 rag-layered-v2 回答质量的纯计数，不调用模型或读取验收题目。

输入由未来冻结执行协议的逐题结果和独立标注提供；不能用模型自称的校验状态。
不返回整体验收 PASS：实际模型、数据哈希、prompt/schema、费用和运行证据须另行核验。
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SupportAnswerObservation:
    sample_id: str
    outcome: Literal["completed", "retrieval_failure", "model_failure", "format_failure"]
    decision: Literal["SUPPORTED", "INSUFFICIENT_INFORMATION"] | None = None
    insufficiency_explained: bool = False
    structure_valid: bool | None = None
    citation_valid: bool | None = None
    semantic_valid: bool | None = None


def summarize_support_answers(
    expected_unanswerable: Mapping[str, bool],
    observations: Sequence[SupportAnswerObservation],
) -> dict[str, object]:
    """完整冻结分母由 expected_unanswerable 提供；缺失样本保留为未评估。

    正确拒答须标签为无答案且独立语义校验通过；recall 保留全部无答案题分母。
    模型宣称不足但实际可回答仍是错误拒答，不能用 semantic_valid=False 把它从分母删掉。
    """
    if not expected_unanswerable:
        raise ValueError("冻结样本集不能为空")
    by_id: dict[str, SupportAnswerObservation] = {}
    for row in observations:
        if row.sample_id not in expected_unanswerable or row.sample_id in by_id:
            raise ValueError("样本标识不在冻结集合内或重复")
        by_id[row.sample_id] = row

    refusals = [
        row for row in observations
        if row.outcome == "completed"
        and row.structure_valid is True
        and row.citation_valid is True
        and row.decision == "INSUFFICIENT_INFORMATION"
        and row.insufficiency_explained
    ]
    correct = sum(
        expected_unanswerable[row.sample_id] and row.semantic_valid is True for row in refusals
    )
    unanswerable_count = sum(expected_unanswerable.values())
    precision = correct / len(refusals) if refusals else None
    recall = correct / unanswerable_count if unanswerable_count else None
    missing = sorted(set(expected_unanswerable) - set(by_id))
    failures = Counter(row.outcome for row in observations if row.outcome != "completed")

    checks = {}
    for label, attribute in (
        ("structure", "structure_valid"),
        ("citation", "citation_valid"),
        ("semantic", "semantic_valid"),
    ):
        values = []
        for key in expected_unanswerable:
            row = by_id.get(key)
            if row is None or row.outcome != "completed":
                values.append(False if row is not None and row.outcome == "format_failure" and label == "structure" else None)
            else:
                values.append(getattr(row, attribute))
        checks[label] = {
            "passed": sum(value is True for value in values),
            "failed": sum(value is False for value in values),
            "notAssessed": sum(value is None for value in values),
            "total": len(expected_unanswerable),
        }

    return {
        "protocol": "rag-layered-v2",
        "path": "HUMAN_SUPPORT_ASSISTANCE",
        "totalSamples": len(expected_unanswerable),
        "observedSamples": len(by_id),
        "missingSampleIds": missing,
        "failureCounts": dict(failures),
        "normalRefusals": len(refusals),
        "correctRefusals": correct,
        "unanswerableSamples": unanswerable_count,
        "refusalPrecision": precision,
        "refusalRecall": recall,
        "refusalTargetsMet": precision is not None and recall is not None and precision >= 0.90 and recall >= 0.85,
        "checks": checks,
        "allSamplesValidated": not missing and not failures and all(
            counts["passed"] == len(expected_unanswerable) for counts in checks.values()
        ),
    }
