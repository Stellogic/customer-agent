# [B1] 建立按工单授权的类型化调查能力目录

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/119](https://github.com/Stellogic/customer-agent/issues/119)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:56:09Z
> 最后更新时间：2026-08-24T22:50:44Z
> 关闭时间：2026-08-24T22:50:44Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

把一次性全量 facts 演进为 Spring 授予的类型化调查能力目录，覆盖订单确认、物流、支付退款、既有补偿与待处理动作和适用政策。每次调用按客服工单和当前处理代次授权，只返回最小事实与证据引用；本票不要求 API key。

## Acceptance criteria

- [ ] Agent 只能从声明的类型化能力和参数中选择，不能构造任意 Spring 路径或访问数据库。
- [ ] 每项能力校验机器身份、工单、generation、生命周期、允许操作和客户人工偏好。
- [ ] 能力结果不暴露原始 HTTP、数据库字段、内部令牌或完整业务对象。
- [ ] 未知能力、错误参数、越权工单、旧处理代次和重复副作用请求均被拒绝。
- [ ] 现有 Spring 权威计算与审批执行边界保持不变，并通过仓库完整规范化门禁。

## Blocked by

- #116
