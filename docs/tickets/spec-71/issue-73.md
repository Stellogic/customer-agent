# 建立一个 React 应用、两个界面壳的静态路由骨架

> 父规格：[#71 规格 统一客户帮助中心与内部工作台的登录、鉴权及路由](../../specs/issue-71.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/73](https://github.com/Stellogic/customer-agent/issues/73)
> Issue 状态：CLOSED
> 创建时间：2026-08-16T10:25:42Z
> 最后更新时间：2026-08-22T03:26:42Z
> 关闭时间：2026-08-22T03:26:42Z
> 同步日期：2026-08-24
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#71

## What to build

在现有 Vite 应用中建立一个 React 应用、两个界面壳的静态路由骨架。系统根据当前身份的 `subjectType` 和页面级 capability 生成菜单、守卫和默认落点，Spring 不返回 React 路径；本票只建立壳和路由接缝，不迁移各业务 API 的人工身份来源。

## Acceptance criteria

- [ ] 在真实安装、类型检查、测试和生产构建通过后锁定兼容的 React Router 7、Ant Design 6 与 Pro Components 版本。
- [ ] `/help/**` 使用 `CustomerShell`；`/internal/support/**` 与 `/internal/approvals/**` 使用共享 `InternalShell`，客户与内部工作人员不共享导航。
- [ ] 客户默认进入 `/help`，仅客服进入 `/internal/support`，仅审批人进入 `/internal/approvals`，双角色内部工作人员进入 `/internal`。
- [ ] `/internal` 只展示当前身份有权进入的工作区入口，不预读客服或审批业务数据。
- [ ] 页面级 capability 只使用 `CUSTOMER_HELP_ACCESS`、`SUPPORT_WORKBENCH_ACCESS` 和 `APPROVAL_WORKBENCH_ACCESS`；角色和 capability 不被当作动态资源授权。
- [ ] 已登录但缺少页面 capability 时显示 403，不静默切换角色或循环重定向。
- [ ] 未登录访问受保护页面时进入对应登录入口；`returnTo` 只接受可映射到已知静态路由的同源站内路径。
- [ ] `CustomerShell`、客服工作区和审批工作区按 route-level lazy loading 分包；生产构建记录初始 chunk 证据，不把代码分包表述为安全边界。
- [ ] 未整体迁移到 Ant Design Pro/Umi Max，也未引入 react-admin 或 refine 作为主框架。
- [ ] React 行为测试从当前身份接口的外部响应验证四种落点、菜单和 403，不绑定组件内部状态。

## Blocked by

- #72
