# Issue #129 Flash 客户沟通与真实浏览器验收

## 交付边界

- 仅使用合成客户、订单、消息和调查事实；真实供应商配置只从调用进程注入 Agent Server。
- `deepseek-v4-flash` 客户沟通与调查判断、自主行动保持独立接口；普通运行和 CI 仍默认使用固定假模型。
- 客户沟通正式模式固定为最多 2 次供应商尝试、15 秒整体截止，不切换模型、不回退 fake；失败统一进入既有安全转人工路径。
- Spring 在公开发送前继续复核当前处理代次、处理模式、客户人工偏好、证据范围、订单范围和禁止承诺；模型不决定补偿金额、审批或执行。
- 脱敏证据不保存或输出 key、完整提示、模型响应正文、原始供应商 payload、业务对象标识、内部 Agent 地址或 checkpoint 标识。

## 真实 Flash 可复核指标

2026-08-26 使用 `D:\customer-agent\.env` 中显式配置的 `deepseek-v4-flash`，按批准的 43 次逻辑调用、49 次供应商尝试与 400000 micro-USD 三重硬上限执行唯一一次最小完整复验。复验在第二条 Chromium 路径出现非预期转人工后立即停止：

- 累计逻辑模型调用：18；供应商尝试：18；没有重试或模型切换。
- 累计估算费用：3157 micro-USD。
- 客户沟通：2 次逻辑调用、2 次供应商尝试、累计 3191 ms、778 micro-USD。
- Spring 结果：2 个代次完成、1 个代次转人工；转人工代次包含真实模型调用。
- 失败点：第一条自动安全回复 Chromium 路径通过；第二条澄清路径未出现等待客户回复状态，而是非预期转人工。其余三条路径按首错即停规则未执行。
- 当前结论：脱敏证据完整，但正式真实浏览器验收未通过，Issue #129 尚未达到正式交付条件。

机器可读脱敏指标位于 `docs/delivery/issue-129-formal-report.json`。

### 澄清单路径复验与离线根因

获批的首次单路径复验在第 2 次 action 调用后按首错即停规则安全转人工；失败证据原样保留于
`docs/delivery/issue-129-clarification-failure-report.json`：2 次逻辑调用、2 次供应商尝试、
记录估算费用 0 micro-USD，未提交或恢复澄清、未生成客户回复，Spring 权威终态为
`HANDED_OFF/HUMAN/INVALID_MODEL_OUTPUT`。失败响应未留下可计费 usage，因此 0 仅表示已记录估算，
不能证明供应商实际未计费。

脱敏 checkpoint 只保留了通用 `MODEL_CALL_FAILED`，不足以事后唯一判定供应商响应属于 refusal、
incomplete、空正文、非法 JSON 或 schema 越界。离线重放定位到可确定的最窄契约缺陷：
`REQUEST_CLARIFICATION` 的动态 JSON Schema 允许非空订单引用，而解析器要求所有终止动作必须为
`null`；供应商可返回 schema 合法但被本地解析器拒绝的结果。修复将终止动作字段收紧为 `null`，
事实读取动作收紧为权威引用常量，并使 action adapter 分别保留 `PROVIDER_INCOMPLETE`、
`OUTPUT_TRUNCATED`、`MODEL_REFUSAL`、`EMPTY_OUTPUT`、`INVALID_JSON` 与 `SCHEMA_MISMATCH`，同时在
失败 checkpoint 中保留脱敏 token/费用。历史失败证据不改写，也不伪造更细分类。

修复后的唯一获批复验仍按首错即停：3 次逻辑调用、3 次供应商尝试、558 micro-USD，其中客户沟通
1 次、976 ms、268 micro-USD。新的脱敏分类为 `SCHEMA_MISMATCH`；澄清已提交并恢复，
`CLARIFICATION_REQUIRED` 安全客户回复已生成，但恢复后的事实读取 action 响应校验失败，Spring
权威终态为 `HANDED_OFF/HUMAN/INVALID_MODEL_OUTPUT`。这排除了等待条件、澄清恢复状态和客户沟通
envelope。恢复轮第 1 次 `CONFIRM_ORDER` 已通过相同 envelope、JSON 反序列化和 usage 校验；第 2 次
事实读取 action 唯一新增的跨层约束，是由供应商回显 `orderReference`、动态 schema 要求字符串常量，
领域解析器再与权威事实精确比较。最小离线夹具证明该重复约束会把 action 选择变成
`SCHEMA_MISMATCH`；修复后模型只返回受控 action，引用由本地已校验 state 确定性注入。历史证据未保存
供应商返回的是 null 还是非精确字符串，因此不伪造该子细节。该轮失败证据固定保留于
`docs/delivery/issue-129-clarification-schema-failure-report.json`；最新一次复验使用
`docs/delivery/issue-129-clarification-retest-report.json`。

## 安全与异常结果

- 离线受控测试覆盖 429/503 有界重试、非法或越权 envelope、提示注入、未经批准的补偿或退款宣告、意图与证据不匹配以及配置缺失；全部失败关闭且无 fake 回退。
- LangGraph 接缝测试证明客户沟通异常不提交调查结论、不发送模型正文，立即调用 Spring 安全转人工。
- 人工偏好和迟到处理代次继续由 Spring 权威校验阻止自动发送；客户、客服和审批人的既有授权投影矩阵保持通过。

## 测试与浏览器验收数

- Agent 组件规范化门禁：190 passed；Ruff、Pyright 均通过。
- 完整 `pwsh ./scripts/check.ps1`：Backend、Agent、Frontend 三组件门禁 3/3，通过完整 PostgreSQL/Spring/LangGraph/React 集成与 FULL_RESET_GATE。
- Issue #129 最新真实 Flash Chromium：1 passed、1 failed、3 not run；失败后未重试。
- 完整规范化 Chromium：主矩阵 24 passed；后端重启和加速 Session 到期矩阵共 3 passed、3 conditional skips。

## 资源隔离与清理

- 真实模型验收使用专用 project、随机宿主端口、独立卷/网络和 `issue129-*` 镜像 tag；执行前通过 `docker compose config --format json` 读回确认。
- 完整规范化门禁另用独立 `customer-agent-issue129-final-*` project；Issue #80 浏览器门禁继续使用其自有随机 project。
- 本次失败复验的自有容器、卷和网络均回读为空；既有 `customer-agent-baseline` 保持 5 个容器运行，未被停止、重建或清理。
