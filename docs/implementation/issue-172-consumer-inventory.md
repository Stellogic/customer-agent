# #172：旧契约消费者与历史读取盘点

## 范围与证据基准

- 状态：**仅静态准备，#172 未完成，不可据此删除或交付**。本次唯一产物是本文件；未修改业务、接口、共享脚本、测试源码或其他任务文件。
- 日期：2026-09-01。当前起点为远端 `main` `e34b60113a3bbcfe28a4fcd247900127ffbd234a`，已把原盘点提交重放到该基准并通过 `git ls-remote origin refs/heads/main` 核对一致。下文源码路径、符号与行号均指此基准，后续集成需重新核对。
- 事实源：[#172 当前票面](https://github.com/Stellogic/customer-agent/issues/172)、[父规格](../specs/issue-149.md)、[自然语言受理 ADR](../adr/0007-natural-language-intake-creates-confirmed-ticket-sets.md)。本地 `docs/tickets/spec-149/issue-172.md` 是旧镜像；本次已读取 GitHub 当前正文与原生依赖，不修改镜像。
- 当前原生前置中 #150/#155/#156/#157/#158/#159/#161/#163/#164 已关闭；#169/#170/#171 仍 OPEN。#193 是 #171 的在途接触点，不把它写成 #172 的新增原生依赖。关闭前置不等于本次已验证所有消费者。
- 仅执行 Git/gh 只读核对、源码搜索与文档审阅。**未运行测试、格式化或格式检查、lint、类型检查、构建、Docker/Compose、模型、浏览器验收、smoke 或完整门禁；不占测试锁，不触发 CI，不合入、不关票。**

追溯示例：[客户 v2 控制器固定源码](https://github.com/Stellogic/customer-agent/blob/e34b60113a3bbcfe28a4fcd247900127ffbd234a/backend/src/main/java/com/stellogic/customeragent/ticket/CustomerTicketV2Controller.java)。其他路径可用 `git show e34b60113a3bbcfe28a4fcd247900127ffbd234a:<仓库相对路径>` 回读。下文 `J/` 表示 `backend/src/main/java/com/stellogic/customeragent/`，`T/` 表示 `backend/src/test/java/com/stellogic/customeragent/`，`M/` 表示 `backend/src/main/resources/db/migration/`。

## 收缩对象的判定

“v2-only”指新产品接缝，不是把所有带 `v1` 的字符串改成 `v2`：当前受理实际使用 `customer-intake-v4`，公开对话使用 `public-conversation-v2`，客服工作台使用 `support-workbench-v2`。

旧直接建单、客户旧快照/事件、客服旧单工单队列、旧受理解析和固定问题选择属于待收缩对象。独立且仍有用途的 `approval-view-v1`、`customer-intake-recovery-v1`、`sibling-ticket-summary-v1`、`customer-communication-input-v1`、`investigation-capability-catalog-v1`、知识条目版本及 `rag_eval_v1` 不因版本名自动删除。

未带 `/v2/` 的路径也不能批量删除：客户澄清、转人工、自动结案取消仍是当前页面使用的动作。逐端点确认替代行为后再决定处理方式。每张工单继续保有独立对话和权限，不能把“删除单工单投影”误解为删除按工单读取能力。

## 消费者清单

表中“已使用新接缝”仅为静态观察；**每行的真实迁移验收均未在本次执行**。

| 编号 / 消费者 | 基准上的路径与发现 | 删除前的处理与证明 |
| --- | --- | --- |
| C1 客户受理、恢复 | `frontend/src/App.tsx:18` 使用 `/api/customer/v2/intakes` + v4；`:1890` 的 `parseIntakeSnapshot` 仍识别 v1/v2/v3/v4，包含旧 `issue`/`ticketId` 与数组归一化。`J/ticket/CustomerIntakeV2Controller.java:24` 的 `ACCEPTED_SCHEMAS` 仍接受旧开始请求；`:198` 的 v4 响应仍带单值 `issue`、`ticketId`。 | 将活动消费者和 fixture 迁往现行数组/版本字段后，去掉无消费者的旧请求版本、响应字段和解析分支；旧版本的具体处理策略需明确。覆盖单问题、多问题、多订单、重复问题及七日恢复，不只改 schema 字符串。 |
| C2 客户公开对话与问题选择 | `frontend/src/App.tsx:411,764,1657` 已读取 v2 快照/SSE；`:1340` 仍有“提交物流延迟问题”按钮；`:647,1577` 在 RESOLVED/CLOSED 回复表单要求订单编号及固定问题下拉，再 POST `/api/customer/tickets/{id}/replies`。 | 改入口文案时同步调用它的浏览器/单元测试；固定选择迁往自然语言闭环，先确认已结案同问题重开、其他问题关联新单的替代行为。不能删除下拉后默认为某一问题或丢失这些行为。 |
| C3 Spring 客户旧 HTTP 层 | `J/ticket/CustomerTicketController.java:22` 暴露 POST `/api/customer/tickets`、GET `/{id}`、GET `/{id}/events`，硬编码 `LOGISTICS_DELAY`；`SnapshotResponse` 返回 `CUSTOMER_PUBLIC`，含创建/首响时间。 | 全部调用方迁移后删除旧控制器专属 DTO/envelope。旧响应时间字段若仍用于其他投影则保留其数据来源；不能连同通用服务整体删除。 |
| C4 名为 v2 的直接建单桥 | `J/ticket/CustomerTicketV2Controller.java:54` 仍有 POST `/api/customer/v2/tickets`，接收 `schema/orderReference/description` 并硬编码 `LOGISTICS_DELAY`；GET/messages/events 与它共类。 | smoke 和 e2e 仍调用此 POST；迁往自然语言受理并确认建单后才能删除该方法/DTO。保留 v2 对话读写，不能靠把旧 URL 换成这个桥证明已迁移。 |
| C5 客户事件 adapter 与写入 | `J/ticket/CustomerTicketV2Controller.java:26,135,254` 将外部 v2 游标转回 `customer-public-v1`，再转换旧事件；`J/ticket/TicketModels.java` 的 `CustomerPublicEvent.publicData()` 仍生成旧 envelope。 | 先完成下节 H1 的存储/游标迁移，再删 `V1_SCHEMA` 转换及旧 envelope。当前 v2 页面仍依赖此桥。 |
| C6 客服前端与 Spring 队列 | `frontend/src/SupportWorkbench.tsx:17,135` 显式请求 v2，配合 `frontend/src/OrderTicketGroups.tsx`；`J/queue/SupportWorkbenchController.java:34,214` 无 schema 时默认 v1，保留 `LegacySnapshotResponse/LegacyQueueItem`；`J/queue/SupportWorkbenchProjectionService.java:463` 接受双 epoch。 | 先迁移无 schema 请求、旧事件游标和测试。保留当前负责客服详情、持久化领取、公开回复及补偿；配合 H2 停止旧投影双写，再收缩默认与解析。 |
| C7 审批、壳与共享解析 | `frontend/src/ApprovalWorkbench.tsx:13`、`J/approval/JdbcApprovalService.java:28` 仍使用独立 `approval-view-v1`；`frontend/src/shells/InternalShell.tsx` 承载导航；`frontend/src/streamProtocol.ts` 是通用 SSE/指定 epoch 解析。 | 不是旧客户单工单协议的同义词。保留审批权限边界和通用解析；#193 接入后再验证跨角色页面，不能给审批人开放完整客户对话。 |
| C8 Agent adapter | `agent/src/baseline_agent/graph.py:228,676` 经 `/internal/agent/tickets/{id}/generations/{generationId}/...` 消费同订单摘要、沟通上下文；`J/ticket/AgentServerIntakeUnderstandingGateway.java` 与 `agent/src/baseline_agent/intake_graph.py` 负责受理。main 已包含 #190 的内部知识检索基础，但当前图不是客户 v1 HTTP 的直接消费者；它仍通过 Spring 公共投影写入间接依赖 H1。 | 维持 Spring 授权、代次和公共投影边界；#169 Draft 已实现其自有共享检索/客户投影接缝但尚未合入和运行验证，后续按固定提交重新盘点，不复制 adapter。 |
| C9 集成 smoke 与模型业务 smoke | `agent/smoke.py:295,411,454,496` 直接建单、读 v1 快照/SSE，`:562,698` 又用 v2 直接建单桥；旧读贯穿补偿、澄清、转人工、结案 fixture。`:1724,5076` 还有客服 v1 字面量。`agent/src/baseline_agent/formal_mode_business_smoke.py:279,289`、`real_shadow_business_smoke.py:197` 使用旧客户端点。 | 按场景迁移 setup 和断言，保留幂等、权限、补偿、代次及结案行为证明。逐处区分正向调用与故意错误游标的负向断言，不能机械替换或删掉失败能力。 |
| C10 Playwright | `frontend/e2e/issue80.business-boundaries.spec.ts:32,54,81` 读取旧快照；`issue124.offline-fullstack-readiness.spec.ts:130` 调用 v2 直接建单桥；`issue153.atomic-multi-issue-intake.spec.ts:88` 提交 intake-v2。众多用例仍依赖旧按钮文案，见下方补充。 | 将真实 setup 改为确认受理，更新字段、定位和网络断言；旧 API 拒绝测试可以保留明确负向目的。逐场景运行验证，不能把源码中出现 v2 当 PASS。 |
| C11 单元测试、契约夹具 | `T/ticket/{CustomerTicketApiTest,CustomerTicketV2ApiTest,CustomerTicketPrincipalSecurityTest,JdbcCustomerTicketServiceTest,CustomerIntakeV2ApiTest}.java`；`T/queue/{SupportWorkbenchControllerTest,SupportPrincipalSecurityTest}.java`；`frontend/src/App.test.tsx` 含 intake-v1/v2 fixture。 | 迁移活动正向契约、Mock 和返回字段；删除只测旧成功行为的用例前，确保新真实路径覆盖同一要求。服务内部 `CreateCustomerTicket` 测试不因名称自动变成旧 HTTP 消费者。 |
| C12 验收脚本与数据库 fixture | `compose.yaml:174,195,210` 挂载/调用三类 smoke；`scripts/check.ps1` → `scripts/smoke.ps1` / `scripts/issue80-acceptance.ps1`；`scripts/browser-acceptance-plan.psd1` 与 `scripts/issue129-acceptance-plan.psd1` 注册浏览器场景；`scripts/fixtures/issue80-browser.sql` 及 e2e 内联 SQL 构造状态。 | 脚本虽不一定含旧 URL，仍传递调用这些消费者。同步验收注册、状态 fixture 与迁移后约束；不在本次运行或编辑共享入口，也不通过清库重置掩盖迁移问题。 |
| C13 文档示例 | `README.md:93` 仍将客服队列说明为 v1；`docs/baseline/verification.md:97,109`、`docs/delivery/issue-151-verification.md`、`issue-152-verification.md` 记录历史阶段契约；`docs/tickets/spec-11/issue-13.md` 是历史票据。 | 当前使用说明需更新；历史规格/交付记录保留语境与原事实，不伪改成新行为已通过。扫描应明确区分历史证据和活动指引，本盘点本身也不是业务消费者。 |

浏览器旧按钮定位涉及 `frontend/e2e/` 下 `issue80.identity-shells`、`issue80.business-boundaries`、`issue98.customer-help-center`、`issue99.support-workbench`、`issue101.cross-role-acceptance`、`issue124.offline-fullstack-readiness`、`issue129.flash-customer-communication`、`issue152.natural-language-intake`、`issue153.atomic-multi-issue-intake`、`issue154.duplicate-multi-order-intake`、`issue155.intake-recovery`、`issue156.intake-assistance`、`issue157.order-ticket-groups`、`issue163.persistent-support-replies`、`issue164.standard-compensation`（均为 `.spec.ts`）；另有 `frontend/src/{App.test,App.integration.test,Issue29.e2e.test}.tsx`。

`frontend/e2e/issue157.order-ticket-groups.spec.ts` 的转人工、`issue162.auto-resolution.spec.ts` 的取消动作，以及 `agent/auto_resolution_smoke.py` 的取消/结案回复均仍使用无 v2 前缀动作，不等于都可删除。`T/clarification/CustomerClarificationControllerTest.java`、`T/handoff/CustomerHumanHandoffControllerTest.java`、`T/closure/CustomerReplyControllerTest.java`、`T/ticket/CustomerAutoResolutionControllerTest.java`、`T/identity/HumanApiNegativeMatrixTest.java`、`frontend/src/{AutoResolution.test,Routing.test}.tsx`、`frontend/src/humanSessionLifecycle.test.ts` 也需按实际端点逐项归类。

## 历史读取与迁移计划

| 编号 | 当前数据链路 / 固定源码 | 后续最小迁移计划与未决项 |
| --- | --- | --- |
| H1 客户消息和事件历史 | `M/V2__customer_ticket_intake.sql` 建立 `support_ticket/public_message/customer_public_event/customer_ticket_request`。`J/ticket/JdbcCustomerTicketService.java:407,442,508` 读取工单、消息与指定 epoch 事件；当前新消息仍写 v1 epoch。`CustomerPublicProjectionAppender`、`JdbcAgentReplyStreamService`、`J/investigation/AutoResolutionService.java:111` 和 `M/V40__customer_auto_resolution_projection.sql:190` 也写 v1。 | 不能只删 HTTP 桥或只改常量。后续以追加迁移明确旧事件如何保留/转换、所有写入点如何切换、序号如何衔接，并验证旧工单快照和断线游标恢复。具体采用原序列迁移还是重建投影尚未实施/验收；不得先删除历史读取。保留业务消息、审计与权限，不建立额外兼容框架。 |
| H2 客服队列历史 | `M/V15__support_workbench_recovery_projection.sql` 建立旧队列事件；`M/V28__order_ticket_group_projection.sql` 扩展双 epoch、`epoch_sequence`、`support_workbench_epoch_cursor`，并在触发器内同时写入 v1/v2。`J/queue/SupportWorkbenchProjectionService.java:51,67` 按 epoch 读。 | 所有队列消费者用 v2 后，以新增迁移替换触发器使新写入只产 v2；保留历史行及必要约束，明确旧游标拒绝后重读 v2 快照的行为。不可直接改写已执行 V15/V28 或删除历史行来“消除搜索命中”。 |
| H3 旧单问题受理记录 | `M/V23__natural_language_single_issue_intake.sql` 的 `customer_intake.ticket_id/issue_kind/issue_summary`；`M/V24__atomic_multi_issue_intake.sql` 回填 `customer_intake_issue` 并引入 `shared_intake_record/shared_intake_issue`。`J/ticket/JdbcCustomerIntakeService.java:654,797,1091,1171` 仍写/读旧单值列，但响应 ticketIds 来自 shared 关联。 | V24 没有为既有已确认单工单回填 shared 关联；这是需用历史样本验证的读取缺口，不能在此宣称发生过线上丢失。删除单值列或单值响应前核对 V23 已确认、未确认、V24 多工单及 V25/V26 多订单/归档记录，明确必要回填与恢复结果。不能伪造历史确认原文。 |
| H4 内部建单幂等与关联工单 | `J/ticket/JdbcCustomerIntakeService.java:629` 的确认事务仍调用 `tickets.create(new CreateCustomerTicket(...))`；`JdbcCustomerTicketService.java:395` 的关联新单也调用 create；`customer_ticket_request` 保存稳定请求结果。`J/group/OrderTicketGroupService.java:24` 从旧新 `support_ticket` 统一读订单组。 | 删除的是旧公开入口，不是仍被受理确认使用的服务、幂等表或所有单票字段。保留原工单 ID、订单归属、消息、审计和请求映射，验证历史工单仍在订单组可见且不会重建重复工单。 |
| H5 已结案回复 | `J/closure/CustomerReplyController.java:18,26` 只接受 `LOGISTICS_DELAY/OTHER`，而 `App.tsx:1583` 下拉还列出其他类型；`J/closure/JdbcClosureService.java` 负责重开/关联。 | 这是静态可见的前后端范围差异，未运行复现。自然语言替代与原重开规则的责任边界需要协调；先保留当前行为入口，后续在收缩范围内解决，不能顺手重设计结案系统。 |

所有 SQL 仅阅读。本次没有读取实际数据库、迁移执行历史或 LangGraph checkpoint。上述数据路径是源码结论，不是现存数据状况；迁移号应在正式集成的最新 main 上分配，不预占、不复用其他票迁移号。

## 在途接触点（只读固定提交）

| 归属 / PR / SHA | 最小契约与参考路径 | #172 等待事项 |
| --- | --- | --- |
| #169 / [PR #208](https://github.com/Stellogic/customer-agent/pull/208) / `0a09c958ac606b5fb3554a69b971aa43e8b941e1` | Draft 已从独立来源组件扩展到 Agent 查询、Spring 授权检索/引用复核、客户投影、迁移 `V43__customer_knowledge_reply.sql`、App 接线及静态测试/验收源码；来源公开字段仍限标题和更新时间。PR 正文明确当前提交之后的测试、数据库、模型、48题和门禁均 `NOT_RUN`。 | #169 合入后按实际 main 重查 C2/C5/C8、H1 与新增迁移，确认知识来源随 v2 快照/SSE/断线恢复且不让 #172 复制 adapter。当前 Draft 不能作为消费者已迁移证据。 |
| #170 / [PR #209](https://github.com/Stellogic/customer-agent/pull/209) / `e61152199c985f2d46b1a1cf1575b14ac8cb3a03` | Draft 已增加客服自有 Spring/Agent 辅助接缝、`V44__support_assistance_request.sql` 和 `SupportWorkbench` 宿主接线；草稿仍需人工审阅后交给既有发送区。它固定引用尚未合入的 #169 共享实现，当前测试、构建、数据库、模型、浏览器及门禁均 `NOT_RUN`。 | #169/#170 依次正式合入后重查 C6/C8、迁移序号和撤权清屏；不由 #172 实现辅助或复制 #169 adapter。Draft 静态接线不等于真实消费者验收。 |
| #193 / [PR #205](https://github.com/Stellogic/customer-agent/pull/205) / `3731e3e34ad7d26ce7a8badcf2145c9def83727a` | Draft 已把普通客服/审批入口挂到现有投影并保留 ContextEntries/InternalShell；#170 的相似案例/建议动作仍未接入。其阶段状态为 `FOCUSED_VALIDATED`，但浏览器、Docker、模型和完整门禁仍未运行。 | #170 接线及 #193 最终集成后重新检查 C6/C7，保留审批人无完整对话边界。建议动作归 #170，壳和无写入占位归 #193；#172 不触碰这些文件。 |
| #173 / [PR #210](https://github.com/Stellogic/customer-agent/pull/210) / `50a15db64cfc2412bbee22eb8eef4a701fb91bec` | 下游 Draft 新增真实全栈/固定时钟 Playwright 与验收脚本源码，当前基线正是本文件基准；它明确等待 #169/#170/#171/#172，所有运行均 `NOT_RUN`。 | #172 删除前把 `frontend/e2e/issue173.*`、`frontend/e2e/support/issue173-intake.ts` 和 `scripts/issue173-clock-acceptance.ps1` 纳入 C10/C12 的最终迁移回读；不改其分支或把静态验收源码当 PASS。 |

四份 PR 在盘点时均为 Draft；本次只读其正文、文件清单及固定源码。#190/#168 已合入本次 main，但 #169/#170 的实际客户/客服消费仍由各自任务处理；这里不沿用 Draft 的静态 PASS、历史聚焦结果或事故前证据作为 #172 迁移证据。

## 待迁移断言源码清单

本轮原文件边界只有本文件，因此不新增共享脚本或测试文件；以下是可直接落为断言源码的最小清单。每项当前都应能发现活动消费者，状态统一为 **PREPARED / NOT_RUN / EXPECTED_TO_FAIL_BEFORE_MIGRATION**，不是当前质量门。

| 断言 | 激活后的最小判定 | 当前允许命中 / 迁移责任 |
| --- | --- | --- |
| A1 旧客户 HTTP 成功路径归零 | 活动源码、正向 smoke、Playwright 和正向 API 测试不得再调用 POST/GET/SSE `/api/customer/tickets` 旧三件套；新动作端点按独立清单处理。 | 历史文档、旧迁移、明确的权限/不兼容负向断言可保留；C3/C9/C10/C11 先迁移。 |
| A2 v2 直接建单桥归零 | 不再 POST `/api/customer/v2/tickets`，只保留该基址下对已确认工单的快照、消息和事件消费。 | C4/C9/C10/C11 当前仍有正向命中；迁往 v4 自然语言受理确认。 |
| A3 固定问题选择归零 | 产品 JSX 与正向 UI 测试不得出现“提交物流延迟问题”“回复问题类型”或固定 issueKind 下拉。 | 历史票据可保留；C2/C10/C11 迁往自然语言输入与原重开/关联行为。 |
| A4 旧受理响应解析归零 | 产品解析器、请求成功测试不再接受 `customer-intake-v1/v2/v3` 或依赖单值 `issue/ticketId`。 | 明确的不兼容/历史数据读取测试保留；C1/C11 先迁移，H3 明确历史回读。 |
| A5 客户 v1 投影活动读写归零 | Java/Python/前端活动路径不再生成或消费 `customer-public-v1`；外部只见 `public-conversation-v2`。 | 已执行迁移与保留历史读取实现可命中；H1 必须先给出追加迁移和旧工单/游标实测。 |
| A6 客服 v1 投影活动读写归零 | 默认响应、游标解析、触发器新写入、正向测试/smoke 不再接受 `support-workbench-v1`。 | 已执行 V15/V28 和历史只读路径可命中；C6/C9/C11、H2 先迁移。 |
| A7 非历史残留分类完整 | 扫描结果中的每一项必须归为活动待迁移、独立有效协议、历史证据或明确负向断言，不允许“未知”。 | A1–A6 的允许清单必须使用具体文件/断言名，不能按整个目录放行。 |

A1–A7 只证明仓库静态残留已分类。真实 v2 行为、历史兼容、bundle/网络/日志和敏感内容边界仍必须用 C1–C13 对应的运行证据证明；静态断言通过不能替代这些验收。

## 删除顺序与待验证清单

1. 同步已合入前置和最新 main，刷新 C1–C13 与四个在途固定 SHA；由协调确认已结案自然语言回复的衔接归属，以及仍需保留的无版本前缀动作。正式范围仍只做契约收缩。
2. 先迁移正向消费者：前端及旧响应解析、真实浏览器 setup、smoke、Mock/SQL fixture、活动文档。逐场景记录消费者路径、最终 SHA、运行入口和实际结果；本文件所有运行结果当前均为 **NOT_RUN**。
3. 在有历史数据的隔离验证环境执行 H1–H4 的追加迁移，核对消息/工单/审计/幂等映射与游标恢复；保持迁移历史可追溯，禁止清库绕过兼容。H5 的回复范围差异需纳入实际验收。
4. 全部消费者已通过新接缝真实验收后，再删旧客户控制器、v2 直接建单桥、无消费者的旧 schema/DTO/解析、客服旧默认投影与双写。无版本前缀的当前业务动作只按已确认的替代方案处理。
5. 重新静态扫描并人工分类剩余引用：历史文档/迁移、独立有效协议、明确负向测试、活动残留。扫描不能替代运行证明；仍有活动残留则不宣称 v2-only。
6. 正式窗口按仓库当前流程完成聚焦验证、预检、双轴确认和最终一次 `pwsh ./scripts/check.ps1 -Issue 172`；验证浏览器 bundle/网络、Spring/Agent 日志、迁移历史的敏感内容边界。最终 HEAD 变更后旧门禁证据不沿用；本次不启动这些步骤，不触发 CI 或外部审查。

后续最小真实验收覆盖：自然语言确认单/多问题、多订单与重复问题；旧工单及旧受理恢复；公开对话刷新/断流/游标恢复；持久化领取和人工回复；审批隔离与补偿；结案回复/关联单；#169 引用恢复及 #170/#193 撤权清屏。它们是当前需求的待验证项，不新增极端场景或防御框架。

本次使用的只读搜索口径（后续按最新提交重跑；不是测试或成功断言）：

```powershell
rg -n 'customer-public-v1|support-workbench-v1|customer-intake-v[123]' frontend backend agent scripts docs README.md
rg -n '/api/customer/(v2/)?tickets|CreateCustomerTicket|LegacySnapshotResponse' frontend backend agent scripts
rg -n '提交物流延迟问题|回复问题类型|parseIntakeSnapshot' frontend
rg -n 'customer_public_event|support_workbench_event|customer_ticket_request|shared_intake_issue' backend/src/main
```

搜索范围覆盖活动源码、测试/fixture、验收脚本和文档，但不是对动态构造 URL、运行期请求或数据库历史的穷尽证明。最终删除前必须按以上清单实测回读。
