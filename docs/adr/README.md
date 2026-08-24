# 架构决策索引

本页统一索引仓库中的架构与工程决策，帮助实现者先找到当前有效结论，再按需追溯形成结论的规格、调研和 GitHub Issue。

## 事实源与阅读顺序

1. 优先读取本目录中状态为 `accepted` 的产品与应用架构决策。
2. 涉及具体工程工具、依赖和验证方式时，再读取 [`docs/decisions`](../decisions/) 中的工程 ADR。
3. 涉及完整业务边界、授权、状态机、协议或验收范围时，以 [`docs/specs`](../specs/) 中对应父规格的当前镜像为入口；GitHub `[规格]` Issue 仍是规格事实源。
4. Wayfinder Issues 保存决策形成过程和评论，只用于历史追溯，不应覆盖已接受 ADR 或后续规格。

如果实现与已接受 ADR 冲突，应先显式提出冲突并形成新的替代决策，不能静默修改架构边界。

## 已接受的产品与应用架构决策

| 决策 | 状态 | 主要范围 |
| --- | --- | --- |
| [一个 React 应用使用两个界面壳](./0001-one-react-application-two-shells.md) | accepted | 客户与内部工作台的界面壳、路由、导航和数据投影边界 |
| [渐进采用内部工作台组件栈](./0002-incremental-internal-workbench-stack.md) | accepted | Vite、React Router、Ant Design 与 Pro Components 的采用边界 |
| [分离登录入口并保持单主体 Session](./0003-separate-login-entry-single-subject-session.md) | accepted | 客户/内部登录入口、Session 主体、capability、CSRF 与 SSE 重授权 |

## 工程与验证 ADR

| 决策 | 状态 | 关联范围 |
| --- | --- | --- |
| [跨语言质量门禁](../decisions/0001-quality-guardrails.md) | 已接受 | 三端格式、Lint、类型检查、架构测试、统一检查和 CI |
| [静态 React Shell 与路由组件栈](../decisions/0002-static-react-shell-stack.md) | 已接受 | #71、#73；前端依赖版本、静态路由注册表和分包 |
| [Playwright 真实浏览器验收](../decisions/0003-playwright-browser-acceptance.md) | 已接受 | #80；真实浏览器、隔离 Compose 和 bundle 验收 |

## 父规格中的架构汇总

| 规格 | 汇总的主要架构边界 |
| --- | --- |
| [#11 客服工单调查与补偿审批 Agent MVP 首个纵向切片](../specs/issue-11.md) | Spring 业务权威、LangGraph 私有编排、可靠提交、权限与数据边界、产品事件投影、持久化和验收矩阵 |
| [#71 统一客户帮助中心与内部工作台的登录、鉴权及路由](../specs/issue-71.md) | 双界面壳、身份与 Session、页面 capability、资源授权、路由和迁移边界 |
| [#95 依据高保真原型统一视觉体验](../specs/issue-95.md) | 原型与真实 DTO/API/权限的边界，以及既有架构决策不被视觉实现替代的约束 |

## Wayfinder 历史决策链

以下 Issues 保存首个 MVP 架构形成过程。父规格 #11 已汇总其最终结论，但 Issue 评论中的讨论、修正和证据不会自动同步到仓库：

- [#1 明确 MVP 实施路线](https://github.com/Stellogic/customer-agent/issues/1)
- [#2 定义工单生命周期与 SLA 语义](https://github.com/Stellogic/customer-agent/issues/2)
- [#3 定义补偿政策、审批与执行不变量](https://github.com/Stellogic/customer-agent/issues/3)
- [#4 定义参与者、权限与敏感数据边界](https://github.com/Stellogic/customer-agent/issues/4)
- [#5 选择浏览器、Spring Boot 与 LangGraph 的信任边界](https://github.com/Stellogic/customer-agent/issues/5)
- [#6 验证 LangGraph 中断恢复与业务幂等方案](https://github.com/Stellogic/customer-agent/issues/6)
- [#7 定义首个纵向切片与验收矩阵](https://github.com/Stellogic/customer-agent/issues/7)
- [#8 定义流式事件与断线恢复契约](https://github.com/Stellogic/customer-agent/issues/8)
- [#9 核对核心技术版本与兼容基线](https://github.com/Stellogic/customer-agent/issues/9)
- [#10 确定页面信息架构与关键交互](https://github.com/Stellogic/customer-agent/issues/10)

## 维护约定

- 新的长期架构决定应新增或替代 ADR，并链接形成决定的规格、Issue 和证据。
- ADR 被替代时保留原文件和历史状态，在新 ADR 中明确替代关系。
- `scripts/sync-spec-docs.ps1` 只镜像标题以 `[规格]` 开头的 Issue 正文；`scripts/sync-ticket-docs.ps1` 只镜像明确归属于正式父规格的实施与验收票据。两者都不镜像评论、Wayfinder 调研或原型。
- 实施票据镜像见 [`docs/tickets`](../tickets/)；它负责记录交付切片和验收历史，不作为长期架构事实源，其中产生的长期决定应回写 ADR 或父规格。
