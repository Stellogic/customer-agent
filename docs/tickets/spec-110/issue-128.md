# [B1] 使用 Flash 完成自主调查真实验收

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/128](https://github.com/Stellogic/customer-agent/issues/128)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:58:04Z
> 最后更新时间：2026-08-25T15:32:07Z
> 关闭时间：2026-08-25T15:32:07Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

使用 deepseek-v4-flash 在合成工单中自主选择受控调查行动、识别事实缺口、请求澄清、形成证据链、提交结论或转人工，并验证资源预算与恢复语义，正式完成 B1。

## Acceptance criteria

- [ ] Flash 能在允许目录内自主选择订单、物流、支付退款、补偿历史和政策调查顺序。
- [ ] 覆盖缺少事实、事实冲突、工具暂时失败、重复无进展、预算耗尽和客户人工偏好。
- [ ] 测试允许不同合法行动顺序，只断言最终结果、证据完整性、业务不变量和预算。
- [ ] 客服接管只能看到授权范围内的受控行动、事实和证据，任何角色都看不到思维链或供应商 payload。
- [ ] 通过真实 LangGraph、PostgreSQL、相关浏览器场景和完整门禁，正式声明 B1 完成。

## Blocked by

- #127
