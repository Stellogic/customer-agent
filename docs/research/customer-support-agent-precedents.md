# 客服工单调查与补偿审批 Agent：架构决策前置证据

> 调研日期：2026-08-08  
> 研究范围：React + Spring Boot + LangGraph 项目在架构设计前需要确认的工单、补偿审批与 Agent 运行时事实。  
> 证据原则：优先采用项目官方文档、官方仓库、框架参考文档与支付 API 官方文档；`D:\java-agent-\research\agent-fullstack-project-topics.md` 仅作为选题背景，不作为本文事实依据。  
> 决策边界：本文提供先例、约束和待决问题，**不替项目选择架构、状态机、数据库或协议**。

## 执行摘要

1. **成熟客服系统把工单当作长期业务记录，而不是一次对话。** Frappe Helpdesk 和 Zammad 都将客户往来、负责人/团队、状态、优先级和 SLA 放在同一个工单上下文中；Zammad 还提供“谁在何时做了什么”的工单历史。由此可以确认，聊天记录不能替代工单事实、内部调查记录和审计历史。
2. **SLA 是带日历与状态语义的计时规则，不是一个静态截止时间。** 两个项目都支持按条件匹配 SLA、按工作时间计算；暂停、履约、重新打开会改变计时或升级表现。项目在建模前必须先决定“等待客户”是否暂停、重开是否沿用原 SLA、补偿调查是否有独立时钟。
3. **补偿至少包含提案、授权决定与实际执行三个不同事实。** Stripe 的退款接口证明金额不能超过剩余可退金额，退款可能部分执行并处于 `pending`、`succeeded`、`failed` 或 `canceled` 等结果状态；幂等键用于安全重试，但同一键必须绑定相同参数。审批通过不能等同于退款成功。
4. **LangGraph 的 interrupt 是可恢复编排点，不是授权系统。** 官方文档要求持久 checkpointer 和稳定 `thread_id`；恢复会从发生 interrupt 的节点开头重跑，所以副作用必须放在 interrupt 之后、拆到单独节点并由业务 API 幂等保护。流式事件用于呈现进度，不应被当成最终业务事实。
5. **“Spring 保存确定性业务事实，LangGraph 编排调查”是有证据支撑的候选边界，但仍是推论而非已批准架构。** Spring 官方能力覆盖细粒度方法授权与本地事务，LangGraph 官方定位覆盖持久编排、HITL 和流式执行。Spring 文档同时明确事务上下文不会跨远程调用传播，因此不应假设 Java 与 Python 服务共享一个原子事务。
6. **许可证会影响参考方式。** Frappe Helpdesk 与 Zammad 仓库均标注 AGPL-3.0；若修改并以网络服务方式运行 AGPL 程序，AGPL 第 13 节涉及向远程用户提供相应源代码的义务。当前最保守的做法是学习其领域术语、行为和页面信息架构，而不复制代码；任何复用代码或深度集成决策都应单独做许可证评审。

## 证据对照表

