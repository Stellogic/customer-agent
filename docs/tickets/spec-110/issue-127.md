# [B0] 正式启用 Flash 调查结论并安全转人工

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/127](https://github.com/Stellogic/customer-agent/issues/127)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:57:55Z
> 最后更新时间：2026-08-25T12:47:20Z
> 关闭时间：2026-08-25T12:47:19Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

在真实契约与 shadow 均达到准入门槛后，允许 deepseek-v4-flash 调查判断进入 Spring 权威复核。模型成功只提供有限判断，Spring 继续决定补偿资格、方式、金额、审批和执行；任一模型失败都显式转人工且不会回退 fake。

## Acceptance criteria

- [ ] 配置明确区分 fake、shadow 和正式 Flash，缺少配置或密钥时不会伪装成真实模式。
- [ ] 合法模型判断能够进入 Spring 当前处理代次的确定性复核并产生既有业务结果。
- [ ] 超时、限流、拒绝、无效输出、预算耗尽和不可用均产生稳定转人工结果且不回退 fake。
- [ ] 旧处理代次迟到结果、客户人工偏好和并发调用不能产生越权副作用。
- [ ] 完成 B0 全栈正式验收、完整门禁和诚实的里程碑声明。

## Blocked by

- #126
