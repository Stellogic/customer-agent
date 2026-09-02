# #169/#170 共用 Agent 检索接入：最小契约方案（拟议）

> 后续状态：已获明确授权并完成[独立模块聚焦验证](issue-169-focused-validation.md)，41 项测试通过。下文保留各静态阶段的历史 NOT_RUN 记录，真实集成和完整门禁仍未完成。

> 当前修订：以 #149/#169/#190 正式 `rag-layered-v2` 为准，详见[回答层承接](issue-169-rag-layered-v2.md)。本次更改共享解析状态，尚未执行验证；上述 41 项仅是 `575d10a` 的历史证据，不覆盖本次差异。旧固定 PR 源码与失败记录保留，但“检索空结果等于拒答”和“检索层判断可回答性”不再作为实施契约。

## 状态及结论

2026-08-31，基于最新 `origin/main` **c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472**，保留 #169 既有组件提交并合并该 main；没有重做 UI。
检索引擎仅只读参考 PR203 固定 SHA **3f3fb4c28676f846af65b1c59cb389359ed613d6**，不跟随浮动 PR 头部。
下文“现有”均有这两个 SHA 的源码依据；标为“拟议”的路径、方法、字段、失败码和存储用法均未接线、未获集成放行，不是现行 API。

建议采用**两个授权入口、一个检索适配**：客户 Agent 沿现有 ticket/generation 栅栏；HUMAN 辅助沿客服会话与当前 assignment 栅栏。两者在 Spring 内调用同一 #190 检索核心，由 #169 实现公共适配与引用校验。不要把内部知识页面 API 授予客户，也不要为 HUMAN 辅助复活 Agent generation。
前一阶段新增纯引用校验/投影及测试源码和本方案；本次追加共用 DTO/纯响应解析（见文末对齐记录）。无网络、SQL、模型、公共入口或迁移改动。#190 原生质量前置、串行验证窗口及协调放行要求不变。

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

以下是旧阶段原则讨论过、当前仍待落实的接缝需求，**不是已存在的方法**：由 #190 在 KnowledgeRetrievalService 提供接受可信授权范围的包内入口（此前提议名 `searchAuthorizedScopes(query, allowedScopes)`），原内部 search 保留身份/能力校验及 scope 选择后委派。#190 owner 本次明确目前只有内部 search，未承诺已实现包内入口；#169 不预写依赖不存在方法的适配。该入口只需覆盖权限/发布/版本/范围过滤、两路检索及 RRF Top-5，**不判断可回答性**。条目是供同次 DeepSeek 判断和回答的资料，不能直接当答案或已接受引用。新 Agent 可信入口无授权范围应拒绝；内部页面在固定修复 `0527552d250f6c2a819cff6365ad8870268f7761` 中也于编码/检索前拒绝显式未授权 scope（403），旧 200 空交集不是合法授权契约。不复制引擎，不让 Agent 指定索引 generation、模型 revision 或阈值。包内方法不会自动继承原 search 的事务。旧 CALIBRATED/评分、c5 及所有失败仅作为历史，不进入默认回答路径。

#169 拟新增同 knowledge 包的 `AgentKnowledgeRetrievalAdapter.java`：

- `searchCustomer(query)` 固定范围 CUSTOMER_PUBLIC，仅由已验证客户 Agent 工单授权的 Spring 入口调用。
- `searchSupport(principalId, query)` 复用 requireScopes(principalId)，只保留 INTERNAL/SUPPORT 交集，不能借审批角色扩大辅助范围；调用前后由 #170 验证当前领取关系。
- **已对齐、待实施的事务安排**：适配 public 方法 searchCustomer/searchSupport 经 Spring 代理开启只读 REPEATABLE_READ，覆盖共享核心检索及 canonical 元数据补读；原内部 search 的事务不变。外层编排必须**无事务**，前置授权事务先结束，检索事务结束后才进入接受结果事务；仅“不持业务锁”不够，因为默认 REQUIRED 会加入外层事务而忽略本地隔离级别。无需 REQUIRES_NEW/新租约/通用框架。不得用另一版本的标题或更新时间填补。[Spring REQUIRED 官方说明](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/tx-propagation.html)、[代理与自调用说明](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html)。
- 返回给 Agent 的受控条目拟为 `articleId, version, chunkId, title, updatedAt, applicability, startLine, endLine, snippet`。sourceFile、分数、候选和模型配置留在 #190 内部诊断；Agent 不需要它们。
- 拟议响应仍为 `schema=agent-knowledge-v1, indexGeneration, results`，这是 #169 自有受控投影而非 #190 内部响应。非空派生 CANDIDATES_AVAILABLE，空派生 NO_MATCH；二者只表达授权片段有无，不表达充分性、模型拒答或安全引用。#190 新版移除 policy，不能要求默认校准字段；revision 可作内部追溯元数据，不作为授权。

