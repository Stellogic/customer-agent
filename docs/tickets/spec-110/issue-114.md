# [B0] 完成 DeepSeek adapter 离线故障与兼容契约验证

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/114](https://github.com/Stellogic/customer-agent/issues/114)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:48:53Z
> 最后更新时间：2026-08-24T18:53:06Z
> 关闭时间：2026-08-24T18:53:06Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

使用本地可控的供应商替身，从调查判断模型公共接口验证 DeepSeek adapter 的结构化输出、静默参数风险、重试与失败边界。该票提供无需 API key 的完整离线证据，但不声称证明真实 DeepSeek 服务兼容。

## Acceptance criteria

- [ ] 离线契约覆盖 required、enum、禁止额外字段、证据数组、输出上限和允许参数。
- [ ] 覆盖 400、401、402、422、429、500、503、连接超时、读取超时、整体超时和结果不明确的断线。
- [ ] 证明每次供应商尝试独立记录，且任何失败都不会静默改用 fake。
- [ ] 日志、持久化记录和 checkpoint 不包含密钥、原始提示、模型正文或供应商 payload。
- [ ] 通过仓库完整规范化门禁，并明确标注本票没有运行真实模型。

## Blocked by

- #113
