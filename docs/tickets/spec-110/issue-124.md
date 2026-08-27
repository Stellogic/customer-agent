# [C] 完成无密钥全栈就绪验收

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/124](https://github.com/Stellogic/customer-agent/issues/124)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:57:32Z
> 最后更新时间：2026-08-25T08:04:36Z
> 关闭时间：2026-08-25T08:04:36Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

使用 fake、确定性行动模型和供应商替身，通过真实 React、Spring、LangGraph 和 PostgreSQL 验证调查、澄清、自动回复、转人工及跨角色安全边界，形成可以安全提供 API key 的就绪证据。

## Acceptance criteria

- [ ] 客户可在真实浏览器中完成合成工单创建、自主调查、澄清、自动回复、转人工和 SSE 恢复。
- [ ] 负责客服只在当前分配内看到行动、受控事实和证据，审批人权限与租约边界保持不变。
- [ ] 浏览器网络与 bundle 不包含模型密钥、Agent 私有地址、提示、原始响应、工具 payload 或 checkpoint。
- [ ] 报告明确区分代码与离线安全就绪、真实供应商未验证、B0/B1/C 尚未正式完成。
- [ ] 通过仓库完整规范化门禁和离线真实浏览器矩阵。

## Blocked by

- #123
