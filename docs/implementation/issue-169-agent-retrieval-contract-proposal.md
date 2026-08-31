# #169/#170 共用 Agent 检索接入：最小契约方案（拟议）

## 状态及结论

2026-08-31，基于最新 `origin/main` **c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472**，保留 #169 既有组件提交并合并该 main；没有重做 UI。
检索引擎仅只读参考 PR203 固定 SHA **3f3fb4c28676f846af65b1c59cb389359ed613d6**，不跟随浮动 PR 头部。
下文“现有”均有这两个 SHA 的源码依据；标为“拟议”的路径、方法、字段、失败码和存储用法均未接线、未获集成放行，不是现行 API。

建议采用**两个授权入口、一个检索适配**：客户 Agent 沿现有 ticket/generation 栅栏；HUMAN 辅助沿客服会话与当前 assignment 栅栏。两者在 Spring 内调用同一 #190 检索核心，由 #169 实现公共适配与引用校验。不要把内部知识页面 API 授予客户，也不要为 HUMAN 辅助复活 Agent generation。
本轮新增的只有纯引用校验/投影及测试源码和本方案；无网络、SQL、模型、公共入口或迁移改动。#190 原生质量前置、串行验证窗口及协调放行要求不变。

## 现有契约：明确能复用什么

以下路径相对仓库根目录，未标 PR203 的均取上述 main SHA。

| 源码 | 已有行为和直接影响 |
| --- | --- |
| `backend/src/main/java/com/stellogic/customeragent/investigation/AgentInvestigationController.java` 的 requireScope | `/internal/agent/tickets/{ticketId}/generations/{generationId}`；服务 Bearer、X-Agent-Generation-Id 与路径一致、X-Agent-Operation 必须匹配。头部只校验调用范围，不代替数据库工单授权。 |
| 同目录 `JdbcAgentInvestigationService.java` 的 requireActiveGeneration / invoke | generation 属于工单、ACTIVE 且为最新一代，工单 AGENT/INVESTIGATING 且无 customer_human_preference；失败 403。invoke 先 TicketAuthorityLock，再当前代次和稳定请求身份，后执行工具。该 guard 是 private，不能假称适配模块已可直接调用。 |
| `reliability/TicketAuthorityLock.java`、`reliability/StableParameterDigest.java`（同 Java 包根） | 已有工单业务锁与参数摘要，无需新造权限令牌、租约或审批框架。业务锁不是本轮可申请的测试锁；本轮二者均不运行。 |
| `backend/src/main/resources/db/migration/V3__agent_no_compensation_resolution.sql` 的 agent_command_request；上述 invoke | 主键 generation_id/request_id，operation、parameter_digest、response_payload 已存在。当前工具重复请求返回 409，仅记录 capability，不存知识结果；“缓存知识回执”是下面的新设计，不能说已经支持。 |
| `queue/SupportWorkbenchProjectionService.java` 的 details/currentTicketScope（同 Java 包根） | 当前 support_assignment 必须 ACTIVE 且 support_id 匹配，工单未 RESOLVED/CLOSED；currentTicketScope 锁 t/a。details 本身不要求 HUMAN，也不只读当前代事实；#170 必须另加 HUMAN 条件并挑选可用事实。辅助不能拿历史 generation 当调用权。 |
| `identity/HumanSecurityConfiguration.java`、`queue/SupportWorkbenchController.java` | SUPPORT 会话角色、CSRF；principal 来自 Authentication，不能信任请求体 supportId。上述 service 的 requireSupportPrincipal 只检查非空，不是角色认证。 |
| `knowledge/KnowledgeCatalogModels.java`、`V35__versioned_knowledge_catalog.sql` | article 有 articleId/version/title/updatedAt/applicability/publicationStatus/current/contentHash；chunk 有 chunkId/articleId/version/sourceFile/startLine/endLine/applicability/content。元数据可直接在 Spring 读现有表，无需调用内部目录 HTTP 或新增知识库。 |
| PR203 `knowledge/KnowledgeRetrievalService.java` | search(principal,query,scope) 先 requireScopes；发布/当前版本、条目及片段范围、索引 generation/revision/content_hash 过滤后检索。结果采用 Top-5；低阈值/无匹配均可能 results=[]。不能将候选列表当结果。 |
| PR203 `knowledge/KnowledgeAccessPolicy.java` | 仅 INTERNAL + KNOWLEDGE_READ_ACCESS，范围 INTERNAL，按角色添加 SUPPORT/APPROVER；不授予 CUSTOMER_PUBLIC。客户范围必须由新工单工具边界赋予，不能改这个员工目录策略来绕过。 |
| PR203 `knowledge/KnowledgeRetrievalModels.java` | hit 缺 updatedAt；响应 generation 是**知识索引代次**，不是 agent_processing_generation 的 UUID。对外适配应命名 indexGeneration，避免混用。 |
| `investigation/CustomerReplySafetyPolicy.java`、AgentInvestigationController.parseConclusion；`agent/src/baseline_agent/customer_communication_model.py` | 当前 customer-reply-v1 字段精确校验，没有知识引用。现有业务事实、金额/承诺校验必须保留；仅新增 metadata 不会自动完成有依据自然回复。 |
| `agent/src/baseline_agent/investigation_action_loop.py` | 动作枚举/参数名单封闭，且 result 会合并进 facts。知识接入须独立放 knowledge 上下文，不能把 snippet 当物流、支付、补偿事实合并或用于满足业务证据充分性。 |

