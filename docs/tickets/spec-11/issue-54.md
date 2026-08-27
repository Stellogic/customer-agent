# 修复补偿成功重放 attempt 绑定与 RESOLVED 前 SLA 原子固化

> 父规格：[#11 规格 客服工单调查与补偿审批 Agent MVP 首个纵向切片](../../specs/issue-11.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/54](https://github.com/Stellogic/customer-agent/issues/54)
> Issue 状态：CLOSED
> 创建时间：2026-08-12T15:44:56Z
> 最后更新时间：2026-08-12T16:49:15Z
> 关闭时间：2026-08-12T16:49:15Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

Part of #11

## 问题

补偿执行成功交付存在两个同一事务边界内的正确性缺口：

1. execution 已为 `SUCCEEDED` 时，新的 success command 当前可能仅按 execution 的持久化结果回放，未强制核对命令的 `attemptId` 与成功结果绑定的 attempt，因而错误 attempt 可能被接受。
2. 补偿成功事务直接停止解决时钟并把工单转为 `RESOLVED`，但没有先用同一业务时间评估 SLA。若成功时刻恰已跨越解决 SLA 阈值，事务会先停止时钟，导致应固化的 SLA 到期事实、审计、通知和共享队列遗漏。

## 验收标准

- execution 已 `SUCCEEDED`：
  - 新 success command 的 `attemptId` 与持久化成功结果 attempt 不一致时返回 409，且不产生业务副作用。
  - 正确 attempt、相同参数的成功命令可安全重放并返回既有成功结果。
  - 同一 `requestId` 复用但关键参数不同仍返回 409。
- 首次补偿成功事务：
  - 在停止解决时钟及把工单转为 `RESOLVED` 前，以同一 `now` 同步调用工单 SLA 评估。
  - 已到期的 SLA fact、audit、notification、`SLA_BREACH` shared queue 与补偿成功、工单解决原子提交。
  - 重复成功命令回放不重复生成 SLA fact/audit/notification/queue。
- 使用真实 PostgreSQL 集成测试覆盖关键持久化、事务和并发/重放语义；保留现有执行器授权与投影隐私边界。
- 从仓库根运行 `pwsh ./scripts/check.ps1` 通过。

## 非目标

- 不改变补偿审批、UNKNOWN 对账或执行器调度策略。
- 不创建新的业务通知类型或后继任务。
