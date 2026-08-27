# [RAG] 完成中文检索消融与可选 ONNX 验证

> 父规格：[#149 规格 重塑自然语言多工单客服 Agent 与知识工作台](../../specs/issue-149.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/168](https://github.com/Stellogic/customer-agent/issues/168)
> Issue 状态：OPEN
> 创建时间：2026-08-27T17:25:23Z
> 最后更新时间：2026-08-27T17:33:36Z
> 关闭时间：—
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

Part of #149

## What to build

在已经通过最低中文质量门的 PyTorch 混合检索上完成更完整的中文消融评测，并把 ONNX Runtime 作为可选优化进行向量、排序和资源一致性验证。ONNX 不达标时保留 PyTorch 默认，不阻塞已可用 RAG。

## Acceptance criteria

- [ ] 在冻结评测集上分别报告词法、稠密向量和 RRF 的 Recall@K、MRR 或 nDCG、无答案表现及错误版本命中。
- [ ] 只有混合方案相对单路检索有可复现收益时才冻结候选数、RRF 常数和排序参数。
- [ ] 若 PostgreSQL 内建词法召回不足，按证据比较 `pg_trgm`、写入前中文分词或 PGroonga，不直接引入未经评估扩展。
- [ ] ONNX 导出固定 feature-extraction 模型、pooling 与 normalization，并与 PyTorch 比较向量差异和 Top-K 排序一致性。
- [ ] ONNX 基准记录冷启动、吞吐、P50/P95、峰值 RSS 和相同硬件条件，不从权重体积推断运行资源。
- [ ] ONNX 只有在排序一致性满足冻结容差且资源收益明确时成为默认；否则文档化保留 PyTorch。
- [ ] 评测结果、环境、模型 revision、数据集哈希和通过/未通过结论保存为仓库证据。
- [ ] 本票不改变 RAG 的业务权威、客户引用或客服权限，也不顺手实现 T20/T21 功能。

## Blocked by

- #150
- #167
