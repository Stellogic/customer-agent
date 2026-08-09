# 决策草案：流式产品事件与断线恢复契约

> 状态：等待与“定义首个纵向切片与验收矩阵”的最终结果核对；未经用户许可，不关闭对应 Wayfinder issue。

## 1. 总体边界

React 只消费 Spring 提供的**权威快照**和**白名单产品事件**。Spring 查询接口是当前业务状态的权威；SSE 只改善实时体验，不能成为唯一事实来源。Agent Server 原始流、prompt、模型输入输出、自由形式推理、原始工具 payload、checkpoint、thread/run/trace 等内部标识不得进入浏览器产品事件或业务审计。

Spring 订阅 Agent Server 原始流后，只把已识别的上游信号映射为封闭的产品事件类型。未知类型默认丢弃并记内部 observability；不能透传或使用“任意 JSON”兜底。Spring 自己产生的提案、审批、执行和最终工单结果同样进入产品事件日志，但其业务表仍是权威。

产品事件按授权投影视图分流：`CUSTOMER_PUBLIC`、`SUPPORT_WORKBENCH` 和以当前提案版本/审批租约为范围的 `APPROVAL_VIEW` 各有独立的 epoch、序号和白名单。底层业务事实只保存一份；视图流是授权投影，不是新的业务真值。这样客户看不到客服内部事件时，不会因为全局序号被过滤而产生伪缺口。

## 2. 浏览器契约

### 权威快照

`GET /api/tickets/{ticketId}/workbench` 在每次请求时校验当前权限，返回客服角色范围内的完整页面投影以及 `cursor = epoch:sequence`。客户公开投影与审批投影使用独立端点、独立数据形状和独立视图流；客户快照不含 generation、调查事实、工具进度或提案草稿，审批快照只含当前提案版本的审批证据与租约状态。审批投影以提案版本和审批租约为范围，不能复用客服工作台事件流取得完整工单。

### SSE 增量流

每种投影视图使用对应的 SSE 端点和同源 HttpOnly 会话认证。Spring 在建立连接、重放每个事件、投递实时事件时都按当前主体与资源关系复核权限；权限或租约失效即停止投递并关闭连接。实现可用授权变更通知加周期性复核缩短撤销窗口，不能只在连接建立时鉴权一次。

首次连接使用快照返回的 `after` 游标；自动重连由浏览器按 SSE 标准携带 `Last-Event-ID`。游标不是授权凭据。SSE 心跳使用 comment，不占产品序号。

### 产品事件信封

```json
{
  "schemaVersion": 1,
  "id": "ticket-demo-001.support.v1:42",
  "type": "investigation.phase_changed",
  "ticketId": "ticket-demo-001",
  "viewType": "SUPPORT_WORKBENCH",
  "generationId": "gen-002",
  "occurredAt": "2026-08-09T10:00:00Z",
  "payload": { "phase": "POLICY_EVALUATION" }
}
```

- `id` 同时作为 SSE `id`；`epoch` 标识一次兼容的授权投影视图流历史，`sequence` 在该视图流内严格递增。不同视图不得共享游标。
- 页面只按 `sequence` 应用事件，不按 `occurredAt` 排序；时间只用于展示。
- `generationId` 只在客服工作台调查事件中作为业务代次关联，不是权限凭据；客户公开流和审批流不暴露它。除 generation 生命周期事件外，客服调查事件只在其代次仍为当前代次时生效。
- payload 必须按事件类型封闭校验字段，未知字段拒绝进入产品事件日志。

## 3. 事件白名单

