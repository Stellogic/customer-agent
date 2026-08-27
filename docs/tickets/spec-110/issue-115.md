# [B0] 建立合成评测框架并冻结 Flash 最低准入门槛

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/115](https://github.com/Stellogic/customer-agent/issues/115)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:49:00Z
> 最后更新时间：2026-08-24T19:50:21Z
> 关闭时间：2026-08-24T19:50:21Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

把现有单场景 release smoke 演进为可重复的合成评测框架，在真实调用前冻结 deepseek-v4-flash 进入真实 shadow 所需的 schema 成功率、业务正确率、拒绝或空输出率、延迟、成本和安全不变量门槛。评测必须显式启用，普通 CI 永不访问 DeepSeek；框架保留 Flash 与 Pro 使用同一口径的能力，但本票不运行真实模型比较。

## Acceptance criteria

- [ ] 评测集覆盖 24、48、72 小时边界、取消、退款、重复补偿、待处理动作、错误证据和提示注入。
- [ ] 评测框架覆盖拒绝、超时、非法输出和不完整响应，并能生成不含原始业务正文的指标报告。
- [ ] 冻结 Flash 进入真实 shadow 的最低质量、安全、失败率、延迟和成本门槛，不能在看到真实结果后追改目标。
- [ ] 框架允许 Flash 与 Pro 使用同一场景、预期和计量口径，但真实横向比较推迟到 C 完成后。
- [ ] 无 API key 时框架可完整离线验证并通过仓库完整规范化门禁，但不得报告真实模型结果。

## Blocked by

- #114