这不是增加第二个检索引擎。接缝实现仍归 #190 并等待其独立验证与协调窗口，#169 本轮不预写或挂载依赖该尚未落地方法的 Spring 适配类。

## 拟议接缝 B：Agent 如何调用，怎样撤销

客户通道建议在现有 AgentInvestigationController 中新增 `POST /knowledge/search`，沿用路径 ticketId/generationId，拟议 operation 为 SEARCH_KNOWLEDGE，沿用 Idempotency-Key；请求体仅 `{query}`（trim 后 1–200 字符）。范围由客户工具固定，不收身份、订单结果、全文对话、索引参数或任意 URL。模型只自主选择是否调用与精简检索问题；它不能选择权限范围。

实现时分三个步骤，不在慢检索/Embedding 期间持有工单业务锁：

1. 现有 Controller.requireScope 后，调用 JdbcAgentInvestigationService 的拟新增事务方法 `authorizeKnowledgeRequest`，内部复用 authorityLock/requireActiveGeneration，并读取该 generation/requestId 的既有回执；摘要包含 operation/query/实际 scopes。异参或 operation 复用返回 409。
2. 没有回执才调用公共适配；按接缝 A 的拟议安排，适配层事务覆盖共享检索和元数据补读，而非假定包内方法自动继承原 search 的事务。返回后进入拟新增事务方法 `acceptKnowledgeResult`，再次获取业务锁并校验最新 generation；撤权或转人工则拒绝结果，不能发布。并发同 key 时只保留首个一致回执，另一次返回该回执。
3. 在 agent_command_request.response_payload 存受控知识回执（indexGeneration、引用、必要受控片段/元数据），不存两路候选、分数或原始模型载荷；重放仍先检查当前授权及索引/版本可用性，过期则返回受控失败，用新请求身份重检索。无新增通用请求表。

以上新 service 方法需加入现有 AgentInvestigationService 接口，保留 private guard 在原类中复用，不复制一套 generation SQL，也不拿 capabilities 调用当授权凭证。具体事务入口必须通过 Spring 代理，不能靠同类自调用注解声称已分离事务。

HUMAN 通道由 #170 自有辅助请求入口验证 SUPPORT 会话、HUMAN、当前 ACTIVE assignment（包括 assignment id，防止撤回后重新领取同一人的旧辅助结果重新有效）。#170 保存稳定辅助请求与 assignment 绑定，不能往需要 generation 外键的 agent_command_request 塞假 UUID。辅助 worker 的知识调用须经 Spring 按该辅助请求重新解出 ticket/当前负责客服/允许范围；发起、取结果、返回浏览器时都复核。其路由和请求记录仍由 #170 决定，不在本方案冒称为已有接口。

#169 已新增独立 `agent/src/baseline_agent/knowledge_retrieval.py` 作为两通道唯一的 DTO/响应解析/HTTP错误归类代码，当前只接收状态码和已解码 JSON，不发请求或接收 URL/headers。未来认证与已授权上下文由各入口提供，不自建 retriever、模型或 provider 切换。客户侧选择动作及 graph 仍等待放行；#170 仅消费同一 DTO，不实现第二份检索解析。

## 拟议失败契约与输出规则