| 产品事件 | 最小公开字段 | 用途 |
|---|---|---|
| `public.progress_changed` | 固定公开状态码 | 客户公开进度，不包含内部调查事实 |
| `customer.message_published` | 固定消息模板码 | 通知客户等待审批、转人工或最终结果 |
| `generation.activated` | `generationId` | 表达当前有权 Agent 代次 |
| `generation.revoked` | `generationId`, `reasonCode` | 终止旧代次的页面影响 |
| `investigation.phase_changed` | 受控 `phase` | 调查阶段 |
| `evidence.added` | `evidenceRef`, `category`, 安全摘要 | 引用可授权访问的业务证据 |
| `tool.progress_changed` | 产品级 `operationRef`, 类别, 状态 | 受控工具进度，不暴露调用参数/结果 |
| `investigation.input_required` | 产品级 `requestRef`, 输入类别, 文案键, 允许动作 | 表达调查内部 interrupt，不透传 interrupt payload |
| `proposal.created` | 不可变 `proposalRevisionRef`, 安全摘要 | 提示提案已形成；详情另查授权视图 |
| `ticket.result_changed` | 工单状态, 结果码 | Spring 已确认的最终业务结果 |
| `investigation.failed` | 受控原因码, 是否可重试 | 不暴露异常、trace 或模型输出 |
| `approval.lease_changed` | 提案版本引用, 租约状态 | 仅审批视图 |
| `approval.decision_recorded` | 提案版本引用, 审批结果 | 仅审批视图，决定后终止持续访问 |

`reasoning`、token、debug、checkpoint、task、原始 messages、原始 tool call/result 等 LangGraph stream mode 不进入产品事件白名单。需要工具进度时，只接受 Agent 主动产生的、结构已约束的 custom 信号，再由 Spring 重新校验并投影。

## 4. 去重、顺序与恢复

1. React 先替换为快照并记住其游标，再建立 SSE；不能把新快照与旧本地状态合并。
2. 收到 `sequence <= lastSequence` 时作为重放重复项忽略。
3. 收到 `sequence == lastSequence + 1` 时应用事件。
4. 出现序号缺口、epoch 不同、不支持的 schema、非法字段或游标已超出保留窗口时，立即停止应用增量、关闭流并重新获取快照；不能猜测缺失事件。
5. Spring 从持久产品事件日志重放 `after` 之后的事件，再无缝切入实时订阅。快照游标与重放边界必须避免“查完快照、订阅实时”之间漏事件。
6. 旧 generation 的迟到事件在 Spring 投影入口进行 fencing；React reducer 再做一次防御性忽略。迟到结果是否需要审计由 Spring 审计模型处理，不向页面泄露内部细节。

若事件历史被裁剪或 schema 发生不兼容变化，Spring 发送不带业务序号的 `stream.reset_required` 控制事件后关闭连接，或直接返回可识别的重置响应；React 必须 `EventSource.close()` 并重新获取快照，避免浏览器自动重连循环。

## 5. 原型结论和限制

确定性场景覆盖：白名单投影、重复事件、序号缺口、快照后重放、新旧 generation 交替、权限撤销、epoch 变化、未知原始事件、非法敏感字段，以及客户公开流过滤内部事件后仍保持连续游标。原型证明状态模型内部一致，不证明 Spring MVC/WebFlux 实现、数据库并发、浏览器真实自动重连、代理缓冲或端到端授权已运行验证。

进入规格后至少需要三类真实验证：Spring 产品事件日志的并发序号与快照/订阅无缝切换；浏览器断线与 `Last-Event-ID` 重连；审批租约或客服访问撤销后既有 SSE 连接在限定时间内停止投递。

## 6. 官方证据

- WHATWG HTML SSE 标准定义 `EventSource`、事件 `id` 与重连时的 `Last-Event-ID`：<https://html.spec.whatwg.org/multipage/server-sent-events.html>
- Spring `SseEmitter` 支持事件名、ID 与数据字段：<https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/web/servlet/mvc/method/annotation/SseEmitter.html>
- LangGraph 官方流式文档区分 `updates`、`values`、`messages`、`custom`、`checkpoints`、`tasks`、`debug`；本项目只允许受控投影，不直接公开这些原始模式：<https://docs.langchain.com/oss/python/langgraph/streaming>
- LangGraph 官方 interrupts 文档说明恢复会重跑节点、interrupt 前副作用必须幂等：<https://docs.langchain.com/oss/python/langgraph/interrupts>
