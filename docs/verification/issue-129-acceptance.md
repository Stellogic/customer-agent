# Issue #129 Flash 客户沟通与真实浏览器验收

## 交付边界

- 仅使用合成客户、订单、消息和调查事实；真实供应商配置只从调用进程注入 Agent Server。
- `deepseek-v4-flash` 客户沟通与调查判断、自主行动保持独立接口；普通运行和 CI 仍默认使用固定假模型。
- 客户沟通正式模式固定为最多 2 次供应商尝试、15 秒整体截止，不切换模型、不回退 fake；失败统一进入既有安全转人工路径。
- Spring 在公开发送前继续复核当前处理代次、处理模式、客户人工偏好、证据范围、订单范围和禁止承诺；模型不决定补偿金额、审批或执行。
- 脱敏证据不保存或输出 key、完整提示、模型响应正文、原始供应商 payload、业务对象标识、内部 Agent 地址或 checkpoint 标识。

## 真实 Flash 可复核指标

2026-08-25 至 2026-08-26 使用 `D:\customer-agent\.env` 中显式配置的 `deepseek-v4-flash`，在专用 Compose project 中完成一次正式成功路径：

- 逻辑模型调用：8；供应商尝试：8；没有重试或模型切换。
- 估算总费用：1415 micro-USD。
- 客户沟通：1 次逻辑调用、1 次供应商尝试、556 tokens、348 micro-USD、1159 ms。
- 结果：业务路径成功；客户沟通失败分类为空；未转人工。
- 调查行动、调查判断和客户沟通分别占 6、1、1 次逻辑调用；Spring 终态为 generation/submission 完成、`AGENT` 处理模式、提案等待人工审批。

机器可读脱敏指标位于 `docs/delivery/issue-129-formal-report.json`。

## 安全与异常结果

- 离线受控测试覆盖 429/503 有界重试、非法或越权 envelope、提示注入、未经批准的补偿或退款宣告、意图与证据不匹配以及配置缺失；全部失败关闭且无 fake 回退。
- LangGraph 接缝测试证明客户沟通异常不提交调查结论、不发送模型正文，立即调用 Spring 安全转人工。
- 人工偏好和迟到处理代次继续由 Spring 权威校验阻止自动发送；客户、客服和审批人的既有授权投影矩阵保持通过。

## 测试与浏览器验收数

- Agent 组件规范化门禁：179 passed；Ruff、Pyright 均通过。
- 完整 `pwsh ./scripts/check.ps1`：Backend、Agent、Frontend 三组件门禁 3/3，通过完整 PostgreSQL/Spring/LangGraph/React 集成与 FULL_RESET_GATE。
- Issue #129 真实 Flash Chromium：3 passed，覆盖提示注入下无需补偿自动回复与 SSE 恢复、客户澄清后等待人工审批、客户人工偏好与客服领取前后授权隔离；网络、SSE 与 bundle 泄漏检查同步通过。
- 完整规范化 Chromium：主矩阵 24 passed；后端重启和加速 Session 到期矩阵共 3 passed、3 conditional skips。

## 资源隔离与清理

- 真实模型验收使用专用 project、随机宿主端口、独立卷/网络和 `issue129-*` 镜像 tag；执行前通过 `docker compose config --format json` 读回确认。
- 完整规范化门禁另用独立 `customer-agent-issue129-final-*` project；Issue #80 浏览器门禁继续使用其自有随机 project。
- 三组自有容器、卷和网络在完成后均回读为空；既有 `customer-agent-baseline` 未被停止、重建或清理。