| 现有证据 | 拟议适配归类与消费者动作 |
| --- | --- |
| rag-layered-v2 results=[] | NO_MATCH，仅无匹配资料，不能记正常拒答；资料不足判断和说明/必要追问由同一次 DeepSeek 回答形成。不补写无来源规则，也不仅因此自动转人工。无需知识的业务回复仍只用 Spring 事实。 |
| 旧 PR203 CALIBRATION_REQUIRED | 新默认检索不依赖校准。若收到旧服务该错误，按 RETRIEVAL_UNAVAILABLE 失败，不重试校准、不当正常拒答；旧实验与 FAIL 不追改。#190 新检索质量与完整门禁仍为前置。 |
| PR203 KnowledgeRetrievalService：INDEX_STALE | INDEX_STALE；不使用旧缓存。 |
| PR203 KnowledgeEmbeddingGateway：MODEL_UNAVAILABLE | MODEL_UNAVAILABLE（这里特指 Embedding）；保留原码，不伪造独立“Embedding错误”实现。 |
| PR203 FUSION_UNAVAILABLE / RETRIEVAL_UNAVAILABLE、HTTP 超时/非预期载荷 | 对 Agent 归一 RETRIEVAL_UNAVAILABLE，内部保留受控诊断，不转发异常正文。 |
| 现有 generation 403；客服无当前 assignment；Agent 授权范围为空；显式未授权 scope | ACCESS_DENIED；不重试越权。客服返回授权资源的 404 语义由 #170 保留，不据此泄露工单存在。授权失败不能伪装无匹配或正常拒答；只有成功授权但无匹配才使用 200 空结果。 |
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
| KnowledgeCitationProjection.java、测试；AgentKnowledgeRetrievalAdapter.java；agent/.../knowledge_retrieval.py；客户来源 UI | #169；纯投影、共用 Python DTO/解析与各自测试源码已写，Spring adapter 仍待实施。 |
| KnowledgeRetrievalService.java 的包内共享方法，以及检索模型/编码/依赖/Compose/校准与质量 | #190；#169 只提出最小接缝，不修改、不复制实现。 |
| AgentInvestigationController/Service、JdbcAgentInvestigationService 的新增知识方法；客户 graph/动作选择/回复协议；CustomerPublicProjectionAppender/客户快照与 App.tsx | 拟议集成修改由 #169 单独承担，需协调开放共享文件窗口；本轮均不修改，不触碰 JdbcCompensationProposalStore 等 #165 补偿区域。 |
| HUMAN 辅助入口/请求绑定、当前领取校验、结果访问/撤权、composer/草稿发送衔接 | #170；引用共用适配，不委托 #169 修改其文件。 |
| 内部 shell/页面导航 | #193；本轮与本接入方案均不需要修改。 |

可执行顺序：①协调确认 #190 包内范围接缝与以上归属；②#190 质量 PASS、合入关票后读取正式接口；③#169 落地共用适配、customer 授权前后复核和引用回执，#170 对接自己的 assignment 请求；④#169 完成回复语义校验/投影持久化和版本协议再接 UI，双方补足真实故障与撤权测试；⑤按协调串行窗口验证、增量双 CR 与正式交付。
①的原则接缝已对齐，但尚无正式实现或真实集成许可；不能据此把未来接口当已上线 API 接到公共入口。

## 贡献与验证记录

本阶段贡献：沿现有 generation/assignment 两条权限链提出共享检索最小接缝，区分 indexGeneration 与业务 generation，复用知识模型实现纯引用结构校验与客户/客服白名单投影；保存测试源码。
不是检索引擎、上线集成、质量 PASS、prompt injection 防护完成或端到端授权证明。
**NOT_RUN**：测试、格式化/格式检查、lint、类型检查、构建、模型、评测、Docker/Compose、浏览器、测试锁、check.ps1。未合入、未关闭 Issue；CI 保持关闭。

静态双 CR（2026-08-31）：固定比较 `git diff --cached c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`，复审完整七文件 597 新增行（含旧 UI）；增量四文件 317 行。首轮 Standards/Spec 均指出同一 P2：包内检索方法不自动继承原 search 事务。已明确新增适配事务经 Spring 代理覆盖检索与元数据补读，再重审完整暂存差异，两轴均 **PASS，0 项未解决发现**。本段只补记审查结果；所有运行验证仍 NOT_RUN。

## 本次 #169/#170 消费者字段对齐与纯解析（2026-08-31）

由协调任务 `01a043aa-d724-7353-b6c5-9266277846d6` 限定静态授权，直接与 #170 任务 `01a053ab-74a9-72e3-aeb2-87bc6e09139f` 对齐；#190 接缝意见来自 owner 任务 `01a051b6-257f-7230-a04e-a2f6a112e921`。未因对齐增加测试/真实集成许可。

