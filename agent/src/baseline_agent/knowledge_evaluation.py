"""通过真实 Spring 会话/API 执行冻结题,不将服务故障计作正确拒答。"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx
import psycopg

from baseline_agent.knowledge_embedding import configured_encoder
from baseline_agent.rag_eval_v1 import (
    AllowedHit,
    EvalQuery,
    compute_content_sha256,
    load_rag_eval_v1,
)


def matches(hit: dict[str, Any], allowed: AllowedHit) -> bool:
    return (
        hit["articleId"] == allowed.article_id
        and hit["version"] == allowed.version
        and set(hit["applicability"]) == set(allowed.applicability)
        and allowed.source_file.endswith("/" + hit["sourceFile"])
        and all(
            snippet.text in hit["snippet"]
            and hit["startLine"] <= snippet.start_line <= snippet.end_line <= hit["endLine"]
            for snippet in allowed.required_snippets
        )
    )


def metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    """保留旧检索空列表拒答口径,不得把新版结果标作旧门通过。"""
    answered = [row for row in rows if row["kind"] == "answered"]
    unanswered = [row for row in rows if row["kind"] == "unanswered"]
    abstentions = [row for row in answered + unanswered if not row["results"]]
    true_abstentions = sum(not row["results"] for row in unanswered)
    return {
        **retrieval_metrics(rows),
        "unanswered_precision": true_abstentions / len(abstentions) if abstentions else 0.0,
        "unanswered_recall": true_abstentions / len(unanswered),
    }


def retrieval_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    """新版只度量召回/排名/硬过滤,完整保留无答案样本但不猜测回答充分性。"""
    answered = [row for row in rows if row["kind"] == "answered"]
    values = {
        "answered_recall_at_5": sum(row["recall"] for row in answered) / len(answered),
        "answered_mrr_at_5": sum(row["reciprocal_rank"] for row in answered) / len(answered),
    }
    for reason in ("wrong_version", "out_of_scope", "unauthorized"):
        relevant = [row for row in rows if reason in row["checked_prohibitions"]]
        values[f"{reason}_top5_hit_rate"] = sum(
            reason in row["violations"] for row in relevant
        ) / len(relevant)
    return values


def frozen_corpus_differences(
    actual: list[tuple[Any, ...]], expected: list[tuple[Any, ...]]
) -> dict[str, Any] | None:
    """冻结条目必须原样保留。后续正式发布的知识作为真实检索干扰项参与评测。"""
    actual_by_version = {(row[0], row[1]): row for row in actual}
    missing_versions: list[list[str]] = []
    mismatched_columns: dict[str, list[int]] = {}
    for target in expected:
        key = (target[0], target[1])
        row = actual_by_version.get(key)
        if row is None:
            missing_versions.append(list(key))
            continue
        changed = [
            index
            for index, (value, wanted) in enumerate(zip(row, target, strict=True))
            if value != wanted
        ]
        if changed:
            mismatched_columns[f"{key[0]}:{key[1]}"] = changed
    if not missing_versions and not mismatched_columns:
        return None
    return {
        "actual_count": len(actual),
        "expected_count": len(expected),
        "missing_versions": missing_versions,
        "mismatched_columns": mismatched_columns,
    }


def login(client: httpx.Client, query: EvalQuery) -> None:
    principal = query.principal
    if principal.subject_type == "CUSTOMER":
        username = "customer-demo"
    else:
        role = "approver" if "APPROVER" in principal.roles else "support"
        suffix = "demo" if "KNOWLEDGE_READ_ACCESS" in principal.capabilities else "no-knowledge"
        username = f"{role}-{suffix}"
    csrf = client.get("/api/auth/csrf")
    csrf.raise_for_status()
    token = csrf.json()
    response = client.post(
        "/api/auth/login",
        headers={token["headerName"]: token["token"]},
        data={"username": username, "password": "local-demo-password"},
    )
    if response.status_code != 204:
        raise ValueError("冻结身份登录失败")
    session_response = client.get("/api/auth/session")
    session_response.raise_for_status()
    session = session_response.json()
    if (
        session["subjectType"] != principal.subject_type
        or (
            ("KNOWLEDGE_READ_ACCESS" in session["capabilities"])
            != ("KNOWLEDGE_READ_ACCESS" in principal.capabilities)
        )
        or (principal.subject_type == "INTERNAL" and set(session["roles"]) != set(principal.roles))
    ):
        raise ValueError("真实会话与冻结身份不符")


def failure_observation(error: Exception, query_id: str | None) -> dict[str, Any]:
    """记录失败位置和协议错误码,不保存请求、响应正文或带凭据地址。"""
    result: dict[str, Any] = {
        "query_id": query_id,
        "error_type": type(error).__name__,
        "http_status": None,
        "code": None,
    }
    if isinstance(error, httpx.HTTPStatusError):
        result["http_status"] = error.response.status_code
        try:
            body = error.response.json()
        except ValueError:
            body = None
        code = body.get("code") if isinstance(body, dict) else None
        if code in (
            "KNOWLEDGE_ACCESS_DENIED",
            "INVALID_KNOWLEDGE_QUERY",
            "INDEX_STALE",
            "MODEL_UNAVAILABLE",
            "RETRIEVAL_UNAVAILABLE",
            "FUSION_UNAVAILABLE",
        ):
            result["code"] = code
    return result


def run_query(
    base_url: str, query: EvalQuery, expected_schema: str = "knowledge-hybrid-v1"
) -> dict[str, Any]:
    with httpx.Client(base_url=base_url, timeout=90) as client:
        login(client, query)
        scope = "CUSTOMER_PUBLIC" if query.search_context == "CUSTOMER_PUBLIC" else "INTERNAL"
        response = client.get(
            "/api/internal/knowledge/search", params={"q": query.query, "scope": scope}
        )
        denied = (
            query.principal.subject_type != "INTERNAL"
            or "KNOWLEDGE_READ_ACCESS" not in query.principal.capabilities
        )
        # 本入口只请求 INTERNAL 或 CUSTOMER_PUBLIC; 内部检索 API 不授予后者。
        if expected_schema == "knowledge-hybrid-v2":
            denied = denied or scope == "CUSTOMER_PUBLIC"
            if denied and response.status_code != 403:
                response.raise_for_status()
                raise ValueError("预期权限拒绝必须返回 HTTP 403")
        if response.status_code == 403 and denied:
            result: dict[str, Any] = {
                "results": [],
                "lexicalCandidates": [],
                "vectorCandidates": [],
            }
        else:
            response.raise_for_status()
            result = response.json()
            if (
                result["schema"] != expected_schema
                or result["revision"] != load_rag_eval_v1().protocol.model.revision
            ):
                raise ValueError("检索协议不符")
    hits = result["results"]
    if len(hits) > 5:
        raise ValueError("结果超过冻结 Top-5")
    matched = [any(matches(hit, allowed) for hit in hits) for allowed in query.allowed_hits]
    ranks = [
        i + 1
        for i, hit in enumerate(hits)
        if any(matches(hit, allowed) for allowed in query.allowed_hits)
    ]
    violations = {
        forbidden.reason
        for forbidden in query.forbidden_hits
        if any(
            hit["articleId"] == forbidden.article_id and hit["version"] == forbidden.version
            for hit in hits
        )
    }
    # 越权/不适用时任何内容都是违规,不能只检查预先列出的几个条目。
    if denied and hits:
        violations.add("unauthorized")
    if query.kind == "out_of_scope" and hits:
        violations.add("out_of_scope")
    if (denied or query.kind == "out_of_scope") and (
        result["lexicalCandidates"] or result["vectorCandidates"]
    ):
        raise ValueError("过滤前候选泄露")
    return {
        "id": query.id,
        "kind": query.kind,
        "http_status": response.status_code,
        "recall": sum(matched) / len(matched) if matched else 0.0,
        "reciprocal_rank": 1 / min(ranks) if ranks else 0.0,
        "checked_prohibitions": sorted({item.reason for item in query.forbidden_hits}),
        "violations": sorted(violations),
        **result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--head-sha")
    parser.add_argument("--base-sha")
    parser.add_argument("--working-tree-dirty", action="store_true")
    parser.add_argument(
        "--protocol",
        choices=("rag-eval-v1", "rag-layered-v2-retrieval"),
        default="rag-eval-v1",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    dataset = load_rag_eval_v1()
    active_query_id: str | None = None
    layered = args.protocol == "rag-layered-v2-retrieval"
    thresholds = {
        name: value
        for name, value in asdict(dataset.thresholds).items()
        if not layered or not name.startswith("unanswered_")
    }
    report: dict[str, Any] = {
        "evaluation_protocol": args.protocol,
        "answer_quality": "NOT_EVALUATED",
        "dataset": dataset.dataset_id,
        "dataset_sha256": compute_content_sha256(),
        "revision": dataset.protocol.model.revision,
        "passed": False,
        "status": "ERROR",
        "run_id": args.run_id,
        "head_sha": args.head_sha,
        "base_sha": args.base_sha,
        "working_tree_dirty": args.working_tree_dirty,
        "paid_model_cost_cny": 0,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "thresholds": thresholds,
        "rows": [],
        "query_count": len(dataset.queries),
        "metrics": None,
    }
    try:
        report["environment"].update(
            {name: version(name) for name in ("torch", "transformers", "safetensors")}
        )
        if report["dataset_sha256"] != dataset.manifest.content_sha256:
            raise ValueError("冻结数据集哈希不符")
        with psycopg.connect(os.environ["SPRING_FIXTURE_DATABASE_URI"]) as connection:
            articles = connection.execute(
                "select article_id,version,body,publication_status,is_current,applicability from knowledge_article order by article_id,version"
            ).fetchall()
            expected = sorted(
                (a.article_id, a.version, a.body, a.status, a.current, list(a.applicability))
                for a in dataset.protocol.corpus_snapshot
            )
            differences = frozen_corpus_differences(articles, expected)
            if differences:
                report["corpus_differences"] = differences
                raise ValueError("数据库语料与冻结正文/权限/版本不符")
            expected_versions = {(row[0], row[1]) for row in expected}
            report["corpus_additions"] = [
                list(row[:2]) for row in articles if (row[0], row[1]) not in expected_versions
            ]
            report["environment"]["postgres"] = connection.execute("select version()").fetchall()[
                0
            ][0]
            report["environment"]["pgvector"] = connection.execute(
                "select extversion from pg_extension where extname='vector'"
            ).fetchall()[0][0]
        encoder = configured_encoder()
        texts = ["物流延迟应先核对当前权威状态。", "部分退款必须核对审批和执行结果。"]
        first = encoder.encode(texts, query=True)
        if first != encoder.encode(texts, query=True) or any(
            len(vector) != 512 for vector in first
        ):
            raise ValueError("编码确定性契约失败")
        if any(abs(sum(value * value for value in vector) - 1) > 1e-5 for vector in first):
            raise ValueError("编码归一化契约失败")
        if first == encoder.encode(texts, query=False):
            raise ValueError("查询指令契约失败")
        instructed = [dataset.protocol.model.query_instruction + text for text in texts]
        if first != encoder.encode(instructed, query=False):
            raise ValueError("查询/文档指令边界不符")
        prefix = "物" * 600
        truncated = encoder.encode([prefix + "甲", prefix + "乙"], query=False)
        if truncated[0] != truncated[1]:
            raise ValueError("512 token 右截断契约失败")
        report["embedding_contract"] = "PASS"
        for query in dataset.queries:
            active_query_id = query.id
            report["rows"].append(
                run_query(
                    os.environ["SPRING_INTERNAL_URL"],
                    query,
                    "knowledge-hybrid-v2" if layered else "knowledge-hybrid-v1",
                )
            )
            active_query_id = None
        measured = retrieval_metrics(report["rows"]) if layered else metrics(report["rows"])
        report["metrics"] = measured
        report["passed"] = all(
            value == 0 if name.endswith("hit_rate") else value >= thresholds[name]
            for name, value in measured.items()
        )
        report["status"] = "PASS" if report["passed"] else "FAIL"
    except Exception as error:
        # 不保存带凭据的连接串或供应商异常正文。
        report["error_type"] = type(error).__name__
        report["failure"] = failure_observation(error, active_query_id)
    finally:
        report["completed_queries"] = len(report["rows"])
        report["failed_queries"] = int(active_query_id is not None)
        report["not_run_queries"] = (
            len(dataset.queries) - report["completed_queries"] - report["failed_queries"]
        )
        report["elapsed_seconds"] = time.perf_counter() - started
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
