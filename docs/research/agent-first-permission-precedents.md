# 受限 Agent-first 客服流程：Chatwoot 与 LangGraph 先例核验

> 调研日期：2026-08-09  
> 范围：只核对 Chatwoot、LangChain/LangGraph 的官方文档、官方 API 和官方仓库。  
> 结论边界：本文区分“来源直接证明的能力”和“本项目需要自行保证的设计”。

## 结论

用户提出的方向有可靠先例，但不能整体照搬为实现保证：

- **Chatwoot 直接证明了 Bot-first 与显式人工交接模式。** Bot 绑定 inbox 后，新会话自动进入 `pending`，Bot 接收会话事件、可查询外部系统并回复；需要人工时把会话切为 `open`。[Chatwoot AgentBot 指南](https://www.chatwoot.com/hc/user-guide/articles/1677497472-how-to-use-agent-bots)
- **LangGraph 直接支持自动路由和敏感工具 HITL。** 条件边可以把输入路由到不同处理节点；HITL 中间件或 `interrupt()` 可在工具执行前暂停，并接受 approve/edit/reject 决定。[Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) / [Human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)
- **“每次运行仅绑定一个工单、每次工具调用重验关系、转人工后拒绝迟到输出”不是上述项目替我们完成的能力。** Chatwoot 和 LangGraph 提供状态、身份、锁、checkpoint、并发策略等原语；Spring Boot 仍需成为最终授权与业务写入门禁。

因此，“受限 Agent-first”有充分依据作为候选方案；可靠性与权限边界仍是本项目自己的确定性设计，不能归因于框架默认安全性。

## 1. Chatwoot：Bot-first 与 handoff

### 1.1 直接证据

- AgentBot 连接到 inbox 后，新 conversation 自动为 `pending`；Chatwoot 将 `widget_triggered`、`message_created`、`message_updated` 等事件发送到 Bot webhook。Bot 可以调用外部系统获取订单等信息，并通过 Chatwoot API 回复。[AgentBot 指南](https://www.chatwoot.com/hc/user-guide/articles/1677497472-how-to-use-agent-bots)
- Bot 可把 conversation 状态切到 `open` 以交给人工；官方术语也将 Agent Bot 定义为“处理会话初始部分，并在需要时交给人工”的 Bot。[AgentBot 指南](https://www.chatwoot.com/hc/user-guide/articles/1677497472-how-to-use-agent-bots) / [Chatwoot Glossary](https://www.chatwoot.com/hc/user-guide/articles/1677141565-chatwoot-glossary)
- AgentBot 是独立身份：创建 Bot 的 API 返回其自己的 `access_token`，并可关联 `account_id`；Bot 通过 inbox 配置接入。[Create Agent Bot](https://developers.chatwoot.com/api-reference/agentbots/create-an-agent-bot) / [Set Agent Bot on Inbox](https://developers.chatwoot.com/api-reference/inboxes/add-or-remove-agent-bot)
- 当前官方源码把 Bot handoff 限定为 AgentBot 将 `pending` conversation 改为 `open`；handoff 会清除该 conversation 的 `assignee_agent_bot` 并派发 handoff 事件。人工打开会话时的相关更新使用数据库锁。[Conversations controller](https://github.com/chatwoot/chatwoot/blob/develop/app/controllers/api/v1/accounts/conversations_controller.rb) / [Conversation model](https://github.com/chatwoot/chatwoot/blob/develop/app/models/conversation.rb)
- 官方 webhook 文档提供签名、时间戳及可用时唯一的 `X-Chatwoot-Delivery`，可供接收端验证来源、防重放并对重试去重。[Webhook 指南](https://www.chatwoot.com/hc/user-guide/articles/1677693021-how-to-use-webhooks)

### 1.2 限制与本项目推论

- Chatwoot 指南还写明 Bot 会继续监控 `open` conversation，为人工提供上下文；官方 Rasa 示例讨论也说明集成方需自行只在 `pending` 时自动回复。[AgentBot 指南](https://www.chatwoot.com/hc/user-guide/articles/1677497472-how-to-use-agent-bots) / [官方示例 handoff 讨论](https://github.com/chatwoot/rasa-agent-bot-demo/issues/12) 因此，**handoff 状态变化不等于外部 Agent 的在途任务已经取消，也不天然阻止迟到回复**。
- 独立 Bot token 和 conversation 级 Bot 指派，不能证明 token 天然只可访问一个 conversation；也没有证据表明 handoff 会使 token 本身失效。故“单工单运行”和“每次工具调用重验工单、客户、订单关系”是本项目新增的最小权限控制。
- `X-Chatwoot-Delivery` 支持 webhook 接收去重，但没有找到 AgentBot `Create Message` API 的幂等键保证，也没有找到 LLM 并发回复排序或迟到输出取消的原生保证。项目仍需自己的消息去重键、唯一约束、版本检查与发送门禁。

### 1.3 再次转人工时的历史负责人

- Chatwoot 支持把对话保留在 `Unassigned` 队列供合格成员领取，也支持从当前 eligible agents 中自动分配；当原 assignee 不再属于新 team 时，系统会清除该 assignee。[自动分配](https://www.chatwoot.com/hc/user-guide/articles/1677696868-assigning-conversations-in-a-round_robin-fashion) / [Teams](https://www.chatwoot.com/hc/user-guide/articles/1677492970-adding-teams)
- Zammad 的官方组设置明确支持两种策略：客户回复已关闭工单时，可保留 last owner，也可清空为 `nobody`；官方文档标注的默认值是保留。[Zammad Group Settings](https://admin-docs.zammad.org/en/6.1/manage/groups/settings.html)
- osTicket 官方用户文档可确认客户回复可重开工单、工单访问受 Department/Group/直接分配约束，且支持 release assignment；“重开后分配给最后回复者”的明确说明主要来自其官方社区，证据强度低于前两项。[osTicket Tickets](https://docs.osticket.com/en/latest/Agent/Tickets/Tickets.html) / [官方社区说明](https://forum.osticket.com/d/102304-disable-ticket-assignment-on-reply)

因此，成熟项目同时存在 continuity-first 与 queue/routing-first 策略，不存在唯一通行做法。本项目选择“历史负责客服只是软路由信号”，是因为完整工单权限严格来自当前 active assignment；历史关系不能自动恢复对敏感工单的访问权。

## 2. LangChain / LangGraph：路由、HITL 与运行可靠性

### 2.1 直接证据

- LangGraph 官方 routing 示例使用结构化输出和 conditional edges 将输入自动分流到不同节点；Graph API 也支持 conditional entry point。[Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) / [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- LangChain HITL 中间件允许按工具名配置 `interrupt_on`，工具调用命中策略时会在执行前暂停，审阅者可 approve、edit 或 reject；恢复必须使用同一 `thread_id`。[Human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)
- LangGraph `interrupt()` 也可直接放进敏感工具，在实际副作用前暂停并等待人工决定。[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- Functional API 明确要求 API 调用等副作用放进 task，并设计为幂等；任务失败后恢复可能重新执行，应使用 idempotency key 或先查询既有结果。[Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)
- LangSmith Agent Server 对同一 thread 的并发运行提供 enqueue、reject、interrupt、rollback 四种策略；默认 enqueue 会串行处理后来输入。[Double texting](https://docs.langchain.com/langsmith/double-texting)
- LangGraph Platform 的认证中间件在每次请求运行，并可通过资源 metadata 过滤 thread/run 等资源。[Authentication and access control](https://docs.langchain.com/langsmith/auth)

### 2.2 限制与本项目推论

- 官方 routing 示例证明的是通用自动分流能力，不是现成的“客服事实冲突/工具失败/客户要求人工”分类器；这些条件、置信度与失败处理仍需本项目确定性定义和测试。
- HITL 能暂停工具调用，但 **interrupt 或 `thread_id` 不是审批授权证据**。审批人身份、提案版本、职责分离和执行权限必须由 Spring Boot 校验并持久化。
- double texting 是 **LangSmith Deployment / Agent Server** 能力，官方明确说明它不属于 LangGraph 开源框架本身。即使采用 Agent Server，`interrupt` 也可能发生在工具已发起但未完成时；文档要求应用自行处理部分工具调用。因此重复触发、并发客户消息和迟到输出仍需业务层 fencing。
- LangGraph 的资源授权可以作为部署层防线，但不会自动理解本项目的 ticket-customer-order 关系。若工具由 Spring Boot 暴露，Spring 应在每次调用时依据独立机器身份、`ticketId`、当前 `handlingMode`、run generation/version 和资源关系重新授权。

## 3. 对当前方案可安全采用的表述

可以把候选流程表述为：

1. 客户创建或公开回复工单时，系统以独立受限机器身份自动触发绑定该工单的 Agent run。
2. Agent 可读取经过 Spring 授权的订单、物流和政策事实，可询问客户、发送进度说明、直接回答支持范围内的问题，并可生成补偿提案。
3. 补偿审批与执行始终由确定性业务接口控制；Agent 不能批准或执行补偿。
4. 事实冲突、工具失败、超出场景或客户要求人工时，将 `handlingMode` 从 `AGENT` 切为 `HUMAN`，并生成接手摘要；工单生命周期状态与处理模式分开。
5. 所有公开发送和工具调用都在执行前重新校验当前模式和 run generation；handoff 后的旧 run 即使完成，也只能被拒绝或记为过期结果。
6. 客户消息、触发事件、工具副作用和公开回复分别使用稳定幂等键；同工单采用串行化或乐观版本控制，明确处理重复投递、并发回复和迟到输出。

其中第 1、2、4 项的总体交互形态有 Chatwoot/LangGraph 先例；第 3、5、6 项是本项目在其原语之上增加的安全不变量。

## 验证范围

- 本文核对的是 2026-08-09 可访问的官方文档、官方 API 与官方仓库 `develop` 分支，未运行 Chatwoot 或 LangGraph 示例。
- 仓库分支和 SaaS/部署功能可能变化；实现前应锁定版本并以集成测试验证 handoff、并发输入、重复事件和旧 run 输出拒绝。
- 未找到 Chatwoot 原生保证单 conversation token、消息发送幂等、在途 Agent 取消或迟到输出隔离的官方证据。