| 共用解析输入/输出 | 已收敛的静态契约，不代表已有 HTTP endpoint |
| --- | --- |
| `parse_knowledge_response(status_code, payload)` | 输入 HTTP 状态码与已解码 JSON；不执行 HTTP、JSON 解码、鉴权、重试、缓存或清屏。未来传输/JSON 解码异常由调用者归为 RETRIEVAL_UNAVAILABLE。 |
| 成功载荷 | 仅 HTTP 200；精确字段 schema=agent-knowledge-v1、indexGeneration（非负整数，非业务 generation UUID）、results（0–5 条最终结果）。不接受 knowledge-hybrid-v1、两路候选、policy 或多余载荷字段。 |
| 每条 results | 精确字段 articleId/version/chunkId/title/updatedAt/applicability/startLine/endLine/snippet。文本非空，updatedAt 是带时区 ISO 时间，scope 使用现有四范围词汇且非空，行号为正且 endLine≥startLine；范围是否获授权仍由 Spring 决定。 |
| Python DTO | frozen KnowledgeSource 使用对应 snake_case 属性；KnowledgeRetrievalResult(index_generation, sources)，集合复制成 tuple。本次 rag-layered-v2 将 status 从旧 AVAILABLE/NO_ANSWER 改为 CANDIDATES_AVAILABLE/NO_MATCH，仅表示片段有无。不把畸形响应降成空结果，也不把有片段当充分回答。 |
| HTTP 401/403/404；400；409 | 依次映射 ACCESS_DENIED、INVALID_QUERY、REQUEST_CONFLICT。权限优先于错误正文自称的 code。 |
| HTTP 503 | 仅保留 INDEX_STALE/MODEL_UNAVAILABLE；FUSION_UNAVAILABLE、旧 CALIBRATION_REQUIRED、其他码或未知失败一律 RETRIEVAL_UNAVAILABLE。不将实验评分/校准作为默认依赖。 |
| HTTP 422 | 仅保留 INVALID_KNOWLEDGE_CITATION/KNOWLEDGE_CONFLICT/UNSAFE_KNOWLEDGE；这些仍是消费者约定，未新增 Spring handler 或语义检测。 |
| 其他 HTTP 错误、畸形 200 | 抛 KnowledgeRetrievalFailure(RETRIEVAL_UNAVAILABLE)，不透传异常正文/原始 payload。 |

#170 确认现 UI 的 title/version/articleId/chunkId/snippet/applicability 是共用条目的显示子集，后续由其增加 updatedAt/startLine/endLine。Agent 内 DTO 不是浏览器授权结果，#170 不复制 Python DTO/HTTP解析。
HUMAN 自有绑定为 ticketId + assignmentId + requestId + assistanceType（服务端再保存输入摘要）；principal 从会话取得。新类型/输入用新 requestId，重试同身份同参数，异参 409 REQUEST_CONFLICT。发起/取结果/返回前均复核 SUPPORT/HUMAN/ACTIVE assignment；这些仍由 #170 在后续真正入口实现。
普通完成结果按 assignment + requestId + assistanceType 匹配，旧 request 的普通结果忽略。ACCESS_DENIED（含受保护资源的 403/404）按当前 session/ticket/assignment 匹配，**不按 requestId**：同 assignment 的旧请求拒绝仍清理当前 assignment 的授权内容/草稿并停止重试，新请求不能掩盖责任失效；只有旧 assignment 的拒绝不得清理新的 assignment。其余知识失败保留人工编辑；辅助生成模型失败与 MODEL_UNAVAILABLE（Embedding）分开。#170 本轮仅实现自有客户端绑定状态，路由/请求持久化/真实授权仍后置。

消费者测试源码在 `agent/tests/test_knowledge_retrieval.py`：双方 scope 共用 DTO、规范结果与空结果、私有字段/内部候选拒绝、引用字段约束、错误类别及不透传原始载荷。fixture 仅在测试文件，不向任何 endpoint 发请求。所有验证 **NOT_RUN**；该解析器不能宣称已经完成注入防护、当前版本复核或回复依据校验。

本次静态双 CR：固定比较 `git diff --cached 6e343df0367cd81382d71cb327fc07eddb0a512a`（三文件，317 新增／7 删除），Standards **PASS，0 项发现**；Spec **PASS，0 项发现**。本段仅补记结果，未改被审阅的解析实现；测试及全部运行验证仍 NOT_RUN。
