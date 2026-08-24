# 以审批人 Principal 贯通共享内部工作台

> 父规格：[#71 规格 统一客户帮助中心与内部工作台的登录、鉴权及路由](../../specs/issue-71.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/76](https://github.com/Stellogic/customer-agent/issues/76)
> Issue 状态：CLOSED
> 创建时间：2026-08-16T10:25:49Z
> 最后更新时间：2026-08-22T08:39:13Z
> 关闭时间：2026-08-22T08:39:13Z
> 同步日期：2026-08-24
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#71

## What to build

把审批工作区完整迁移到 Spring Principal 和共享 `InternalShell`。审批人登录后可查看可领取提案、获得限时审批视图并批准或驳回；页面 capability 不能替代审批租约、提案版本或事务内业务围栏。

## Acceptance criteria

- [ ] 仅审批人登录后默认进入 `/internal/approvals`，只显示审批导航；双角色人员也能从 `InternalShell` 进入审批工作区。
- [ ] 审批队列、领取、审批视图、释放、批准和驳回全部从 Spring Principal 获取审批人身份。
- [ ] 审批视图继续绑定当前补偿提案版本与有效租约，且只暴露提案范围的审批证据。
- [ ] 领取、释放、批准和驳回继续校验审批人、租约令牌、租约版本和提案版本；可见资源的租约过期或版本冲突返回 409。
- [ ] 无权知道其存在的提案返回 404；缺少审批粗粒度能力返回 403。
- [ ] `APPROVAL_VIEW` 快照与 SSE 保持既有白名单、epoch、schema、序号缺口、租约撤销和权威快照恢复行为。
- [ ] `X-Synthetic-Approver-Id` 不再决定任何审批业务操作；伪造该请求头不能改变 Principal、租约持有人或决定人。
- [ ] 审批写操作必须携带当前 Session 的合法 CSRF token。
- [ ] 审批 API 安全矩阵、React 行为和真实 PostgreSQL 租约事务用例先失败后通过，并回归批准、驳回、执行和对账不变量。

## Blocked by

- #73
