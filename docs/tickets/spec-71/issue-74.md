# 以客户 Principal 贯通客户帮助中心

> 父规格：[#71 规格 统一客户帮助中心与内部工作台的登录、鉴权及路由](../../specs/issue-71.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/74](https://github.com/Stellogic/customer-agent/issues/74)
> Issue 状态：CLOSED
> 创建时间：2026-08-16T10:25:44Z
> 最后更新时间：2026-08-22T05:34:05Z
> 关闭时间：2026-08-22T05:34:05Z
> 同步日期：2026-08-24
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#71

## What to build

把客户帮助中心完整迁移到 Spring Principal。客户从专属入口登录后，通过 `CustomerShell` 创建、查看和继续处理自己的客服工单，并消费授权的 `CUSTOMER_PUBLIC` 快照与 SSE；浏览器不再通过客户合成身份头声明身份。

## Acceptance criteria

- [ ] 客户登录后进入 `/help`，刷新页面可从 Session 恢复身份和客户帮助中心。
- [ ] 客户创建工单、读取公开快照、回复澄清、请求转人工、重开相关操作都从 Spring Principal 获取客户身份。
- [ ] 客户只能读取和修改属于自己的客服工单；其他客户的资源返回不可枚举的 404。
- [ ] `CUSTOMER_PUBLIC` 快照与 SSE 继续只包含公开白名单字段，不暴露内部记录、调查事实、提案、审批、generation 或原始 Agent 数据。
- [ ] 客户 SSE 建连和重连都验证 Session 与工单归属，既有 epoch、schema、序号缺口和权威快照恢复行为保持不变。
- [ ] `X-Synthetic-Customer-Id` 不再决定任何客户业务操作；伪造该请求头不能改变当前 Principal 或资源范围。
- [ ] 客户直接访问内部路由看到 403，不能通过前端菜单或 URL 获得内部数据。
- [ ] 客户写操作必须携带当前 Session 的合法 CSRF token。
- [ ] 客户 API 安全矩阵、React 行为和真实浏览器到 PostgreSQL 的纵向用例先失败后通过，并回归现有客户公开投影与 SSE 自愈测试。

## Blocked by

- #73
