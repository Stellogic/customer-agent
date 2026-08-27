# [C] 建立独立客户沟通模型与安全回复 envelope

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/122](https://github.com/Stellogic/customer-agent/issues/122)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:57:16Z
> 最后更新时间：2026-08-25T05:08:31Z
> 关闭时间：2026-08-25T05:08:31Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

建立独立于调查判断的客户沟通模型接口，并先用确定性 fake 贯通客户可见文字、回复意图、证据引用和转人工标志。Spring 在发送前重新验证当前处理代次、处理模式、生命周期、人工偏好、证据范围和禁止承诺。

## Acceptance criteria

- [ ] 调查判断与客户沟通具有独立输入、输出 schema、评测和失败边界。
- [ ] 回复仍写入现有公开沟通，不建立平行消息系统，并遵循重开、关闭和 SSE 规则。
- [ ] Spring 拒绝模型金额、未批准补偿或退款承诺、伪造证据、越权订单和不允许公开的字段。
- [ ] 失效 generation、错误处理模式、人工偏好或迟到结果不会发送消息。
- [ ] 普通 CI 使用确定性 fake 完成端到端验证并通过完整门禁。

## Blocked by

- #121
