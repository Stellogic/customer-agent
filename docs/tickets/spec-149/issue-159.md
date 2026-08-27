# [对话] 交付 SSE 真流式输出与断线恢复

> 父规格：[#149 规格 重塑自然语言多工单客服 Agent 与知识工作台](../../specs/issue-149.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/159](https://github.com/Stellogic/customer-agent/issues/159)
> Issue 状态：OPEN
> 创建时间：2026-08-27T17:24:57Z
> 最后更新时间：2026-08-27T17:33:16Z
> 关闭时间：—
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

Part of #149

## What to build

通过 Spring 授权 SSE 向客户提供真实的等待首字、内容片段、持续更新和完成状态，并在断线、事件缺口、旧事件或页面恢复时回到权威快照；浏览器不直接连接 DeepSeek 或 Agent Server。

## Acceptance criteria

- [ ] Spring 产品事件明确表达 loading、stream-start、content-delta、completed、aborted 和 failed 等受控状态。
- [ ] 首个内容片段到达前显示加载气泡，随后按真实片段增量更新，不用定时切割完整假文本冒充流式。
- [ ] 新消息围栏旧代次后，旧内容片段被拒绝或忽略，且不会在完成事件后重新出现。
- [ ] SSE 断线、重复、旧事件、游标缺口、trimmed history 和 schema 不兼容均通过权威快照恢复。
- [ ] 页面刷新或重登可以恢复已持久化消息和当前生成状态，不把浏览器内存作为事实源。
- [ ] 公开处理进度只包含受控业务阶段，不包含 prompt、reasoning、原始工具响应、checkpoint 或内部运行标识。
- [ ] Ant Design X 组件通过兼容性验证后用于会话、气泡、输入和来源；完整 X SDK 不因 UI 组件而自动引入。
- [ ] 真实 Chromium 覆盖桌面、窄屏、慢首字、断线、重新同步、错误和终止状态。

## Blocked by

- #150
- #158
