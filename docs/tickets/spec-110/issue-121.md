# [B1] 完成离线澄清、恢复与人工接管路径

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/121](https://github.com/Stellogic/customer-agent/issues/121)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:56:24Z
> 最后更新时间：2026-08-25T03:52:44Z
> 关闭时间：2026-08-25T03:52:44Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

完成自主调查中的事实缺口识别、针对性客户澄清、LangGraph 中断恢复、结论提交和人工接管。使用 fake 和工具替身证明 B1 工程能力就绪，但不把离线结果描述为真实模型 B1 已完成。

## Acceptance criteria

- [ ] 缺少或冲突事实时只询问继续调查所必需的合成信息，并保持业务幂等。
- [ ] 客户回复澄清后从当前处理代次继续；旧代次迟到行动不能发送消息或修改工单。
- [ ] 客户要求人工后 Agent 停止自动调查，负责客服只在当前分配范围内看到行动、事实和证据。
- [ ] checkpoint 只保存恢复所需状态，不进入客户、客服或审批人的产品投影。
- [ ] 使用真实 LangGraph 与 PostgreSQL 完成离线全栈验证，并明确尚未取得真实 DeepSeek B1 证据。

## Blocked by

- #120