## 拟议接缝 A：授权后的检索核心，#190 只需一个接缝

请协调把以下最小变更交给 #190 owner 评估，#169 本轮不改其文件：在 KnowledgeRetrievalService 内，将现有“按 principal 求 scopes”之后的检索代码提取成**包内** `searchAuthorizedScopes(query, allowedScopes)`；原内部 search 仍先 requireScopes 并调它。该方法只接收服务端求出的非空范围，不增加 HTTP 路由、不复制 SQL/编码/阈值/融合，也不让 Agent 指定索引 generation、模型 revision 或 threshold。现有事务注解只在 search 上，新包内方法不会自动继承该事务。

#169 拟新增同 knowledge 包的 `AgentKnowledgeRetrievalAdapter.java`：

- `searchCustomer(query)` 固定范围 CUSTOMER_PUBLIC，仅由已验证客户 Agent 工单授权的 Spring 入口调用。
- `searchSupport(principalId, query)` 复用 requireScopes(principalId)，只保留 INTERNAL/SUPPORT 交集，不能借审批角色扩大辅助范围；调用前后由 #170 验证当前领取关系。
- **新增事务安排（拟议）**：适配的 searchCustomer/searchSupport 经 Spring 代理开启只读 REPEATABLE_READ 事务，覆盖包内共享核心检索及后续元数据补读；原内部 search 的事务仍保持不变。然后从 #190 的 **results** 提取命中引用，在该事务同一知识快照内按 articleId/version/chunkId 读取 title/updated_at 和 canonical chunk，保持发布/当前/范围检查。不得用另一个版本的标题或更新时间填补；不得在调用适配的外层已持有工单业务锁。
- 返回给 Agent 的受控条目拟为 `articleId, version, chunkId, title, updatedAt, applicability, startLine, endLine, snippet`。sourceFile、分数、候选和模型配置留在 #190 内部诊断；Agent 不需要它们。
- 拟议响应 `schema=agent-knowledge-v1, indexGeneration, results`；空结果就是 NO_ANSWER，不另外猜测“低分”或“无语料”。quality policy/revision 可在内部回执留存，但不把它们作为权限。

这不是增加第二个检索引擎。若 #190 不采用该方法名，可以只调整包内接缝名；明确的要求是**共享原检索核心并保持检索前过滤**。本轮不预写依赖该未接受方法的适配类。

## 拟议接缝 B：Agent 如何调用，怎样撤销

客户通道建议在现有 AgentInvestigationController 中新增 `POST /knowledge/search`，沿用路径 ticketId/generationId，拟议 operation 为 SEARCH_KNOWLEDGE，沿用 Idempotency-Key；请求体仅 `{query}`（trim 后 1–200 字符）。范围由客户工具固定，不收身份、订单结果、全文对话、索引参数或任意 URL。模型只自主选择是否调用与精简检索问题；它不能选择权限范围。

实现时分三个步骤，不在慢检索/Embedding 期间持有工单业务锁：

1. 现有 Controller.requireScope 后，调用 JdbcAgentInvestigationService 的拟新增事务方法 `authorizeKnowledgeRequest`，内部复用 authorityLock/requireActiveGeneration，并读取该 generation/requestId 的既有回执；摘要包含 operation/query/实际 scopes。异参或 operation 复用返回 409。
2. 没有回执才调用公共适配；按接缝 A 的拟议安排，适配层事务覆盖共享检索和元数据补读，而非假定包内方法自动继承原 search 的事务。返回后进入拟新增事务方法 `acceptKnowledgeResult`，再次获取业务锁并校验最新 generation；撤权或转人工则拒绝结果，不能发布。并发同 key 时只保留首个一致回执，另一次返回该回执。
3. 在 agent_command_request.response_payload 存受控知识回执（indexGeneration、引用、必要受控片段/元数据），不存两路候选、分数或原始模型载荷；重放仍先检查当前授权及索引/版本可用性，过期则返回受控失败，用新请求身份重检索。无新增通用请求表。

