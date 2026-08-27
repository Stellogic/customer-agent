# [C] 使用 Flash 完成客户沟通与真实浏览器验收

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/129](https://github.com/Stellogic/customer-agent/issues/129)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:58:12Z
> 最后更新时间：2026-08-26T12:40:08Z
> 关闭时间：2026-08-26T12:40:08Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

使用 deepseek-v4-flash 理解当前工单范围内的合成客户自然语言，生成经过 Spring 权威校验的澄清、调查摘要和受约束自动回复，并通过真实浏览器验证客户、客服和审批人体验，正式完成 C。

## Acceptance criteria

- [ ] 覆盖意图理解、必要澄清、无需补偿、等待人工审批、转人工和提示注入场景。
- [ ] 回复不能宣布未批准补偿、模型金额、最终执行结果、伪造证据或无法保证的响应时间。
- [ ] 客户、负责客服和审批人的授权投影保持隔离，迟到结果和人工偏好阻止自动发送。
- [ ] 浏览器网络与 bundle 不包含 DeepSeek 密钥、Agent 私有地址、模型请求、提示、原始响应或工具 payload。
- [ ] 通过真实 React、Spring、LangGraph、PostgreSQL、浏览器矩阵和完整门禁，正式声明 C 完成。

## Blocked by

- #128
