# [B0] 使用 API key 完成 DeepSeek Flash 真实契约验证

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/125](https://github.com/Stellogic/customer-agent/issues/125)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:57:40Z
> 最后更新时间：2026-08-25T09:28:31Z
> 关闭时间：2026-08-25T09:28:31Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

在调用者显式提供 API key 后，只使用 deepseek-v4-flash 和固定合成评测集验证真实 DeepSeek Responses 行为。该票是从无密钥就绪进入真实供应商验证的明确关口，未达到预先冻结门槛时停止后续启用。

## Acceptance criteria

- [ ] 真实调用只发送评测集中的合成最小事实，密钥只进入 Agent Server 或受控评测进程。
- [ ] 验证 strict schema、响应状态、thinking 配置、允许参数、请求追踪字段和实际响应形状。
- [ ] 报告 schema、业务正确率、拒绝或空输出、P50/P95 延迟、usage、缓存和单位场景成本。
- [ ] Flash 达到 #115 冻结的最低门槛才可进入真实 shadow；否则记录明确阻断结论。
- [ ] 缺少 API key 时本票保持未完成，不得以离线结果替代真实评测证据。

## Blocked by

- #124
