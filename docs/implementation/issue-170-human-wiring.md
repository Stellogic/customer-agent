# #170 HUMAN 辅助接线源码（2026-09-01）

状态：**CODE_READY_NO_TESTS**；最终静态 Standards / Spec 均 PASS，当前不具备独立运行条件（待 #169 正式合入共享实现）。

当前仅源码/测试源码与静态双 CR，**NOT_RUN**。已同步正式交付的 main `8bd86e618e1a282d647cc234dcb445035f8cb23a`（分支保留提交，合并点 `6bc2eff`），#150/#160/#163/#190 原生前置均已关闭。协调允许源码接线，最新通知唯一运行窗口现归 #168（#169已归还静态空档）；本票没有测试、检查、构建、Docker、模型或锁查询权限。

## 固定共享契约与归属

只读 #169 `f31a454fba3d1950b8ce0abbf5598d0120aa45cc` 的 `docs/implementation/issue-169-shared-adapter.md` 和实际 Java 源码。#169 的 `AgentKnowledgeRetrievalAdapter.searchSupport(principalId, query)` 固定 INTERNAL/SUPPORT 并验证知识 capability；`revalidateSupport(principalId, receipt)` 只校验索引代次、当前已发布版本、范围和 canonical 内容，不再次编码或排名。`AgentKnowledgeResult.Source` 的九字段来自 Spring，Python `knowledge_retrieval.py` 为唯一解析。

本分支只引用这些公开类/纯解析，未复制未合入实现。它们目前不在 main 中，**运行前须同步 #169 已交付源码并核对契约**；当前静态审查不能证明本分支已可编译。旧 #190 scope 交集200语义不使用，显式越权由403处理。

协调统一交付顺序：#169 共享实现先交付并使用 V43，#170 后交付，请求表使用 `V44__support_assistance_request.sql`；本票已将未发布的 V43 仅改名为 V44，SQL内容不变。#170仍拥有 queue 下自有文件、SupportWorkbench 中辅助挂载/草稿衔接和 `langgraph.json` 的 support_assistance 注册。运行前须同步 #169 正式 main 并再次核对序号，不修改已发布迁移、不用 outOfOrder 绕过。#169拥有知识适配及客户路径，本票未修改其文件，也未改 App、InternalShell、共享回复/补偿存储、编码器或 #189 资产。

## 最小运行链路

复用现有 Spring MVC/Security、JdbcTemplate、LangGraph StateGraph、httpx 与 React；依据现有 SupportWorkbench、IntakeUnderstandingGateway/intake_graph 与 DeepSeek Responses 调用源码，不引入依赖或编排框架。

1. 已授权客服详情挂载独立 SupportAssistance。GET `/api/support/workbench/tickets/{ticketId}/assistance/context` 只返回当前 assignmentId；必须 SUPPORT/HUMAN/ACTIVE 且工单非终态。主体取 Authentication，不接受 supportId、scope 或 generation。
2. POST `/assistance/requests` 使用 `support-assistance-v1`、assignmentId、UUID requestId、四种 kind 和最多200字符查询（与共享检索上限一致）。CSRF/会话复用既有链路。输入只由 Spring 加载当前描述、最近20条公开消息和授权调查事实，不采用浏览器提供的事实/知识。
3. V44 持久化请求参数和输入投影。按客服/requestId唯一，同 ID 异工单/assignment/type/query 拒绝；参数直接比较，不新增哈希。工单行锁只覆盖申请执行权及保存回执的短事务；重复请求读取原回执，不再次执行。
4. 外层无事务地检索，之后再次验证 assignment；独立 support_assistance 图在同次 DeepSeek 输出充分性决定和总结/知识说明/政策解释/草稿，不单独调用充分性模型，无业务工具、自动发送或自动重试。
5. Spring 检查输出结构、长度、引用必须来自本次 Top5及逐字原文，以 canonical metadata 构造浏览器白名单投影；调用 #169 复核选中完整 Source，再验证当前 assignment 才存/返回。每次 GET `/assistance/requests/{requestId}` 也重新验证授权及知识引用，不缓存授权结论。模型 audit/知识原始回执不发送浏览器。
6. 客服手动插入、编辑并勾选审阅后，只把文字移交既有人工发送区。发送区已有编辑时再次确认替换；发送中/结果未知时禁止移交。最终公开发送仍由原按钮、CSRF、权限与幂等路径执行。详情撤权/断线重同步卸载辅助组件并中止客户端接收。

