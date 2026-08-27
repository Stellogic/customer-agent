# [评测] 使用完整合成评测集比较 DeepSeek Flash 与 Pro

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/130](https://github.com/Stellogic/customer-agent/issues/130)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:58:20Z
> 最后更新时间：2026-08-26T14:02:35Z
> 关闭时间：2026-08-26T14:02:35Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

在 C 已使用 deepseek-v4-flash 正式完成后，使用完全相同的合成场景、提示、schema 和计量口径比较 Flash 与 Pro，形成继续使用 Flash 或建议切换 Pro 的证据化结论。本票只评测，不直接修改正式模型。

## Acceptance criteria

- [ ] Flash 与 Pro 使用相同评测集、提示版本、schema 版本、thinking 配置和指标定义。
- [ ] 比较业务正确率、结构化输出成功率、拒答、提示注入、P50/P95 延迟、token、缓存和成本。
- [ ] 报告记录请求模型、实际响应模型、后端指纹和供应商行为差异，不保存原始业务正文或模型思维链。
- [ ] 形成继续使用 Flash、建议 Pro 或证据不足的明确结论。
- [ ] 如建议切换 Pro，另立独立切换与回归票；本票不得直接改变正式运行配置。

## Blocked by

- #129