| 关注点 | 直接证据（已核对） | 可用于设计讨论的推论（尚未批准） | 主要来源 |
|---|---|---|---|
| 工单生命周期 | Frappe：门户或邮件创建；调查后可解决，客户满意后关闭；客户回复可重开；可转派或升级到团队。Zammad：同一问题的往来消息作为 articles 归入工单，直到解决/关闭。 | 不应把 Agent run 的结束当作 ticket 的关闭；“Agent 调查完成”“客服已回复”“客户确认关闭”可能是不同事件。 | [Frappe Ticket](https://docs.frappe.io/helpdesk/ticket)、[Zammad Ticket Basics](https://user-docs.zammad.org/en/7.0/basics/ticket-basics.html) |
| 状态、负责人、队列 | Frappe 可按条件使用 Round Robin、Load Balancing 或字段分配；Zammad 工单含 owner、group、priority、state，并提供未分配、我的工单、即将/已经超 SLA 等工作列表。 | 工单归属与 Agent 执行归属应分开；队列分派需要确定性规则和人工改派能力。 | [Frappe First Steps](https://docs.frappe.io/helpdesk/your-first-steps-with-frappe-helpdesk)、[Zammad Browse](https://user-docs.zammad.org/en/6.3/basics/find-ticket/browse.html) |
| SLA | Frappe 为不同优先级配置首次响应/解决时间，支持履约状态、暂停状态、工作时间、节假日和条件匹配；Zammad 用日历和 ticket selector 匹配 SLA，关闭/待处理状态可冻结，重新打开时可能立即升级。 | SLA 计算器应是可测试的确定性业务能力；LLM 可以解释风险，但不应自行计算或改写 SLA 真值。 | [Frappe SLA](https://docs.frappe.io/helpdesk/service-level-agreement)、[Zammad SLA](https://admin-docs.zammad.org/en/latest/manage/slas.html) |
| 客户/客服入口与可见性 | Frappe 将客户门户访问和可见工单范围绑定到客户联系人角色；普通联系人默认只看自己提交的工单，customer manager 可看所属客户的全部工单。Zammad 默认有 Admin、Agent、Customer 角色，并可叠加 group permissions。 | React 即使共享组件，也需要按主体和资源重新鉴权；“知道 ticket ID/thread ID”不能带来读取或审批权限。 | [Frappe Customers & Contacts](https://docs.frappe.io/helpdesk/customers-contacts)、[Zammad Roles](https://admin-docs.zammad.org/en/latest/manage/roles/) |
| 历史与内部记录 | Zammad ticket history 展示自创建以来任何用户的更新、执行者和时间；Frappe comment 用于记录调查发现，便于后续经办人复用。 | 客户可见消息、内部调查笔记、Agent 推理摘要、业务审计应分别定义可见性；原始隐藏推理不应自动成为审计内容。 | [Zammad Work with Tickets](https://user-docs.zammad.org/en/latest/basics/work-with-tickets.html)、[Frappe Ticket](https://docs.frappe.io/helpdesk/ticket) |
| 知识库 | Frappe 的知识文章同时供客服复用和客户自助；Zammad 支持草稿、仅员工、公开可见性，多语言、搜索、定时发布，并用 reader/editor 权限控制。 | “可被 Agent 检索”与“可向客户引用/展示”需要不同权限；检索结果必须携带可见性与版本信息。 | [Frappe Knowledge Base](https://docs.frappe.io/helpdesk/lesson-4-knowledge-base)、[Zammad Knowledge Base](https://admin-docs.zammad.org/en/latest/manage/knowledge-base.html) |
| 补偿金额与对象 | Stripe 创建退款必须引用原 Charge 或 PaymentIntent；允许多次部分退款，但总额不能超过剩余未退款金额，金额为最小货币单位。 | 补偿提案需要绑定订单/支付/币种和计算依据；金额校验必须在执行事务中再次进行，不能只相信 Agent 提案。 | [Stripe Create a refund](https://docs.stripe.com/api/refunds/create) |
| 原交易与冲销记录 | ERPNext 的 credit note 链接原销售发票，金额可小于或等于原交易；sales return 使用关联的反向单据，并明确以 credit note 保留原发票审计轨迹。 | 补偿/冲销不应覆写原交易；应通过关联的新记录表达原因、金额、审批与执行结果。 | [ERPNext Credit Note](https://docs.frappe.io/erpnext/credit-note)、[ERPNext Sales Return](https://docs.frappe.io/erpnext/sales-return) |
| 多级审批 | ERPNext Workflow 支持按角色、条件和状态配置多级 approve/reject 转换。 | 补偿审批层级可由金额/风险策略驱动，但是否多级、阈值和角色仍需业务确认。 | [ERPNext Workflows](https://docs.frappe.io/erpnext/workflows) |
| 补偿执行状态 | Stripe 退款只能回原支付方式；可能 pending、failed、canceled，且提供创建、更新、失败等事件。 | `APPROVED` 不能等同于 `SUCCEEDED`；需要记录外部执行 ID、最终状态、失败原因和对账/补救路径。 | [Stripe Refunds](https://docs.stripe.com/refunds?dashboard-or-api=api) |
| 审批职责分离 | GitHub 受保护环境支持 required reviewers，并可选禁止发起人自审；审批前任务不能取得环境 secrets。 | 高额度/高风险补偿可考虑禁止提案人自批和延迟释放执行凭据；这只是可选控制，不是所有补偿的必然规则。 | [GitHub Deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments) |
| 幂等执行 | Stripe 的幂等请求保存首次执行结果；相同键重试返回相同结果，并对参数不一致报错。LangGraph 要求可能重执行的 API 调用具备幂等性。 | 可把“一次补偿执行意图”绑定一个业务幂等键和规范化参数摘要，并在 Spring 数据库施加唯一约束；具体键生命周期仍待决定。 | [Stripe Idempotent requests](https://docs.stripe.com/api/idempotent_requests)、[LangGraph Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api) |
| LangGraph 持久化/恢复 | checkpointer 在步骤保存 checkpoint，并按 thread 组织；`thread_id` 是加载/恢复 checkpoint 的标识；持久化支持 HITL、故障恢复和历史状态。 | `thread_id` 应仅作运行游标，与用户身份、ticket ID、approval ID 分列；业务 API 每次调用仍按当前主体鉴权。 | [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) |
| interrupt / HITL | interrupt 保存图状态并等待外部输入；恢复必须使用同一 thread；节点从头重跑，interrupt 前副作用需幂等，官方建议副作用放在 interrupt 后或拆为单独节点。 | 审批记录应先由确定性业务接口落库，再用其不可歧义的决定恢复图；resume payload 本身不能充当授权证据。 | [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) |
| 流式呈现 | LangGraph 可流式输出状态、消息及子图事件，也能在 interrupt 后继续流。 | UI 应把流当作可重放/可去重的运行投影；工单、审批和退款最终状态仍从业务查询接口读取。事件 envelope、序号与重连方式待设计。 | [LangGraph Event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming) |
| Spring 能力边界 | Spring Security 支持请求级及方法级授权；Spring Framework 支持声明式本地事务。官方明确事务上下文通常不跨远程调用传播。 | Spring 是承载工单/审批/补偿真值和写操作门禁的强候选；跨 Spring/LangGraph 应采用显式命令、幂等和最终一致性，而非假设分布式原子事务。 | [Spring Method Security](https://docs.spring.io/spring-security/reference/servlet/authorization/method-security.html)、[Spring Transactions](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative.html) |
| 可靠发布 | Spring Modulith 的 event publication registry 可在原业务事务内记录待发布事件，保留失败/未完成发布并支持重新提交；官方同时指出普通异步事务监听器在失败时可能丢事件。 | 若审批落库与恢复 LangGraph 不能同步原子完成，可将 transactional outbox/event publication 作为候选，而不是把远程调用包进本地事务。 | [Spring Modulith Events](https://docs.spring.io/spring-modulith/reference/events.html) |

## 1. 成熟客服系统透露出的领域约束

### 1.1 直接证据

- Frappe 的 Ticket 文档把工单描述为用于管理和跟踪客户请求的数字记录。创建时会获得默认状态、优先级、SLA 和类型；调查页同时展示客户信息、首次响应 ETA 和解决 ETA。[来源](https://docs.frappe.io/helpdesk/ticket)
- Frappe 的解决路径允许客服标记 resolved，客户满意后标记 closed 并反馈；客户继续回复可以重开。需要时可改派客服或升级团队。[来源](https://docs.frappe.io/helpdesk/ticket)
- Frappe SLA 将首次响应与解决时间按优先级配置，并将“履约状态”“暂停状态”、工作时间、节假日和条件匹配作为计时输入。[来源](https://docs.frappe.io/helpdesk/service-level-agreement)
- Zammad 将一项客户问题下的每次往来称为 article，并把 owner、group、priority、state 作为工单元数据。[来源](https://user-docs.zammad.org/en/7.0/basics/ticket-basics.html)
- Zammad history 提供工单创建以来的完整更新列表，包含谁在何时做了什么；其 UI 还提示同时查看/编辑同一工单的客服，以减少冲突和矛盾回复。[来源](https://user-docs.zammad.org/en/latest/basics/work-with-tickets.html)
- Zammad SLA 的 first-response 计时从创建开始，移动 group 不会重置；部分 pending/closed 状态忽略 SLA，重新打开时会基于原年龄立即升级。[来源](https://admin-docs.zammad.org/en/latest/manage/slas.html)

### 1.2 推论与待验证假设

- **推论：** ticket、conversation/article、internal note、audit event、agent run 应是可区分的概念。否则客户消息、内部调查和系统审计会混在一起，难以正确授权与回放。
- **推论：** 工单状态机和 SLA 时钟必须由确定性代码执行。Agent 可以建议分类、优先级或处理动作，但每次建议都需要经过明确业务命令和校验。
- **待决定：** 客户回复是否总是重开；resolved 与 closed 是否都存在；等待客户、等待第三方、等待审批分别是否暂停 SLA；重开后 SLA 是延续、重置还是新建周期。
- **待决定：** 分派目标是 owner、team、queue 还是三者组合；自动分配冲突时采用轮询、负载、技能标签还是人工领取。

## 2. 补偿审批：可确认的不变量与候选状态

### 2.1 直接证据

- Stripe 退款要求关联原支付对象，金额必须为正的最小货币单位，且不能超过剩余未退款金额；同一支付允许多次部分退款直到额度耗尽。[来源](https://docs.stripe.com/api/refunds/create)
- 退款通常返回原支付方式，不能任意改到另一张卡或银行账户；外部处理可能 pending、failed 或 canceled，并通过 webhook/event 更新。[来源](https://docs.stripe.com/refunds?dashboard-or-api=api)
- Stripe 的幂等键用于安全重试。首次请求开始执行后会保存结果；相同键与相同参数重试复用结果，参数不一致会报错。[来源](https://docs.stripe.com/api/idempotent_requests)
- GitHub 的受保护环境可要求指定 reviewer，并可选禁止发起者自审；审批通过前，等待中的 job 不可访问该环境的 secrets。[来源](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- ERPNext Workflow 支持由角色、条件和状态控制的多级 approve/reject 转换；其 credit note/sales return 将冲销记录关联到原销售发票，支持部分金额，并强调用关联反向单据保留原交易审计轨迹。[Workflow](https://docs.frappe.io/erpnext/workflows) / [Credit Note](https://docs.frappe.io/erpnext/credit-note) / [Sales Return](https://docs.frappe.io/erpnext/sales-return)

### 2.2 候选不变量（均为推论，不是已确认需求）

1. **对象约束：** 每个补偿提案绑定明确 ticket、customer、order/payment、currency 和 policy version。
2. **额度约束：** `requestedAmount > 0`，且执行时的累计成功/在途补偿加本次金额不超过可补偿余额。是否把 `pending` 占用额度必须业务确认。
3. **提案快照：** 审批针对不可变的金额、方式、原因、证据和政策版本；任一关键字段变化应形成新 revision，而不是静默修改已批准记录。
4. **职责分离：** 对达到风险阈值的提案，可要求 approver 与 proposer 不同；阈值、角色和是否允许管理员 bypass 都是待决策略。
5. **授权时效：** 执行前重新校验审批未过期、工单/订单版本未变化、支付仍可退以及当前操作者/服务凭据仍有权限。
6. **至多一次业务意图：** 每次执行意图有稳定 idempotency key；同键必须绑定同一参数摘要。网络超时后先查询/重试同一意图，不创建第二笔补偿。
7. **决定与结果分离：** `APPROVED` 只表示授权；外部执行可能 `PENDING`、`SUCCEEDED`、`FAILED`、`CANCELED`，并需要外部 ID 和状态事件对账。
8. **审计追加：** 提案、证据摘要、规则计算、审批人/时间/意见、执行请求、外部响应与人工更正都应留下不可静默覆盖的历史事件。

### 2.3 仅供 wayfinding 比较的候选状态词汇

```text
PROPOSED -> PENDING_APPROVAL -> APPROVED | REJECTED | EXPIRED
APPROVED -> EXECUTION_PENDING -> SUCCEEDED | FAILED | CANCELED
```

这不是推荐最终状态机。仍需决定：修改提案是回到 `PROPOSED` 还是创建 revision；是否存在无需人工审批的低额自动补偿；外部 `pending` 多久后升级；失败后是重试同一 execution 还是创建 replacement execution。

## 3. LangGraph：持久化、HITL、流式与恢复边界

### 3.1 直接证据

- 编译图时配置 checkpointer 后，LangGraph 在执行步骤保存 checkpoint，并按 thread 组织；持久化支撑 HITL、memory、time travel 与容错恢复。[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- `thread_id` 是 checkpointer 保存和检索 checkpoint 的键；没有它无法在 interrupt 后恢复。[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- interrupt 会持久化当前图状态并等待外部输入；恢复时使用同一 thread 和 `Command(resume=...)`。[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- 恢复不是从 Python 函数的具体代码行继续，而是从发生 interrupt 的节点开头重新执行。官方因此要求 interrupt 前副作用幂等，最好放到 interrupt 之后或独立节点。[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- Functional API 要求将 API 调用放入可 checkpoint 的 task，并设计成幂等，以应对失败或恢复时重执行。[Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)
- 流式 API 可输出完整/增量状态、消息及子图投影，并在 interrupt 后恢复流。[Event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)

### 3.2 推论：恢复安全需要两层保证

LangGraph checkpoint 可以减少已经完成的纯计算重复，但**不能替代外部业务系统的幂等性**。候选做法是：图节点保存业务 operation ID；Spring API 以 operation ID + 参数摘要执行原子“查重/校验/写入”；LangGraph 无论因 interrupt、进程崩溃或网络超时重调，都取得同一结果。该做法需要通过“响应丢失后重复 resume”和“同键不同参数”集成测试验证。

### 3.3 推论：流不是事实源

token、node start/end、tool progress 和 interrupt payload 适合驱动 React 时间线，但客户端可能断线、重连或收到重复事件。架构设计时应另行确定事件 ID、顺序、保留期、重放和去重语义；页面最终显示的 ticket、approval 和 compensation 状态应可通过业务查询重新校准。

### 3.4 版本风险

当前 LangGraph 文档同时存在不同代际的流式/输出示例（例如 interrupt 页面展示 v1/v2，event streaming 页面展示较新的接口）。在锁定依赖版本前，不宜直接把文档某个 chunk 结构固化为跨服务公共协议；应先选版本并做一个最小 pause/resume/stream spike。

## 4. Spring 与 LangGraph 的安全职责边界（候选，不是决策）

| 能力 | Spring 持有的理由 | LangGraph 持有的理由 | 尚待决定 |
|---|---|---|---|
| 身份、角色、资源授权 | Spring Security 支持请求级与方法级细粒度授权；业务写入可在服务层统一复核。 | 图可携带调用上下文，但 `thread_id` 只具有恢复语义。 | 浏览器是否只调用 Spring BFF；服务间身份采用何种 token/mTLS。 |
| ticket/SLA/assignment 真值 | 这些是需要事务、约束、并发控制和审计的确定性业务状态。 | 图可读取快照、提出分类/改派建议。 | 哪些建议允许自动接受；如何处理版本冲突。 |
| 补偿提案、审批和执行 | 金额、权限、额度、幂等和外部支付 ID 必须在可信边界强制。 | 图适合收集证据、解释政策、形成提案并在等待决定时暂停。 | 低额自动化阈值、双人审批、过期规则和失败补救。 |
| 调查计划和工具路由 | Spring 可暴露窄的、已授权的查询/命令 API。 | LangGraph 面向长运行、有状态、多步和 HITL 编排。 | 使用固定图、tool-calling loop 或混合图；最大步数与取消语义。 |
| 运行 checkpoint | Spring 只需保存业务关联键和运行摘要。 | checkpoint 是 LangGraph 原生恢复机制。 | checkpointer 产品/数据库、保留期、加密和租户隔离。 |
| 业务审计 vs Agent trace | Spring 审计回答“谁对何业务对象执行了什么决定/写入”。 | Agent trace 回答“图经过哪些节点、模型和工具”。 | 哪些 trace 字段可进入长期审计；PII、提示词和工具结果如何脱敏。 |

**直接证据：** Spring Security 支持基于方法参数和返回值的授权；Spring 的声明式事务可在方法级配置，但官方指出事务上下文通常不跨远程调用传播。[Method Security](https://docs.spring.io/spring-security/reference/servlet/authorization/method-security.html) / [Declarative Transactions](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative.html)

**推论：** 如果 Spring 与 LangGraph 分进程部署，就不应设计一个跨二者的数据库事务。更可验证的候选方式是：Spring 原子提交业务状态；跨边界命令使用版本号和幂等键；失败后由状态查询与重试收敛。是否采用 outbox、队列或同步 HTTP 仍需 wayfinding 比较。

Spring Modulith 的官方事件文档提供了进一步证据：event publication registry 可把事件发布记录与原业务事务一起持久化，保留未完成发布并支持重新提交；文档也警告普通异步事务监听器失败时可能丢失事件。[来源](https://docs.spring.io/spring-modulith/reference/events.html) 因此 transactional outbox/event publication 是“审批已提交但恢复 Agent 失败”问题的候选解法，但是否引入 Spring Modulith、消息队列或自建 outbox 仍未决定。

## 5. 许可证影响

| 项目 | 仓库标注许可证 | 对本项目的含义 |
|---|---|---|
| [Frappe Helpdesk](https://github.com/frappe/helpdesk) | AGPL-3.0 | 可研究功能、术语和交互；复制、修改、组合或网络部署其代码前必须评估 AGPL 义务。 |
| [Zammad](https://github.com/zammad/zammad) | AGPL-3.0 | 同上。不要把“公开仓库”误解为可无条件复制到任意许可证项目。 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | MIT | 宽松许可，但仍需保留许可证/版权声明并核对实际采用包及其传递依赖。 |
| [React](https://github.com/facebook/react/blob/master/LICENSE) | MIT | 宽松许可；分发时遵守版权与许可证通知要求。 |
| [Spring Framework](https://github.com/spring-projects/spring-framework) | Apache-2.0 | 宽松许可；遵守 NOTICE/许可证及专利条款，并分别核对项目实际依赖。 |

AGPL 第 13 节规定：若修改后的 AGPL 程序支持用户通过网络远程交互，应向这些用户显著提供获取相应源代码的机会。[GNU AGPL-3.0 正文](https://www.gnu.org/licenses/agpl-3.0.en.html) 这不是法律意见；“仅借鉴行为”“复制片段”“独立服务调用”“修改后托管”之间的边界不能由本文替代法律审查。

**当前最保守的研究结论：** 把 Frappe/Zammad 当作产品行为与领域问题清单，不复制其源码、样式资源或独有文本；如果未来决定 fork、嵌入或移植代码，先记录许可证决策。

## 6. 进入 wayfinding 前必须回答的问题

### 领域与策略

1. 工单的最小生命周期是什么？谁有权 resolve、close、reopen？客户回复是否自动重开？
2. SLA 的首次响应/解决计时、暂停状态、工作日历、重开规则和升级动作分别是什么？
3. “补偿”只包含原路退款，还是还包含优惠券、余额、积分、换货或人工转账？不同方式的不变量不同。
4. 哪些订单/支付事实是模拟数据，哪些会调用真实沙箱 API？演示是否严格禁止真实资金动作？
5. 补偿额度由静态政策、客户等级、事故影响还是人工裁量决定？Agent 只能建议，还是允许低风险自动执行？
6. 是否禁止提案人自批？是否按金额/风险要求一人或多人审批？审批是否过期？

### 一致性与恢复

7. ticket、approval、execution、agent thread 和 trace 的稳定关联键分别是什么？
8. 同一工单可否并发运行多个调查？两个提案竞争同一可补偿余额时如何防止超额？
9. Spring 提交审批后恢复图失败怎么办；图恢复后调用执行接口超时怎么办；谁负责重试与对账？
10. UI 事件需要何种顺序、重放、去重、断线恢复和保留期保证？

### 权限与数据

11. 客户、客服、组长、审批人、审计员、管理员各自能看到哪些 ticket notes、证据、知识文章和补偿字段？
12. 外部订单、物流、支付和知识库工具如何做最小权限、租户隔离、字段脱敏和速率限制？
13. 哪些 Agent trace 可以长期保存？是否包含客户 PII、支付信息、内部政策或模型提示词？

### 技术与许可证

14. LangGraph 采用哪个具体版本与部署方式？持久 checkpointer、interrupt 和 streaming 的最小验证 spike 验收标准是什么？
15. React 是直连 LangGraph 还是只连 Spring BFF？两种方式的鉴权、流代理、故障定位和开发成本如何比较？
16. 是否完全不复制 Frappe/Zammad 代码？如果要复用，项目许可证和源代码提供方式是否接受 AGPL 要求？

## 7. 建议的下一步证据产物（不代表选型）

1. 一页领域词汇表：Ticket、Conversation/Article、Internal Note、SLA Clock、Investigation、Compensation Proposal、Approval、Execution、Agent Run。
2. 两到三个候选工单/补偿状态机及不变量对比，每个都包含并发、重开、过期和失败恢复情景。
3. 一个最小 LangGraph spike：持久 checkpoint → interrupt → 进程重启 → 同 thread resume → 模拟业务 API 响应丢失 → 幂等重试，记录真实结果。
4. 两种前后端边界的 sequence diagram 与威胁模型：React→Spring→LangGraph，以及 React→LangGraph + Spring tools；明确授权发生点。
5. 许可证决策记录：只研究、不复制；或接受 AGPL 并列出履约方式。

## 8. 主要一手资料索引

- Frappe Helpdesk：[Ticket](https://docs.frappe.io/helpdesk/ticket)、[SLA](https://docs.frappe.io/helpdesk/service-level-agreement)、[Customers & Contacts](https://docs.frappe.io/helpdesk/customers-contacts)、[Knowledge Base](https://docs.frappe.io/helpdesk/lesson-4-knowledge-base)、[GitHub](https://github.com/frappe/helpdesk)
- Zammad：[Ticket Basics](https://user-docs.zammad.org/en/7.0/basics/ticket-basics.html)、[Work with Tickets / History](https://user-docs.zammad.org/en/latest/basics/work-with-tickets.html)、[SLA](https://admin-docs.zammad.org/en/latest/manage/slas.html)、[Roles](https://admin-docs.zammad.org/en/latest/manage/roles/)、[Knowledge Base](https://admin-docs.zammad.org/en/latest/manage/knowledge-base.html)、[GitHub](https://github.com/zammad/zammad)
- LangGraph：[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)、[Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)、[Event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)
- Spring：[Method Security](https://docs.spring.io/spring-security/reference/servlet/authorization/method-security.html)、[Transaction Management](https://docs.spring.io/spring-framework/reference/data-access/transaction.html)、[Declarative Transactions](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative.html)
- 补偿/审批先例：[ERPNext Workflows](https://docs.frappe.io/erpnext/workflows)、[ERPNext Credit Note](https://docs.frappe.io/erpnext/credit-note)、[ERPNext Sales Return](https://docs.frappe.io/erpnext/sales-return)、[Stripe Create Refund](https://docs.stripe.com/api/refunds/create)、[Stripe Refund Lifecycle](https://docs.stripe.com/refunds?dashboard-or-api=api)、[Stripe Idempotency](https://docs.stripe.com/api/idempotent_requests)、[GitHub Protected Environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- Spring 可靠发布：[Spring Modulith Event Publication Registry](https://docs.spring.io/spring-modulith/reference/events.html)
- 许可证：[GNU AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.en.html)、[React MIT License](https://github.com/facebook/react/blob/master/LICENSE)、[Spring Framework](https://github.com/spring-projects/spring-framework)、[LangGraph](https://github.com/langchain-ai/langgraph)

## 9. 验证范围与限制

- 已在 2026-08-08 通过网页核对上述官方文档/仓库页面；引用事实均来自一手来源，不使用博客作为依据。
- 未克隆、构建或运行 Frappe Helpdesk、Zammad、ERPNext、LangGraph 示例、Spring 示例或 Stripe 集成；因此本文验证的是**文档与仓库声明**，不是运行时行为或兼容性。
- 未逐行审计 Frappe/Zammad 源码，未确认它们所有边缘状态、数据库约束、并发行为和历史版本迁移。
- 未选择 LangGraph、Spring Boot、React、Python 或数据库的具体版本；文档 API 可能继续变化，尤其是 streaming 输出形态。
- Stripe 与 GitHub 只提供可迁移的退款/审批控制先例，不代表本项目必须采用 Stripe、GitHub 式 reviewer 或相同状态名。
- 许可证部分是工程风险提示，不构成法律意见；实际代码复用、组合和部署方式需按最终方案复核。
- 本文没有确认任何架构、服务拆分、领域状态机、API、事件协议、数据库、认证方式、MVP 范围或测试矩阵为用户需求。
