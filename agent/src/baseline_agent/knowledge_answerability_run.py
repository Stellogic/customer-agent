"""独立开发运行入口。通过持锁PowerShell调用,与产品共用真实Spring候选/特征。"""

from __future__ import annotations

import argparse
import json
import math
import platform
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx

from baseline_agent.knowledge_answerability import (
    FEATURE_NAMES, QUALITY, accepted_rows, fit_once, linear_score, measure,
)
from baseline_agent.knowledge_answerability_v1 import (
    ROOT, VERSION, articles, file_sha, load_data, prepare_corpus, queries,
)
from baseline_agent.knowledge_embedding import load_model_protocol


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_seal(path: Path) -> dict[str, Any]:
    seal = read_json(path)
    if (seal.get("schema") != "knowledge-answerability-holdout-seal-v1"
        or seal.get("annotationReview") != "PASS" or seal.get("topicCount") != 3
        or seal.get("queryCount") != 72 or seal.get("topicIsolation") is not True
        or seal.get("implementerHasReadContent") is not False
        or not seal.get("authorContext") or not seal.get("reviewerContext")
        or seal["authorContext"] == seal["reviewerContext"]
        or len(seal.get("datasetSha256", "")) != 64 or not seal.get("sealedAt")):
        raise ValueError("未见留出尚无有效独立封存元数据")
    return seal


def applied_holdout_policy(fit_report: Path, seal: Path) -> dict[str, Any]:
    """打开留出前核对已提交产品参数;是否已提交由PowerShell检查Git追踪与干净HEAD。"""
    fitted = read_json(fit_report)
    policy = fitted.get("proposed_policy")
    if fitted["status"] != "CALIBRATED" or not policy:
        raise ValueError("校准不可行或尚无拟合参数")
    if policy["holdoutSealSha256"] != file_sha(seal):
        raise ValueError("拟合时的留出封存承诺已改变")
    active_path = ROOT.parents[3] / "backend/src/main/resources/knowledge-answerability-logistic.json"
    active = read_json(active_path)
    if active != policy:
        raise ValueError("产品配置尚未原样应用已保存的proposal,不能打开留出")
    return policy


def login(client: httpx.Client) -> None:
    csrf = client.get("/api/auth/csrf")
    csrf.raise_for_status()
    token = csrf.json()
    response = client.post("/api/auth/login", headers={token["headerName"]: token["token"]},
        data={"username": "support-demo", "password": "local-demo-password"})
    if response.status_code != 204:
        raise ValueError("独立开发账号登录失败")
    response = client.get("/api/auth/session")
    response.raise_for_status()
    if "KNOWLEDGE_READ_ACCESS" not in response.json()["capabilities"]:
        raise ValueError("独立开发身份缺少知识权限")


