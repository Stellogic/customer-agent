# 以客服 Principal 贯通共享内部工作台

> 父规格：[#71 规格 统一客户帮助中心与内部工作台的登录、鉴权及路由](../../specs/issue-71.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/75](https://github.com/Stellogic/customer-agent/issues/75)
> Issue 状态：CLOSED
> 创建时间：2026-08-16T10:25:47Z
> 最后更新时间：2026-08-22T07:28:54Z
> 关闭时间：2026-08-22T07:28:54Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#71

## What to build

把客服工作区完整迁移到 Spring Principal 和共享 `InternalShell`。客服登录后可查看最小共享队列、领取客服工单并在有效分配范围内处理详情；共享后台布局不能扩大客服的数据或审批权限。

## Acceptance criteria

- [ ] 仅客服登录后默认进入 `/internal/support`，只显示客服导航；双角色人员也能从 `InternalShell` 进入客服工作区。
- [ ] 客服共享队列、SLA 队列、领取、详情读取和客服写操作全部从 Spring Principal 获取客服身份。
- [ ] 共享队列继续只返回最小摘要；进入队列不授予工单详情访问权。
- [ ] 客服工单详情继续要求当前有效客服分配；未分配或分配失效的详情返回不可枚举的 404。
- [ ] `SUPPORT_WORKBENCH` 快照与 SSE 保持既有白名单、epoch、schema、序号缺口和权威快照恢复行为。
- [ ] `X-Synthetic-Support-Id` 不再决定任何客服业务操作；伪造该请求头不能改变 Principal、领取者或详情可见性。
- [ ] 仅客服直接访问审批路由看到 403，调用审批 API 也不能获得审批 capability。
- [ ] 客服写操作必须携带当前 Session 的合法 CSRF token。
- [ ] 客服 API 安全矩阵、React 行为和真实 PostgreSQL 分配围栏用例先失败后通过，并回归现有队列、分配和 SSE 自愈测试。

## Blocked by

- #73
