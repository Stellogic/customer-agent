---
status: accepted
---

# 分离登录入口并保持单主体 Session

同一个 React 应用分别使用 `/help/login` 和 `/internal/login` 作为客户与内部工作人员入口，二者复用同源 Session 和当前身份接口，但不提供产品级角色切换器。一个 Session 同一时刻只代表一个客户或一名内部工作人员；内部工作人员可以同时具有客服和审批人角色，客户与内部工作人员之间切换身份时必须替换原 Session，并清理前端缓存与 SSE 连接。

本地演示环境使用真实密码校验的固定客户、仅客服、仅审批人和双角色账号；内部登录未来可以在保持当前身份契约的前提下替换为组织 OIDC。Session cookie 由 Spring 管理并保持 HttpOnly，首版采用三十分钟无活动过期且不提供“记住我”；写请求保留 CSRF 防护，SPA 在登录、退出或 Session 更新后重新取得 token。

当前身份只向前端投影稳定的 `CUSTOMER_HELP_ACCESS`、`SUPPORT_WORKBENCH_ACCESS` 和 `APPROVAL_WORKBENCH_ACCESS` 页面级 capability；动态的客服工单分配、审批租约、补偿提案版本及禁止自审规则仍在每次 API 请求中判断。产品运行路径不再接受旧 `X-Synthetic-*` 人工身份头，测试改用受控的 Spring Security 测试身份，机器身份继续使用独立认证链；候选与安全边界见 [统一内部后台管理系统与鉴权方案调研](../research/internal-admin-platform-evaluation.md)。

前端通过 `GET /api/auth/session` 恢复身份；已登录响应只包含 `id`、`displayName`、`subjectType`、`roles` 和 `capabilities`，未登录返回 401，不包含默认路由或动态资源权限。人工身份 SSE 单次连接最长六十秒并在重连时重新验证 Session、角色和资源授权；退出通过跨标签页通知关闭本地 SSE、清除身份与业务缓存，六十秒是异常失联时授权陈旧的最大窗口。

迁移可以按测试驱动的小步实现，但最终可运行版本必须一次性让所有浏览器人工接口改从 Spring Principal 获取身份，不能留下合成身份头兼容模式。`local-demo` 登录页可以显示四种固定演示账号并填充表单，但仍执行真实密码提交与校验，生产构建不渲染该辅助区域。

首版面向单实例本地演示，使用 Spring 内置 Session 存储并接受服务重启后重新登录，不提前引入 Redis 或数据库 Session。登录成功、失败、退出与 Session 过期进入不含密码、cookie 或 CSRF token 的结构化安全日志，不写入面向工单、审批和补偿事实的业务审计事件。