以上新 service 方法需加入现有 AgentInvestigationService 接口，保留 private guard 在原类中复用，不复制一套 generation SQL，也不拿 capabilities 调用当授权凭证。具体事务入口必须通过 Spring 代理，不能靠同类自调用注解声称已分离事务。

HUMAN 通道由 #170 自有辅助请求入口验证 SUPPORT 会话、HUMAN、当前 ACTIVE assignment（包括 assignment id，防止撤回后重新领取同一人的旧辅助结果重新有效）。#170 保存稳定辅助请求与 assignment 绑定，不能往需要 generation 外键的 agent_command_request 塞假 UUID。辅助 worker 的知识调用须经 Spring 按该辅助请求重新解出 ticket/当前负责客服/允许范围；发起、取结果、返回浏览器时都复核。其路由和请求记录仍由 #170 决定，不在本方案冒称为已有接口。

#169 拟新增 `agent/src/baseline_agent/knowledge_retrieval.py` 作为两通道唯一的响应解析/HTTP错误归类代码；认证与已授权请求上下文由各入口传入，不接收模型给出的 URL/headers，不自建 retriever、模型或 provider 切换。客户侧选择动作的枚举及 graph 调度由 #169 在放行后接线；#170 仅调用同一适配，不实现第二份检索。

## 拟议失败契约与输出规则

| 现有证据 | 拟议适配归类与消费者动作 |
| --- | --- |
| PR203 results=[] | NO_ANSWER；不使用候选、不补写无来源规则。若只是无需规则的业务回复，仍只用 Spring 事实；需要知识才能回答时停下该知识答复。 |
| PR203 KnowledgeAnswerabilityPolicy：CALIBRATION_REQUIRED | 保留受控码并停止知识消费；不由 #169 调整门槛。#190 正式质量 PASS 是另一个必须满足的交付条件，配置 CALIBRATED 本身不是证明。 |
| PR203 KnowledgeRetrievalService：INDEX_STALE | INDEX_STALE；不使用旧缓存。 |
| PR203 KnowledgeEmbeddingGateway：MODEL_UNAVAILABLE | MODEL_UNAVAILABLE（这里特指 Embedding）；保留原码，不伪造独立“Embedding错误”实现。 |
| PR203 FUSION_UNAVAILABLE / RETRIEVAL_UNAVAILABLE、HTTP 超时/非预期载荷 | 对 Agent 归一 RETRIEVAL_UNAVAILABLE，内部保留受控诊断，不转发异常正文。 |
| 现有 generation 403；客服无当前 assignment；知识范围为空 | ACCESS_DENIED；不重试越权。客服返回授权资源的 404 语义由 #170 保留，不据此泄露工单存在。范围失败不能伪装 NO_ANSWER。 |
| 拟议引用身份/版本/片段/范围或检索回执不匹配 | INVALID_KNOWLEDGE_CITATION；不发布该知识答复/来源。纯模块抛 IllegalArgumentException，未来入口映射该码；本轮没有新 HTTP handler。 |
| 拟议知识与已核验事实冲突 / 注入或无依据规则结论 | KNOWLEDGE_CONFLICT / UNSAFE_KNOWLEDGE；记录受控事件与引用，不写入原始 prompt。客户只获得安全状态/人工处理提示；客服辅助失败不影响继续人工回复。 |

不新增无限重试。客户按已有动作预算和 ADR0008 的有限修正/转人工处理；#170 的模型失败与 Embedding 失败分开标识，但都不得把草稿自动发送。

## 拟议引用到回复的最后一段

1. Agent 只能提交引用身份 `retrievalRequestId + articleId/version/chunkId`，不能提交自称安全的 title/updatedAt/snippet。Spring 验证它确实出自当前授权请求的最终 results，再回读当前元数据做发布、版本、范围、索引校验。
2. 新增知识上下文是未受信的参考数据，与 authorizedInvestigation 分开；保留现有业务证据与资格/金额校验，不允许知识引用填补订单、物流、支付、补偿事实。知识冲突时保留事实并记录引用/受控冲突码，不把政策文字升级成订单结论。
3. 当前目录没有内容安全审批字段，当前回复校验也不证明任意中文规则结论都有依据。拟议在现有回复校验流程中增加规则句与引用的对应验证，拒绝带指令的知识段/标题及越权承诺；校验不能确定时不公开该知识答复。**该语义校验仍需 #169 在接线阶段实现和实际验证，不用发布状态或本文纯模块替代，也不新造审批系统/关键词防火墙。**
4. customer-reply-v1 是严格字段协议；拟议显式增加版本化知识引用分支（例如 customer-reply-v2），旧分支保持原校验，不放宽成任意字段。知识来源只在完整回复获 Spring 接受后绑定到公开消息；检索命中不能提前当作“本次回复依据”。
5. 流式 CONTENT_DELTA 也是公开边界：拟议知识回复在发送 delta 前完成相应安全校验；不能先泄露内容再在 COMPLETED 拒绝。验证方式未就绪时该分支只显示受控进度，完成校验后一次公开最终文本，不把事后拆字伪装模型流。原有无需知识的真实流不受影响。
6. 客户投影仅 title/updatedAt；客服投影允许 articleId/version/chunkId/title/updatedAt/有效 applicability/startLine/endLine/snippet，不含路径、候选、分数、prompt 或思维链。拟在现有 public_message 增加公开 sources 元数据存储并同步快照/事件 schema（迁移号到集成时决定，不预留）；只持久化已接受且脱敏的来源，断线从 Spring 快照恢复。内部检索回执不直接序列化到浏览器。

