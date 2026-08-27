# [B0] 运行真实 DeepSeek 业务 shadow 并形成准入证据

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/118](https://github.com/Stellogic/customer-agent/issues/118)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:49:22Z
> 最后更新时间：2026-08-24T15:00:44Z
> 关闭时间：2026-08-24T15:00:41Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

使用已经选定的 DeepSeek 模型在合成工单业务路径中运行真实 shadow，对比 fake、权威事实和 Spring 最终计算，同时保持零业务副作用，形成是否允许权威提交的准入证据。

## Acceptance criteria

- [ ] 真实 shadow 覆盖正常、边界、无资格、拒绝、超时和非法输出等合成工单场景。
- [ ] 每次 shadow 都证明没有提交结论、创建提案、解决工单、发送消息或改变处理代次。
- [ ] 比较报告包含质量、分歧、失败率、延迟、usage 和成本，并不保存原始工单或模型正文。
- [ ] 只有达到冻结门槛时才给出允许进入正式模式的结论；否则记录阻断原因。
- [ ] 通过真实 PostgreSQL 和真实 LangGraph 的业务路径验证及仓库完整门禁。

## Blocked by

- #117
