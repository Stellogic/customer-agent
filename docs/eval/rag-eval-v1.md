# rag-eval-v1 中文检索质量基线

本文件与 `agent/src/baseline_agent/rag_eval_v1/` 中的 JSON 共同冻结 Issue #189 的评测资产。本目录只保存质量基线，不实现 Embedding、pgvector 查询、RRF 或在线检索页面；那些工作属于 #190 / #167。

## 资产位置

| 文件 | 作用 |
| --- | --- |
| [`agent/src/baseline_agent/rag_eval_v1/queries.json`](../../agent/src/baseline_agent/rag_eval_v1/queries.json) | 60 条查询、期望命中、禁止命中、身份与适用范围 |
| [`agent/src/baseline_agent/rag_eval_v1/protocol.json`](../../agent/src/baseline_agent/rag_eval_v1/protocol.json) | 固定模型 revision、编码约定、文件校验与门槛 |
| [`agent/src/baseline_agent/rag_eval_v1/manifest.json`](../../agent/src/baseline_agent/rag_eval_v1/manifest.json) | 内容哈希、审查来源、可重复执行说明与纠错账本 |

内容哈希覆盖 `protocol.json` 与 `queries.json` 的原始字节，算法见 `compute_content_sha256()`：先对各文件做 SHA-256，再对按文件名排序的 `name  hex` 行做 SHA-256。`manifest.json` 本身不进入哈希，以免循环。

当前冻结值：

- `content_sha256` = `d2d5efdae565395c1dc722e14f66077558575152e23c5c8fbea58b7ebcfd2fe5`
- `original_content_sha256` 与上值相同，表示尚未发生纠错。

## 查询覆盖

- 36 条有答案查询，覆盖 3 个当前发布知识条目（`approval-review` v1、`logistics-delay` v2、`refund-policy` v1）各 12 条。
- 有答案查询含口语/省略与错别字/简称/同义表达；每条记录允许命中的条目、版本、适用范围和必要片段。
- 12 条无答案查询：当前语料中没有可引用的发布知识。
- 12 条负面查询：6 条错误版本（退役的 `logistics-delay` v1 不得进入合格 Top-5）、6 条不适用范围（客户公开语境或客户身份不得把内部知识当答案）。
- 另有 4 条独立越权查询：内部身份缺少 `KNOWLEDGE_READ_ACCESS`，或客户身份走内部检索；任何知识条目进入合格 Top-5 都计为越权命中。

语料快照哈希和正文写在 `protocol.json` 的 `corpus_snapshot`，对应 `backend/src/main/resources/knowledge/` 在冻结时的文件内容。必要片段必须是该快照正文的子串。知识正文变更后必须另开审查，不能悄悄改评测题。

## 预先冻结门槛

这些门槛在看到任何混合检索结果之前写入版本化资产。未达标时不得改题或降低阈值。

| 指标 | 门槛 |
| --- | ---: |
| 有答案 Recall@5 | `>= 0.90` |
| 有答案 MRR@5 | `>= 0.75` |
| 无答案 precision | `>= 0.90` |
| 无答案 recall | `>= 0.85` |
| 错误版本 Top-5 命中率 | `0%` |
| 不适用范围 Top-5 命中率 | `0%` |
| 越权条目 Top-5 命中率 | `0%` |

合格 Top-5 指完成权限、发布状态、版本和适用范围硬过滤之后的结果。退役版本、客户公开语境与无知识读权限身份看到的内部条目都计为违规命中。

## 评测协议

固定使用 `BAAI/bge-small-zh-v1.5`，完整 revision `7999e1d3359715c523056ef9478215996d62a620`。

- 查询指令：`为这个句子生成表示以用于检索相关文章：`（仅查询侧拼接，文档侧不加指令）
- pooling：CLS
- 归一化：L2
- 最大长度：512
- 截断：开启，`longest_first`，右侧截断
- 输出：512 维
- 权重不进 Git；运行阶段只从本地路径离线加载；缺失或校验失败 fail closed
- 运行时核心权重：`model.safetensors` SHA-256 `354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026`

本票不下载权重、不导出 ONNX、不执行检索。#190 必须按上述协议建立正确性基线。

## 独立审查方式（不联网）

1. 阅读本文件与三份 JSON。
2. 对照 `backend/src/main/resources/knowledge/` 确认必要片段来自真实条目。
3. 在 Agent 测试中运行 `tests/test_rag_eval_v1.py`，核验条数、覆盖、门槛和内容哈希。
4. 不要调用 DeepSeek，不要读取生产数据，不要根据尚未实现的检索输出改题。

## 纠错规则

后续若发现题目或期望结果有误：

1. 不得原地改哈希假装仍是同一基线。
2. 保留 `original_content_sha256`。
3. 更新 `content_sha256`，并在 `corrections` 中写明日期、变更范围与理由。
4. 单独审查；不得因为 #190 实测未达标而改题或降低门槛。
