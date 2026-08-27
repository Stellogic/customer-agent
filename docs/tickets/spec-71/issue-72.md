# 建立同源 Session 登录与当前身份基线

> 父规格：[#71 规格 统一客户帮助中心与内部工作台的登录、鉴权及路由](../../specs/issue-71.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/72](https://github.com/Stellogic/customer-agent/issues/72)
> Issue 状态：CLOSED
> 创建时间：2026-08-16T10:25:39Z
> 最后更新时间：2026-08-16T16:37:28Z
> 关闭时间：2026-08-16T16:37:28Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#71

## What to build

建立浏览器人工身份的同源 Session 基线，使客户和内部工作人员都能通过真实密码校验登录、退出并恢复当前身份。首个切片提供两种登录入口、四种仅本地演示账号、CSRF 防护和最小当前身份投影，但不在本票中迁移现有客户、客服或审批业务接口。

## Acceptance criteria

- [ ] Spring Security 成为浏览器人工身份的认证入口；一个 Session 同一时刻只表示一个客户或一名内部工作人员。
- [ ] `/help/login` 与 `/internal/login` 都能提交真实用户名和密码，并在成功认证时更换 Session 标识。
- [ ] `local-demo` 提供固定客户、仅客服、仅审批人和双角色内部工作人员四种账号；生产配置不包含或展示演示账号辅助信息。
- [ ] `GET /api/auth/session` 在已登录时只返回 `id`、`displayName`、`subjectType`、`roles` 和 `capabilities`，未登录时返回 401。
- [ ] 当前身份投影不包含 React 路由、默认落点、客服工单分配、审批租约或其他动态资源权限。
- [ ] Session cookie 保持 HttpOnly；首版三十分钟无活动过期，不提供“记住我”，单实例服务重启后需要重新登录。
- [ ] 写请求启用 CSRF；无 token、错误 token 和旧 Session token 被拒绝，合法 token 可完成请求，登录和退出后 token 更新。
- [ ] 退出使服务端 Session 失效，之后的当前身份读取返回 401。
- [ ] Agent 与补偿执行器等机器身份认证链保持独立，不能转换为浏览器人工 Session。
- [ ] 后端安全集成测试与最小前端登录行为测试先失败后通过，且不通过手工字符串身份绕过 Spring Security。

## Blocked by

None — can start immediately.
