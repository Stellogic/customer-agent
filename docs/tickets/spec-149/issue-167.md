# [RAG] 交付本地 BGE、pgvector 与预冻结质量门

> 父规格：[#149 规格 重塑自然语言多工单客服 Agent 与知识工作台](../../specs/issue-149.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/167](https://github.com/Stellogic/customer-agent/issues/167)
> Issue 状态：OPEN
> 创建时间：2026-08-27T17:25:20Z
> 最后更新时间：2026-08-27T17:33:34Z
> 关闭时间：—
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

Part of #149

## What to build

在本地 CPU 上使用固定 revision 的 `BAAI/bge-small-zh-v1.5` 生成知识向量，以 PostgreSQL 全文检索、pgvector 与 RRF 形成可工作的混合检索纵切片，并在任何客户或客服 Agent 消费前通过预先冻结的最低中文检索质量门。

## Acceptance criteria

- [ ] 在编写或调优 Embedding、pgvector 查询和 RRF 实现之前，先冻结 `rag-eval-v1` 评测清单、期望结果和内容哈希；本票后续不得根据检索结果修改该集合，纠错必须单独审查并保留原哈希。
- [ ] `rag-eval-v1` 固定为至少 60 条查询：36 条有答案查询、12 条无答案查询、12 条错误版本或不适用范围查询；36 条有答案查询覆盖每个当前发布知识条目至少 3 条，并至少包含 12 条口语/省略表达和 8 条错别字、简称或同义表达。
- [ ] 通过阈值预先固定为：有答案查询 `Recall@5 >= 0.90`、`MRR@5 >= 0.75`；无答案 precision `>= 0.90` 且 recall `>= 0.85`；最终合格 Top-5 中错误版本、不适用范围和越权条目命中率均为 `0%`。
- [ ] 评测使用固定模型完整 revision、查询指令、pooling、L2 normalization、最大长度、截断策略和 512 维输出；模型文件清单与校验值可审计。
- [ ] 模型权重不提交 Git，准备阶段下载后运行阶段只从本地路径离线加载；文件缺失或校验失败时 fail closed。
- [ ] 先以 CPU PyTorch/Safetensors 建立正确性基线，不要求 ONNX 才能完成本票。
- [ ] PostgreSQL 全文候选和 pgvector 语义候选分别可观测，RRF 在权限、发布状态、版本和适用范围硬过滤后融合。
- [ ] 当前语料规模优先使用精确向量搜索；没有规模证据时不提前固定 HNSW 或 IVFFlat。
- [ ] 真实内部检索页面展示带条目标识、版本和片段位置的结果，并覆盖桌面、窄屏、loading、empty、error 与索引过期状态。
- [ ] 模型、索引或数据库扩展不可用时停止知识结果，不以无来源内容填补。

## Blocked by

- #150
- #166