def collect(data: dict[str, Any], base_url: str, report: dict[str, Any]) -> None:
    expected = articles(data)
    with httpx.Client(base_url=base_url, timeout=120) as client:
        login(client)
        state_response = client.get("/api/internal/knowledge/index")
        state_response.raise_for_status()
        state = state_response.json()
        if state["status"] != "READY" or state["failureCode"] is not None or state["articleCount"] != len(expected):
            raise ValueError("开发目录不是本分区完整的独立语料")
        chunks: dict[str, dict[str, Any]] = {}
        for article_id, source in expected.items():
            response = client.get(f"/api/internal/knowledge/articles/{article_id}")
            response.raise_for_status()
            detail = response.json()["article"]
            if (detail["version"] != VERSION or detail["body"] != source["body"]
                or detail["title"] != source["title"] or detail["applicability"] != ["INTERNAL"]
                or detail["publicationStatus"] != "PUBLISHED" or not detail["current"]
                or len(detail["versions"]) != 1):
                raise ValueError("开发正文/版本/范围与独立数据不符")
            for chunk in detail["chunks"]:
                chunks[chunk["chunkId"]] = chunk
        report["corpus"] = {"article_count": len(expected), "chunk_count": len(chunks),
            "generation": state["generation"], "source_digest": state["sourceDigest"]}
        report["rows"] = []
        for query in queries(data):
            response = client.get("/api/internal/knowledge/development-candidates",
                params={"q": query["text"], "scope": "INTERNAL"})
            response.raise_for_status()
            candidate = response.json()
            if (candidate["schema"] != "knowledge-development-v1"
                or candidate["revision"] != report["model_revision"]
                or candidate["generation"] != state["generation"]
                or candidate["featureNames"] != FEATURE_NAMES
                or len(candidate["features"]) != 4
                or any(not math.isfinite(value) for value in candidate["features"])):
                raise ValueError("真实检索特征/模型/目录代次契约不符")
            for key, limit in (("lexicalCandidates", 20), ("vectorCandidates", 20), ("fusedCandidates", 5)):
                if len(candidate[key]) > limit:
                    raise ValueError("开发候选超过既定上限")
                for hit in candidate[key]:
                    known = chunks.get(hit["chunkId"])
                    if (known is None or hit["articleId"] != known["articleId"]
                        or hit["version"] != VERSION or hit["applicability"] != ["INTERNAL"]
                        or hit["snippet"] != known["content"]):
                        raise ValueError("候选违反本分区正文/版本/权限边界")
            expected_chunks = [chunk_id for chunk_id, chunk in chunks.items()
                if query["answerable"] and chunk["articleId"] == query["article_id"]
                and chunk["content"] == query["support"]]
            if query["answerable"] and len(expected_chunks) != 1:
                raise ValueError("正例支持段落没有对应唯一真实目录片段")
            hits = [hit["chunkId"] for hit in candidate["fusedCandidates"]]
            matched = [index for index, key in enumerate(hits, 1) if key in expected_chunks]
            row = {**query, **candidate, "expected_chunks": expected_chunks,
                "recall": len(set(hits) & set(expected_chunks)) / len(expected_chunks) if expected_chunks else 0.0,
                "reciprocal_rank": 1 / min(matched) if matched else 0.0}
            if data["split"] == "holdout":
                product = client.get("/api/internal/knowledge/search", params={"q": query["text"], "scope": "INTERNAL"})
                product.raise_for_status()
                row["product"] = product.json()
            report["rows"].append(row)
        report["status"] = "COLLECTED"


def checked_observations(path: Path, split: str, head: str | None = None) -> dict[str, Any]:
    report = read_json(path)
    expected = {"training": 144, "calibration": 72, "holdout": 72}[split]
    if (report["status"] != "COLLECTED" or report["split"] != split
        or len(report["rows"]) != expected or (head and report["head_sha"] != head)):
        raise ValueError("观测报告分区/数量/受测源码不符")
    return report


def fit_reports(args: argparse.Namespace, report: dict[str, Any]) -> None:
    training = checked_observations(args.training_report, "training", args.head_sha)
    calibration = checked_observations(args.calibration_report, "calibration", args.head_sha)
    manifest = read_json(ROOT / "manifest.json")
    for observed in (training, calibration):
        expected = next(entry for entry in manifest["datasets"] if entry["split"] == observed["split"])
        if (expected["annotationReview"] != "PASS" or observed["dataset_sha256"] != expected["sha256"]
            or observed["model_revision"] != report["model_revision"]
            or observed["holdout_seal_sha256"] != file_sha(args.holdout_seal)):
            raise ValueError("开发观测不是已审阅数据/固定模型/同一封存承诺")
    if set(row["topic"] for row in training["rows"]) & set(row["topic"] for row in calibration["rows"]):
        raise ValueError("训练与校准主题重叠")
    # 真实权限/当前版本/范围回归与跨语言数值检查是独立前置,不从正常内容题推断PASS。
    safety = read_json(args.safety_report)
    required = ("authorization", "current_version", "scope", "numeric_parity")
    if safety.get("head_sha") != args.head_sha or any(safety.get("checks", {}).get(key) != "PASS" for key in required):
        raise ValueError("缺少当前源码的独立权限/版本/范围/数值回归证据")
    if version("scikit-learn") != "1.7.2":
        raise ValueError("训练器版本与预定依赖不符")
    report["environment"].update({name: version(name) for name in ("scikit-learn", "numpy", "scipy")})
    report["inputs"] = {"training": file_sha(args.training_report), "calibration": file_sha(args.calibration_report),
        "safety": file_sha(args.safety_report)}
    report.update(fit_once(training["rows"], calibration["rows"]))
    policy = report["proposed_policy"]
    if policy is not None:
        policy.update(modelRevision=report["model_revision"], sourceSha=args.head_sha,
            trainingDatasetSha256=training["dataset_sha256"],
            calibrationDatasetSha256=calibration["dataset_sha256"],
            holdoutSealSha256=file_sha(args.holdout_seal), dependencyVersions={"scikit-learn": version("scikit-learn")})
        # 拟合结果仅作为proposal保存;不能自动写产品配置。


