# [RAG] 冻结 rag-eval-v1 中文检索质量基线

> 父规格：[#149 规格 重塑自然语言多工单客服 Agent 与知识工作台](../../specs/issue-149.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/189](https://github.com/Stellogic/customer-agent/issues/189)
> Issue 状态：OPEN
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。

## Parent

Part of #149

Child of #167

## What to build

在任何 Embedding、pgvector 查询或 RRF 参数实现与调优之前，冻结可复核的 rag-eval-v1 中文检索评测资产。评测集必须能够独立证明查询覆盖、期望结果、权限与版本边界，并通过内容哈希防止根据后续结果改题。

## Non-goals

- 不实现或调优 Embedding、向量查询、RRF 或检索页面。
- 不运行 ONNX 导出或性能优化。
- 不因预计实现困难降低既定质量阈值。

## Acceptance criteria

- [x] rag-eval-v1 至少包含 60 条查询：36 条有答案、12 条无答案、12 条错误版本或不适用范围；有答案查询覆盖每个当前发布知识条目至少 3 条。
- [x] 有答案查询至少包含 12 条口语或省略表达，以及 8 条错别字、简称或同义表达；每条样本记录允许命中的条目、版本、适用范围与必要片段。
- [x] 预先冻结有答案 Recall@5 >= 0.90、MRR@5 >= 0.75，无答案 precision >= 0.90、recall >= 0.85，以及错误版本、不适用范围和越权条目 Top-5 命中率 0%。
- [x] 固定评测协议所需的模型完整 revision、查询指令、pooling、L2 normalization、最大长度、截断策略和 512 维输出约束。
- [x] 保存评测内容哈希、生成或审查来源及可重复执行说明；后续纠错必须单独审查并同时保留原哈希与变更理由。
- [x] 评测资产和说明进入仓库，能够在不联网、不读取生产数据且不调用 DeepSeek 的条件下接受独立审查。

## Blocked by

- #166

## Boundary

本票只建立不可被后续实现结果污染的质量基线。固定 revision 的模型文件准备、离线加载、混合检索实现、页面接入和实际质量门由 #167 的后续子票承接。