## 本轮已实现的独立纯模块

`backend/src/main/java/com/stellogic/customeragent/knowledge/KnowledgeCitationProjection.java` 与同路径测试类（src/test）属于 #169。
复用 main 的 KnowledgeArticleDetail/KnowledgeChunkCitation，不引用未合入 #190 类、不加 Spring bean 或路由。输入为服务端 canonical article、模型引用三元组及服务端允许范围；验证新回复只能用当前已发布版本和匹配片段，并要求条目/片段/授权范围三者有共同 scope。
客户输出只有标题/更新时间，客服输出规范字段且 applicability 为有效范围交集。错误直接失败，无备用知识、无内容改写；返回类型不携带原对象。

**能力限于结构校验和字段投影**：该模块不确认调用者身份、不执行检索、不证明引用出自某次检索、不查 indexGeneration、不检测 prompt injection、不识别自然语言事实冲突。调用方必须先完成以上管线，不能把客户方法里的 CUSTOMER_PUBLIC 常量当授权。模块包内可见，不从 HTTP 直接反序列化 article 或 allowedScopes。测试只覆盖字段白名单、版本/片段/范围条件与 canonical 数据来源，所有运行验证 NOT_RUN。

## 唯一文件归属与落实顺序

| 区域 | 唯一 owner / 本轮处理 |
| --- | --- |
| KnowledgeCitationProjection.java、测试；AgentKnowledgeRetrievalAdapter.java；agent/.../knowledge_retrieval.py；客户来源 UI | #169；本轮只实现前两项现有模型纯投影文件，其余路径拟议。 |
| KnowledgeRetrievalService.java 的包内共享方法，以及检索模型/编码/依赖/Compose/校准与质量 | #190；#169 只提出最小接缝，不修改、不复制实现。 |
| AgentInvestigationController/Service、JdbcAgentInvestigationService 的新增知识方法；客户 graph/动作选择/回复协议；CustomerPublicProjectionAppender/客户快照与 App.tsx | 拟议集成修改由 #169 单独承担，需协调开放共享文件窗口；本轮均不修改，不触碰 JdbcCompensationProposalStore 等 #165 补偿区域。 |
| HUMAN 辅助入口/请求绑定、当前领取校验、结果访问/撤权、composer/草稿发送衔接 | #170；引用共用适配，不委托 #169 修改其文件。 |
| 内部 shell/页面导航 | #193；本轮与本接入方案均不需要修改。 |

可执行顺序：①协调确认 #190 包内范围接缝与以上归属；②#190 质量 PASS、合入关票后读取正式接口；③#169 落地共用适配、customer 授权前后复核和引用回执，#170 对接自己的 assignment 请求；④#169 完成回复语义校验/投影持久化和版本协议再接 UI，双方补足真实故障与撤权测试；⑤按协调串行窗口验证、增量双 CR 与正式交付。
本轮无需等待①才能保存独立纯模块和具体方案；①未批准也不能把拟议接口当现有事实编码到公共入口。

## 贡献与验证记录

本阶段贡献：沿现有 generation/assignment 两条权限链提出共享检索最小接缝，区分 indexGeneration 与业务 generation，复用知识模型实现纯引用结构校验与客户/客服白名单投影；保存测试源码。
不是检索引擎、上线集成、质量 PASS、prompt injection 防护完成或端到端授权证明。
**NOT_RUN**：测试、格式化/格式检查、lint、类型检查、构建、模型、评测、Docker/Compose、浏览器、测试锁、check.ps1。未合入、未关闭 Issue；CI 保持关闭。

静态双 CR（2026-08-31）：固定比较 `git diff --cached c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`，复审完整七文件 597 新增行（含旧 UI）；增量四文件 317 行。首轮 Standards/Spec 均指出同一 P2：包内检索方法不自动继承原 search 事务。已明确新增适配事务经 Spring 代理覆盖检索与元数据补读，再重审完整暂存差异，两轴均 **PASS，0 项未解决发现**。本段只补记审查结果；所有运行验证仍 NOT_RUN。
