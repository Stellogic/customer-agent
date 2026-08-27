# [B0] 收缩 Agent 调查结论契约

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/111](https://github.com/Stellogic/customer-agent/issues/111)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:48:32Z
> 最后更新时间：2026-08-24T16:03:57Z
> 关闭时间：2026-08-24T16:03:57Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

收缩现有 Agent 向 Spring 提交的调查结论，移除不具权威意义的模型建议补偿方式和金额。完成后，固定假模型仍驱动原有调查流程，Spring 仍根据权威事实独立计算资格、方式和金额，客户、客服和审批人的可见行为保持不变。

## Acceptance criteria

- [ ] Agent 与 Spring 的调查结论不再包含建议补偿方式或金额。
- [ ] 订单、延迟和证据引用仍来自已验证事实，Spring 继续重新读取事实并独立计算补偿。
- [ ] 现有无需补偿、需要审批、并发提案和人工审批路径保持通过。
- [ ] 通过仓库完整规范化门禁。

## Blocked by

None — can start immediately.
