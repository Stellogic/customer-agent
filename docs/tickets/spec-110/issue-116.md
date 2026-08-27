# [B0] 接入默认关闭的业务路径 shadow 能力

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/116](https://github.com/Stellogic/customer-agent/issues/116)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:49:06Z
> 最后更新时间：2026-08-24T20:48:15Z
> 关闭时间：2026-08-24T20:48:15Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

在真实工单调查路径中接入可配置但默认关闭的 shadow 能力。关闭时不发生外部调用；使用离线供应商替身开启时，候选结论只能形成最小比较记录，不能提交 Spring、改变工单、创建提案或发送消息。

## Acceptance criteria

- [ ] 默认配置完全不调用 DeepSeek，普通 CI 和既有 fake 业务路径保持确定性。
- [ ] shadow 结果不提交调查结论、不创建提案、不解决工单、不发送消息且不改变处理代次。
- [ ] 最小比较记录可关联当前工单处理代次、模型和提示版本，但不保存原始输入输出。
- [ ] 旧处理代次、重复回调和 shadow 失败均不能产生业务副作用。
- [ ] 使用离线替身完成全栈验证并通过完整门禁，同时明确尚无真实 shadow 证据。

## Blocked by

- #115
