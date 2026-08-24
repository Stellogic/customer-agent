# Issue #101 前端跨身份视觉与真实浏览器总验收

## 范围与基线

- 实现分支从独立干净工作树的 `origin/main@2627568390b96c1ee3e8df5f67ff261608bfea3a` 创建；该提交已经包含 #98、#99、#100 的正式交付。
- 本票只增加跨身份、跨页面与 bundle 总验证，并修正审批确认对话框的焦点管理；没有修改 Spring API、数据库、身份模型、领域状态机或数据投影。
- 最高验收接缝仍是生产构建后的 React/Nginx、Spring Security、业务服务、PostgreSQL 与真实 Chromium。Vitest/jsdom 只承担快速行为回归，不替代全栈浏览器证据。

## 页面切片既有证据

以下用例由前置页面切片提供，本票把它们显式纳入同一次单 worker、零重试的完整浏览器套件：

| 来源 | 既有证据 |
|---|---|
| #98 客户帮助中心 | 真实创建工单、状态与处理模式反馈、转人工、断线后的受保护内容隐藏与权威恢复 |
| #99 客服工作台 | 领取前最小队列、确认领取、领取后授权详情、窄屏桌面降级、assignment 撤销后清屏 |
| #100 审批工作台 | 领取前不读取审批视图、租约内证据、决定确认、释放或租约失效后清屏 |
| #80/#97 身份与 Shell | 未登录、客户、仅客服、仅审批人、双角色的落点、菜单、403/404、退出、主体替换、跨标签页与 Session 生命周期 |
| #80 授权与 SSE | 客户归属、客服分配、审批租约、禁止自审、assignment/lease/版本撤销后的最长 60 秒清屏与权威重读 |

## Issue #101 新增证据

`frontend/e2e/issue101.cross-role-acceptance.spec.ts` 在三个相互独立的 BrowserContext 中验证客户、客服和审批身份，避免单主体 Session 的主体替换被误当作多身份并存：

- 三个页面在 `1440 × 960` 桌面视口使用同一森林绿、米白画布、无衬线正文和衬线标题语言，并保存真实页面截图。
- 客户页保留真实表单标签且没有内部导航；仅客服与仅审批人分别不出现对方工作区入口，状态同时具有可访问文字而非只依赖颜色。
- `prefers-reduced-motion: reduce` 下页面进入动画被压缩至不超过 `0.01ms`。
- 审批确认对话框打开后把焦点移入对话框，Tab 在对话框内环绕，Escape 关闭后把焦点恢复到原触发按钮。

对应的 Vitest 公共 DOM 行为测试先失败于焦点仍停留在触发按钮，再通过最小实现补齐打开聚焦、Tab 约束、Escape 关闭和焦点恢复。

## 浏览器、构建与 bundle 证据

成功运行 `pwsh ./scripts/issue80-acceptance.ps1` 时：

- effective config：`project=customer-agent-issue80-b577a85b69e7`，随机宿主端口 `62836`，镜像 tag `issue80-b577a85b69e7`，卷 `customer-agent-issue80-b577a85b69e7_postgres-data` 与 `customer-agent-issue80-b577a85b69e7_browser-artifacts`。
- 启动前对该 project/tag 回读为 `containers=0 volumes=0 networks=0 images=0`。
- 主 Chromium 套件 `21 passed (44.1s)`；后端重启阶段 `1 passed, 1 skipped`；真实加速 Session 到期阶段 `1 passed, 1 skipped (1.1m)`。跳过项是同一双阶段文件中与当前阶段不匹配的另一条场景，不是跳过验收能力。
- 生产构建的 manifest 门禁确认 `InternalShell`、`InternalLanding`、`SupportWorkspace`、`ApprovalWorkspace` 均为 dynamic entry，且不进入客户首屏静态闭包。
- 本轮实测 production entry 静态闭包为 `468,175 B / 156,350 gzip B`，客户首屏静态闭包为 `497,331 B / 167,924 gzip B`。本票不新增未经批准的数值预算，结构隔离是可失败硬门禁。
- `finally` 删除本次容器、两个卷、三个网络与五个精确镜像名，并回读全部为空；未操作共享 Compose project 或共享数据卷。

## 门禁

- 聚焦 TDD：审批对话框焦点测试通过。
- TypeScript：`tsc --noEmit` 通过。
- 真实 Chromium 完整套件：通过。
- 最终交付仍以提交前字面量 `pwsh ./scripts/check.ps1`、Standards/Spec 双轴审查、GitHub CI、合并与 Issue 关闭读回为准。
