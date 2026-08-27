# 修复审批证据总额与净额度二次扣减

> 父规格：[#11 规格 客服工单调查与补偿审批 Agent MVP 首个纵向切片](../../specs/issue-11.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/55](https://github.com/Stellogic/customer-agent/issues/55)
> Issue 状态：CLOSED
> 创建时间：2026-08-12T15:45:00Z
> 最后更新时间：2026-08-12T17:30:11Z
> 关闭时间：2026-08-12T17:30:11Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## 背景

当前审批证据快照中的 `availableCompensationAmount` 保存的是扣除 active reservation 后的净额度，但审批阶段又将快照额度与权威总额度比较，并另外校验 active reservation，造成二次扣减与事实语义漂移。

Part of #11

## 目标

审批证据快照保存权威总可补偿额度；资格判断继续使用扣除 active reservation 后的剩余额度。用明确的 total / active / remaining 命名区分三种事实，并保持审批阶段对预占与权威总额的独立校验。

## 验收标准

- [ ] 提案生成时，证据快照保存权威 `totalAvailableCompensationAmount`、`activeReservationAmount` 与由两者导出的 `remainingAvailableCompensationAmount`，不再用含混的 available 命名表达不同语义。
- [ ] 补偿资格仍以 `remaining = total - active` 判断；审批时独立验证权威总额与 active reservation，避免再次从净额度扣减。
- [ ] 总额 268.00、已有 active reservation 10.00、提案金额不超过剩余额度时仍可批准并建立唯一执行/预占。
- [ ] 权威事实漂移会使审批失败，且并发审批/预占继续满足容量、唯一决定、幂等与相邻状态不变量。
- [ ] 审批视图和客户/客服投影不扩大敏感证据暴露范围；无 API 契约迁移需要时不得引入无关字段。
- [ ] 从仓库根运行 `pwsh ./scripts/check.ps1` 通过，并完成独立 Standards / Spec 双轴审阅。