控制器绑定发起请求时的 HTTP session、sessionId 和主体，慢调用或回执读取后、写响应前复核会话仍有效且未换主体；不能只凭仍有效的 assignment 返回内部内容。详情权限流结束时，在等待详情重读前立即卸载辅助及丢弃待移交确认，重读成功后重新申请辅助权限，不恢复旧私有草稿。

## 失败与恢复边界

- 非正式模型模式明确 MODEL_UNAVAILABLE，调用次数0，没有产品假回答；真实调用失败与 INVALID_ANSWER_FORMAT 分开，不算资料不足。
- 浏览器未确认POST结果时仅查询原requestId，不自动重复生成。CSRF失败发生在提交前，明确允许重新发起；不伪装已有服务器请求。
- PENDING只表示没有终态回执，包含进程中断后未确认情形，不声称后台一定还在运行。没有后台重试队列或自动接管；重新打开详情后可显式新建请求，旧记录保留。正式验证须覆盖这一恢复提示，不能将其计入成功样本。
- 知识403/400/422/503复用 #169 已有异常处理；403清辅助授权与草稿，不降为NO_MATCH。失败回执仅保留通用受控原因，初次知识请求保留原状态码；回执不再次调用检索来重演错误。
- 模型调用 metadata 在最终授权检查前单独保存，即使生成途中撤权也保留费用证据；HTTP结果不确定记 TRANSPORT_UNCONFIRMED，不能按0调用/0费用处理。该记录写入不赋予任何人结果读取权。

## 本路径生成协议及预算

源码协议 `support-assistance-answer-v1`：默认 DeepSeek v4 flash，Responses strict schema；一次调用包含 decision/text/followUp/citations。输出 token 上限1800、正文2000字符、追问500字符、引用合计4000字符、最多5条；不设单条24字符限制。这些是当前源码执行参数，**尚未取得真实运行和冻结质量证据**，不得称质量PASS。

没有独立充分性调用或自动修正/重试；故障保留到完整样本分母。调用返回记录 model/responseId、usage、attempts、输出上限和估计费用。估价复用既有函数，不重建成本框架；实际模型/费用和未知 usage 必须在运行账本核对，源码估价不能冒充供应商结算。

真实质量运行前仍需同一累计账本核实剩余额度、冻结完整样本及 prompt/schema/源码记录，**所有相关运行累计不超过人民币6元，不重置旧消费**。本轮真实模型调用0；未知历史余额不表示可用6元。出现未知调用费用应先核对，不开始下一次付费运行。继续使用既有 #170 完整分母计数及三项独立检查，结构/引文通过不等于语义充分；不读验收错题调参。

## 测试与未验证

新增源码覆盖：同次调用和usage、非正式模式不伪造回答、失败不自动重试、引用归属/长引文、请求重放不再次检索/生成、检索后撤权禁止调用、回执重读复核且不泄露audit、宿主人工移交与未知结果GET恢复。全部未运行，测试transport/Mockito/HTTP响应仅为合成测试。

后续串行窗口需要聚焦 Python/Java/React、必要检查，真实 PostgreSQL 请求并发/异参/撤权与回执证据、工作台现有回复回归、窄屏视觉、真实回答质量和最终完整门禁。旧494dbff的25项PASS及7823fc3静态CR均不能覆盖本次源码。CI仍关闭，外部审查不阻塞；本轮不转Ready、不合入、不关票。

## 静态双 CR 记录

固定比较 `git diff --cached 6bc2eff270349f985494dd30f4e1f91fe034930f`，最终23个自有文件。Standards首轮PASS；Spec首轮发现P1原HTTP会话未在慢调用返回前复核、P2详情权限流断开后等待重读期间辅助未卸载。两项均已修复并添加测试源码：会话注销/主体切换拒绝内容返回，慢详情重读尚未完成时辅助编辑区已卸载。复核后 **Standards PASS / Spec PASS，剩余各0项有效发现**。最终文档只补记审查过程，无被测或实测证据；所有运行仍NOT_RUN。

迁移顺序增量：基线 `debe02094eca3f3ad4af8c03a84a7b73fc1ffa84`，仅自有迁移 V43→V44 的100%同内容重命名和本文引用更新；Standards / Spec 各 PASS、0项发现。未运行验证、未查询锁、未修改已发布迁移或他票文件。
