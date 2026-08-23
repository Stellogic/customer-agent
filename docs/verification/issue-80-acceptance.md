# Issue #80 验收与 bundle 证据

## 门禁组成

- `pwsh ./scripts/check.ps1` 先执行既有组件检查与全栈 smoke，再执行 `scripts/issue80-acceptance.ps1`。
- Issue #80 浏览器验收每次生成唯一 Compose project、端口、镜像标签和两个专用卷；失败路径也只清理本次 project、卷和精确镜像标签，并回读确认不存在残留。
- Chromium 只访问同一隔离 Docker network 内自建的 HTTPS React/Nginx 与 Spring 服务。测试固定为单 worker、零重试；只有镜像仓库/构建阶段允许最多五次有界重试。

## 浏览器覆盖

- 匿名、客户、仅客服、仅审批、客服+审批五类身份的 Shell、菜单、默认落点与直接 URL。
- 真实密码登录、刷新恢复、CSRF、主体替换、跨标签退出、Secure/HttpOnly/SameSite Cookie。
- Spring 重启后的旧 Session 失效；生产默认仍为 30 分钟，验收通过 Servlet 可表达的最短有效值 `SERVER_SERVLET_SESSION_TIMEOUT=1m`，静默等待后执行同一真实到期机制。
- 客户公开投影、客服队列/领取详情、独立审批租约、双角色派生版本禁止自审，以及伪造 `X-Synthetic-*` 头无效。
- 客户访问其他客户工单返回 404；客服领取前队列条目严格只有 `ticketId`、状态、处理方式和入队时间四类字段。
- 真实响应区分 401/403/404/409；不兼容 SSE 游标返回 409 并要求重读权威快照。
- 真实浏览器先建立 SSE，再分别触发跨标签 Session 退出、客服 assignment 撤销、审批 lease 撤销和提案版本失效；每种场景都在 60 秒内移除旧视图并重读 Spring 权威资源或队列。assignment/lease/version 变化由只存在于隔离验收容器的 PostgreSQL 客户端驱动，不增加生产测试后门。

既有后端与前端回归继续覆盖投影协议、授权最长陈旧 60 秒及执行/对账链。浏览器门禁没有把单实例本地 Compose 外推为 OIDC、跨实例 Session 或生产身份源验证。

## 生产 bundle 实测

测量命令为 `npm run build`，数据来自 `vite build` 生成的 `dist/.vite/manifest.json` 和产物实际字节；`frontend/scripts/assert-bundle-evidence.mjs` 在每次构建重新计算，并断言内部 Shell、内部首页、客服与审批工作区都是 dynamic entry，且不进入客户首屏静态闭包。

2026-08-23 当前源码测量：

| 范围 | 原始字节 | gzip 字节 |
|---|---:|---:|
| production entry 静态闭包 | 249,093 | 80,275 |
| 客户首屏闭包 | 347,878 | 118,524 |

内部路由独立入口 chunk 的当前值：`InternalShell` 24,210 B、`InternalLanding` 133,933 B、`SupportWorkspace` 9,632 B、`ApprovalWorkspace` 8,199 B（精确 hash 与压缩值以每次门禁输出为准）。本票没有凭空设定数值预算；硬门禁约束的是“必须测量并输出真实值”和“内部路由不得泄漏进客户首屏闭包”。后续若有经过批准的性能预算，可直接在同一脚本增加数值上限。
