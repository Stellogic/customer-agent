---
status: accepted
---

# 使用 Ant Design X 构建由 Spring 中转的对话界面

客户多工单对话界面采用 `@ant-design/x` 的 `Conversations`、`Bubble.List`、`Sender` 和 `Sources` 等组件，并使用消息 loading、streaming 和受控处理进度表达 Agent 从等待首字到完成回复的过程。统一创建的各工单立即并行开始独立处理，订单总览集中展示各工单状态和待客户事项，客户只能在对应工单内回复。浏览器仍只连接 Spring 的授权接口和 SSE，不直接连接模型或携带模型凭据；处理进度只展示允许公开的业务阶段，不展示模型内部推理。是否采用完整 X SDK 取决于它能否自然适配现有消息身份、权威快照、断线恢复和 Agent 处理代次隔离，不能仅因采用 UI 组件而默认引入。
