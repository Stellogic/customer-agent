# Issue #79 旧人工身份与路由兼容面收缩验证

## 范围

- 浏览器人工身份只由 Spring Security Session 的当前 Principal 表达。
- 删除旧合成人工身份控制器、固定身份 cookie 和旧身份目录；本地演示账号仍通过真实密码登录。
- 正式页面由仓库内静态 React 路由注册表驱动；`/support` 与 `/approver` 只保留标记为 `deprecated` 的重定向。
- Agent 与补偿执行器继续使用既有独立机器身份链，本票未修改其产品实现。

## 负向矩阵

`HumanApiNegativeMatrixTest` 枚举 23 个浏览器人工业务 API（客户 9、客服 7、审批 7），并在同时携带三种已废弃伪造头时验证：

| 边界 | 期望 | 证据 |
| --- | --- | --- |
| 无 Session | 401 | 所有 23 个 API |
| 已登录但角色错误 | 403 | 所有 23 个 API |
| 已认证且无权知道资源存在 | 404 | `CustomerTicketApiTest`、`SupportPrincipalSecurityTest`、`SupportWorkbenchControllerTest` |
| 已认证、资源可见但版本、游标或租约冲突 | 409 | `CustomerTicketApiTest`、`SupportWorkbenchControllerTest`、`ApprovalControllerTest` |

客户、客服和审批专用 Principal 安全测试进一步验证伪造头不能改变主体、角色、capability、客户归属、客服分配或审批租约。`HumanSessionSecurityTest` 对当前身份响应采用精确字段集合断言，并验证认证错误不回显密码、cookie、CSRF、路由或动态资源权限。

## 扫描与回归

- `scripts/assert-deprecated-human-auth-contract.ps1` 由规范化检查调用，拒绝产品运行路径再次出现三种旧头，并拒绝产品、演示或入口文档再次出现旧 `/api/demo` 或旧 cookie。
- 旧头字面量只允许保留在明确的伪造攻击测试或前端“不发送该头”的负向断言中；ADR 中的唯一历史说明明确标记契约已经废弃并删除。
- `MachineIdentityApiTest`、Agent 组件门和全栈 Smoke 继续验证机器身份的最小权限链；Smoke 的所有正常人工请求均使用受控登录 Session。
