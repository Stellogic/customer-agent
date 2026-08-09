# 客服工单已解决、自动关闭、重开与 SLA 语义

> 调研日期：2026-08-09  
> 研究问题：工单是否区分“已解决/已关闭”、自动关闭等待期、客户回复后的重开行为，以及重开后的 SLA 周期。  
> 证据原则：优先采用成熟开源客服项目的官方文档、官方 API 与官方仓库源码；Jira Service Management 和 Zendesk 仅作闭源行业对照；不使用博客。  
> 决策边界：本文严格区分**来源事实**与**对本项目的建议**。任何来源未明确说明的行为均标为“未知”，不从界面名称推断实现。

## 结论摘要

| 问题 | 来源事实 | 对本项目的建议 |
|---|---|---|
| 是否区分 `Resolved` / `Closed` | Frappe Helpdesk 明确区分；Zammad 以 `pending close` 表达延迟关闭；Chatwoot 只有 `resolved`、没有 `closed`；FreeScout 只有 `closed`、没有 `resolved`。成熟产品不存在唯一模型。 | 保留 `RESOLVED` 与 `CLOSED`：前者是可恢复的软终态，后者是不可直接修改的归档终态。 |
| 自动关闭等待期 | Frappe 可按指定状态和天数配置，官方示例为 resolved 后 3 天；Zammad 逐票指定 `pending close` 的未来时间；Chatwoot 的自动化是把长期不活跃的 open 会话变成 resolved，并非 resolved 后再 closed；Jira ITSM 模板采用 3 个工作日。没有开源项目证明“固定 72 小时”是行业默认。 | MVP 采用 `RESOLVED` 后 **72 个自然小时**自动转 `CLOSED`。这是本项目选择，不应写成开源默认或行业强制标准。 |
| 客户回复是否重开、回到何状态 | Frappe 表述为回复后重开，但官方文档未明确目标状态；Chatwoot 明确自动回到 open；Zammad 默认重开原工单，也可配置超期后新建；FreeScout 源码把非 spam 会话改为 active。 | 72 小时窗口内，同一问题的客户公开回复使原工单回到 `INVESTIGATING`；已关闭后回复或新问题创建新工单，并关联原工单。 |
| 重开后的 SLA | Zammad 的 First Response / Solution Time 每票只适用一次，重开后可能按原票年龄立即升级；Chatwoot 报表不把重开视为新会话；Zendesk 的解决类 SLA 会恢复原目标和已耗/剩余时间。Frappe、FreeScout 对该问题的公开一手资料不足。 | 不创建新的解决 SLA 周期、不重置 24 小时预算；`RESOLVED` 期间视作暂停，重开后从原已耗时继续。首次响应 SLA 已完成，不重新启动。 |

## 1. 开源项目事实

### 1.1 Frappe Helpdesk：明确的软解决与最终关闭

**来源事实**