def audit_report(args: argparse.Namespace, report: dict[str, Any]) -> None:
    policy = applied_holdout_policy(args.fit_report, args.holdout_seal)
    observed = checked_observations(args.observations, "holdout", args.head_sha)
    if (observed["dataset_sha256"] != report["holdout_seal"]["datasetSha256"]
        or policy["holdoutSealSha256"] != file_sha(args.holdout_seal)):
        raise ValueError("留出内容或封存元数据已改变")
    rows = observed["rows"]
    scores = [linear_score(row["features"], policy) for row in rows]
    decisions = accepted_rows(rows, scores, policy["threshold"])
    for row, accepted in zip(rows, decisions, strict=True):
        product = row["product"]
        actual = [hit["chunkId"] for hit in product["results"]]
        expected = [hit["chunkId"] for hit in row["fusedCandidates"]] if accepted else []
        if (actual != expected or product["policy"]["id"] != policy["id"]
            or product["policy"]["threshold"] != policy["threshold"]
            or product["policy"]["calibrationDatasetSha256"] != policy["calibrationDatasetSha256"]
            or product["generation"] != row["generation"]):
            raise ValueError("实际产品结果与同一参数的Python判定不一致")
    values = measure(rows, decisions)
    report.update(status="PASS" if all(values[key] >= target for key, target in QUALITY.items()) else "FAIL",
        metrics=values, scores=scores, observations_sha256=file_sha(args.observations),
        fit_report_sha256=file_sha(args.fit_report), proposed_policy=policy)
    report["by_topic"] = {topic: measure(
        [row for row in rows if row["topic"] == topic],
        [accepted for row, accepted in zip(rows, decisions, strict=True) if row["topic"] == topic])
        for topic in sorted({row["topic"] for row in rows})}
    report["by_kind"] = {kind: {"count": sum(row["kind"] == kind for row in rows),
        "accepted": sum(accepted for row, accepted in zip(rows, decisions, strict=True) if row["kind"] == kind)}
        for kind in ("direct", "paraphrase", "missing", "mismatch")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "collect", "fit", "audit"))
    for name in ("output", "holdout-seal"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("dataset", "corpus-output", "training-report", "calibration-report", "safety-report", "observations", "fit-report"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("run-id", "head-sha", "base-sha"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--split", choices=("training", "calibration", "holdout"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        started = time.perf_counter()
        report: dict[str, Any] = {"schema": "knowledge-answerability-run-v1", "status": "ERROR",
            "phase": args.phase, "run_id": args.run_id, "head_sha": args.head_sha,
            "base_sha": args.base_sha, "paid_model_cost_cny": 0,
            "environment": {"python": platform.python_version(), "platform": platform.platform()}}
        try:
            report["model"] = load_model_protocol()
            report["model_revision"] = report["model"]["revision"]
            report["holdout_seal"] = read_seal(args.holdout_seal)
            report["holdout_seal_sha256"] = file_sha(args.holdout_seal)
            if args.phase in ("prepare", "collect"):
                if args.split not in ("training", "calibration", "holdout"):
                    raise ValueError("数据阶段必须声明分区")
                if args.split == "holdout":
                    # 只有协调指定的独立运行者可提供留出文件;不得在校准成功前打开。
                    applied_holdout_policy(args.fit_report, args.holdout_seal)
                    if file_sha(args.dataset) != report["holdout_seal"]["datasetSha256"]:
                        raise ValueError("留出运行的先决条件不成立")
                else:
                    manifest = read_json(ROOT / "manifest.json")
                    entry = next(row for row in manifest["datasets"] if row["split"] == args.split)
                    if entry["annotationReview"] != "PASS" or file_sha(args.dataset) != entry["sha256"]:
                        raise ValueError("训练/校准数据未审阅或已改变")
                data = load_data(args.dataset)
                if data["split"] != args.split:
                    raise ValueError("文件分区与声明不符")
                report.update(split=data["split"], dataset_sha256=file_sha(args.dataset))
                if args.phase == "prepare":
                    prepare_corpus(data, args.corpus_output)
                    report["status"] = "PREPARED"
                else:
                    collect(data, args.base_url, report)
            elif args.phase == "fit":
                fit_reports(args, report)
            else:
                audit_report(args, report)
        except Exception as error:
            report["status"] = "ERROR"
            report["error"] = type(error).__name__ + ": " + str(error)
        finally:
            report["elapsed_seconds"] = time.perf_counter() - started
            json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
    if report["status"] in ("ERROR", "FAIL", "INFEASIBLE"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