- 官方 Ticket 文档明确区分 `resolved` 与 `closed`：客服调查并回复后可标记 resolved；客户满意后可标记 closed；客户不满意可通过回复重开。[Frappe Helpdesk：Ticket](https://docs.frappe.io/helpdesk/ticket)
- 官方设置文档提供自动关闭配置：选择触发状态，并配置 `Auto-close after (Days)`；文档示例是工单处于 resolved 状态 3 天后自动关闭。这里的 3 天是示例值，字段本身可配置。[Frappe Helpdesk：Settings](https://docs.frappe.io/helpdesk/settings)
- 官方 SLA 文档把 `Resolved` 和 `Closed` 都列为 SLA fulfilled 状态；`Replied`（等待客户）暂停解决计时。[Frappe Helpdesk：Service Level Agreement](https://docs.frappe.io/helpdesk/service-level-agreement)

**未知**

- Ticket 文档只说客户回复会“reopen”，没有明确说明重开后的具体状态名。
- 现有公开文档没有明确说明重开会新建 SLA 周期、恢复旧周期还是重算截止时间。因此不能用 Frappe 支持“重开后 SLA 重置”或“不重置”的结论。

### 1.2 Zammad：`pending close` 加可配置的关闭后跟进策略

**来源事实**

- Zammad 的内置状态包括 `new`、`open`、`closed`、`pending close` 和 `pending reminder`；`pending close` 表示安排在未来自动关闭。[Zammad：Ticket State](https://user-docs.zammad.org/en/6.2/basics/service-ticket/settings/state.html)
- 组设置 `Follow-up possible` 决定客户回复 closed 工单后的行为。默认 `yes` 会重开原工单；也可配置保持原票关闭并创建新票，或仅在关闭后的指定天数内允许重开、超期后创建新票。[Zammad：Group Settings](https://admin-docs.zammad.org/en/6.1/manage/groups/settings.html)
- SLA 的 First Response 和 Solution Time 每张工单只适用一次。`pending close`、`pending reminder`、`closed` 默认忽略 SLA、处于冻结状态；工单因客户回复回到 open 后，可能根据原工单年龄立即升级。[Zammad：SLAs](https://admin-docs.zammad.org/en/latest/manage/slas.html)

**未知**

- 官方资料没有给出统一的默认自动关闭等待天数；`pending close` 是逐票选择未来关闭时间，不是全局固定 72 小时。
- 文档的 “freezed” 与“根据年龄立即升级”足以排除“重开即获得全新 SLA 预算”，但没有完整公开其截止时间数学公式；不能进一步断言所有暂停区间如何扣除。

### 1.3 Chatwoot：只有 resolved，没有 closed

**来源事实**

- 官方 API 允许的会话状态只有 `open`、`resolved`、`pending`、`snoozed`；官方源码的 `enum status` 也只有这四项，没有 `closed`。[Chatwoot：Toggle Status API](https://developers.chatwoot.com/api-reference/conversations/toggle-status) / [Chatwoot：Conversation model](https://github.com/chatwoot/chatwoot/blob/develop/app/models/conversation.rb)
- 官方用户指南说明 resolved 会话移出 Open 队列；客户再次回复会自动将其重开。[Chatwoot：Chatwoot 101](https://www.chatwoot.com/hc/user-guide/en/categories/chatwoot-101?theme=system)
- `auto_resolve_after` 以分钟配置不活跃会话自动解决时间，还可配置自动解决消息及是否忽略 waiting 会话。这是 `open → resolved`，不是 `resolved → closed`。[Chatwoot：Update account API](https://developers.chatwoot.com/api-reference/account/update-account)
- 官方报表把 Resolution Time 定义为首次打开到解决的时间；重开不算新会话，随后再次解决会增加该会话的 Resolution Time。[Chatwoot：Conversations Report](https://www.chatwoot.com/hc/user-guide/articles/1724140319-how-to-read-conversations-report)

**未知**

- 报表的 Resolution Time 能证明业务统计不把重开当作新会话，但不能单独证明 Chatwoot 的 SLA 引擎在重开时如何生成或恢复 SLA target；该项未找到明确官方说明。

### 1.4 FreeScout：只有 closed，客户回复回到 active

**来源事实**

- FreeScout 官方仓库的 Conversation 模型定义 `active`、`pending`、`closed`、`spam`，没有独立的 `resolved`；官方 FAQ 也明确表示不计划添加额外的 Resolved 状态。[FreeScout：Conversation.php](https://github.com/freescout-help-desk/freescout/blob/dist/app/Conversation.php) / [FreeScout：FAQ](https://github.com/freescout-help-desk/freescout/wiki/FAQ)
- 官方 `FetchEmails.php` 源码明确注明“Reply from customer makes conversation active”，并将非 active、非 spam 的原会话状态改为 `STATUS_ACTIVE`。因此 closed 会话收到客户邮件后会重新进入 active，而不是创建一个独立的 resolved 阶段。[FreeScout：FetchEmails.php](https://github.com/freescout-help-desk/freescout/blob/dist/app/Console/Commands/FetchEmails.php)

**未知**

- 官方 FAQ 将 SLA 和关闭通知等自动化指向 Workflows 模块，但没有给出核心系统统一的自动关闭等待期。
- 未找到 FreeScout 官方资料对“重开后解决 SLA 是否重置”的明确说明；不能根据状态回到 active 推断 SLA 周期行为。

## 2. Jira 与 Zendesk 行业对照

这些产品不是开源证据，仅用于检验建议是否偏离成熟客服产品的常见做法。

### 2.1 Jira Service Management

**来源事实**

- ITSM 模板内置 `Resolved → Closed`：`Time to close after resolution` 在设置 resolution 时启动，自动化在 3 个工作日后关闭请求。[Jira：Auto-close resolved service requests](https://support.atlassian.com/jira-service-management-cloud/docs/auto-close-resolved-service-requests/)
- Jira 的重开规则是可配置工作流/自动化，而非不可变平台语义。官方提供“客户评论 closed 请求后重开”的模板，也支持限制为解决后 X 天，超期提示创建新请求。[Jira：Managing Request Reopenings](https://support.atlassian.com/jira/kb/limit-customer-issue-reopening-to-x-days-after-resolution/)
- SLA 是否创建新周期取决于 START/STOP 条件；官方故障排查文档明确同一工单可出现多个已完成或进行中的周期。因此 Jira 不能为本项目给出唯一的“重开重置/延续”答案。[Jira：Troubleshooting SLA Issues](https://support.atlassian.com/jira/kb/how-to-troubleshoot-common-issues-with-slas/)

### 2.2 Zendesk

**来源事实**

- Zendesk 明确区分 Solved 与 Closed：Solved 可由客服设置，也可被客户回复重开；Closed 由自动化/触发器形成且不可重开，客户回复会创建引用原票的 follow-up ticket。[Zendesk：Solved 与 Closed 的区别](https://support.zendesk.com/hc/en-us/articles/4408887712154-What-is-the-difference-between-a-solved-ticket-and-a-closed-ticket) / [Zendesk：Follow-up tickets](https://support.zendesk.com/hc/en-us/articles/8421655952026-Understanding-follow-up-tickets)
- 解决类 SLA 在重开后不是统一清零：Agent Work Time 与 Requester Wait Time 恢复同一 target 和原已耗/剩余时间，把 Solved 时段视为暂停；Total Resolution Time 从创建时间继续，Solved 时段不计入目标。回复类 SLA 则可能激活新 target。[Zendesk：Defining SLA policies](https://support.zendesk.com/hc/en-us/articles/4408829459866-Defining-SLA-policies)

## 3. 对本项目的建议

以下是基于证据作出的**项目建议**，不是外部产品事实：

1. **区分软解决与最终关闭。** `RESOLVED` 表示客服已给出结论并完成当前必要处理，但客户仍可对同一问题提出异议；`CLOSED` 表示原工单不可直接修改。
2. **采用 72 个自然小时等待期。** 工单进入 `RESOLVED` 后启动独立的关闭等待计时；72 小时内没有客户公开回复则自动进入 `CLOSED`。Frappe 的可配置天数和 Jira 的 3 个工作日证明这种两阶段做法成熟，但“72 个自然小时”是本项目为了 MVP 简化而作的选择。
3. **窗口内重开原票。** 72 小时内客户针对同一问题公开回复，原工单回到 `INVESTIGATING`，保留负责人、历史、调查证据和补偿记录；内部备注与自动通知不触发重开。
4. **关闭后创建关联新票。** `CLOSED` 后的任何客户回复，或窗口内明显不同的问题，创建新工单并记录 `relatedTo`/`followUpOf` 关系；原工单保持不可变。该边界接近 Zendesk 的 follow-up ticket，也避免无限复活旧票。
5. **解决 SLA 不重置。** 重开恢复原 24 小时解决 SLA 的已耗时间与剩余时间，`RESOLVED` 等待期作为暂停区间；不创建新的 24 小时预算。首次响应 SLA 已完成，不因重开再次启动。若产品希望衡量重开响应速度，应另设 `nextResponse` 指标，而不是篡改首次响应。
6. **保留可审计事件。** 至少记录 `resolvedAt`、`resolvedBy`、`closeDueAt`、`closedAt`、`closeReason`、`reopenedAt`、`reopenReason` 和触发回复 ID；自动关闭与重开都应是显式领域事件，不能只覆盖当前状态。

建议的最小转换为：

```text
INVESTIGATING -> RESOLVED
RESOLVED --72h no customer reply--> CLOSED
RESOLVED --same-issue customer reply--> INVESTIGATING
CLOSED --customer reply--> NEW LINKED TICKET
```

## 4. 尚待决定与验证

- “同一问题”由确定性规则、客服确认还是 Agent 建议判定；建议 MVP 中由 Agent 提议、客服可纠正，不能让模型静默拆票。
- 自动关闭前是否发送提醒；这不影响状态机，但影响演示与通知设计。
- 24 小时解决 SLA 在进入 `RESOLVED` 时记录的是“已完成一次”还是仅暂停；建议同时保留每次 resolution attempt，便于计算首解时长、最终解决时长与重开率。
- 需要用可控时钟覆盖边界测试：`71:59:59` 回复、恰好 `72:00:00` 的竞争、自动关闭任务重试、关闭与客户回复并发、重复入站消息与时区转换。

## 5. 验证范围与限制

- 本文在 2026-08-09 核对了上述官方文档、官方 API 和官方仓库源码；未使用博客或第三方教程。
- 未克隆、构建或运行 Frappe Helpdesk、Zammad、Chatwoot、FreeScout；结论属于文档与静态源码核对，不是运行时验证。
- GitHub `develop`/`dist` 分支内容可能变化；实现前应锁定参考版本或 commit，再为本项目自己的状态机建立契约测试。
- Jira 和 Zendesk 只作为行业对照，不是开源实现依据，也不表示本项目必须复制其全部规则。
