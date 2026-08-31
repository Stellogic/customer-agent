# #169 客户接线进度与验证边界

2026-09-01，在 #190 合入 `8bd86e618e1a282d647cc234dcb445035f8cb23a` 后，依协调任务放行推进本票；共享适配已提交 `f31a454fba3d1950b8ce0abbf5598d0120aa45cc` 并通知 #170。本文件接续历史静态记录，不覆盖旧的未测或失败证据。

## 当前源码增量

- 客户 Agent 的 `/internal/agent/tickets/{ticketId}/generations/{generationId}/knowledge/search` 只接受 query；服务端固定 CUSTOMER_PUBLIC。先验证机器 operation 和当前 generation，再检索，最后短事务再次验证并保存回执。检索过程中不持工单锁。相同请求重试复核原回执，不再次编码；同一请求换 query 返回冲突。复用已有 agent_command_request 和其必需参数摘要，没有新增请求身份机制。
- action planner 最终 SUBMIT_CONCLUSION 可在同次选择中产生 nullable knowledgeQuery；当前客户问题单独标为不可信数据，不进入 Spring 业务事实。graph 按非空 query 调用本票客户检索入口，授权结果单独传给 communication；查询选择不代表资料充分性判断。
- customer communication 可选 customer-reply-v2 分支保留原 body/业务事实校验，另在同次模型响应内生成 knowledge.status/answer/citations。SUPPORTED 必须有引用，INSUFFICIENT_INFORMATION/CONFLICT 不携带引用。逐字引用必须存在于本次 CUSTOMER_PUBLIC 片段并匹配 articleId/version/chunkId；没有单条 24 字符限制。
- v2 供应商响应完整缓冲，不向客户回调任何 delta。Java v2入口另外要求 graph 绑定的 knowledgeRequestId，该身份不由模型生成。最终接受从本 generation 的持久回执取资料，经共享适配的发布专用复核，在工单事务内取得目录/向量更新共用的共享 advisory lock，直到公开消息提交。旧 v1 仍可接受，业务正文规则不放宽。
- 公开正文由已验证业务正文和知识说明组成；知识附加正文拒绝金额、执行承诺、个案事实断言及已知注入指令，引用须来自本次回执。冲突单独写 KNOWLEDGE_CONFLICT 审计；资料不足本身不触发人工或自动结案。既有独立业务转人工规则保留。正常生成失败仍允许一次受控回复修正，无默认独立充分性调用。
- 按协调顺序使用未发布 V43 扩展 public_message 的安全来源列、公开事件白名单和流正文上限2502；保留原事件格式校验。客户页面只解析 status/sources(title,updatedAt)，丢弃含内部字段的整份投影；已接受消息恢复来源，流完成不重复正文，断线清空旧内容并显示恢复提示。迁移编号须交付前与 #170 按最新 main 再核对。

## 协议候选与未完成项

候选 prompt 为 customer-knowledge-communication-v1，schema 为 customer-reply-v2；知识回答正文最多 1500 字符、最多五条引用，整体模型输出默认 1536 token、配置上限 2048。它们是源码候选，**尚未完成真实执行协议冻结，也没有真实调用**。引用不单独截断，整体输出截断属于失败，不补造引用或重新标为资料不足。

尚未完成运行验证：真实数据库授权/版本竞态、完整链路与页面行为、结构/引用/语义分项质量报告，以及本票完整门禁。结构合法、逐字引文存在、已知注入模式被挡住或模型自评 SUPPORTED 均不能证明任意回答语义正确、全面无注入或整体通过；这些仍待真实路径质量验证。

聚焦批次候选：Python graph/communication/action/knowledge 测试，Java investigation/knowledge/ticket 相关单元测试，frontend App/CustomerKnowledgeSources；隔离 PostgreSQL 的 `backend/src/test/resources/issue169_customer_knowledge_projection.sql` 覆盖新旧事件、内部字段/作者拒绝及2502/2503边界，要求先准备合成 AGENT 工单且全事务回滚。该 SQL 不是单元 mock 或已执行证据，最终仍需完整 API 授权/撤权与版本重建交错验证。

运行窗口已归还协调任务。此阶段只写源码/测试源码/文档并进行静态双轴审查，测试、格式/lint/类型检查、构建、Docker、模型/评测均 **NOT_RUN**。旧 `575d10a` 的41项聚焦不覆盖这些增量。未转 Ready、未触发 CI、未合入、未关票。

## 增量静态审查

固定基点 `f31a454fba3d1950b8ce0abbf5598d0120aa45cc`，包含本阶段所有新增源码/测试源码。Spec PASS，0项发现；Standards 首轮发现1项P2：同键并发请求可能让接受阶段返回未经本次复核的旧回执。修复为既有回执必须等于本次已验证结果，否则409，补单元边界测试源码；复核 Standards PASS，0项未解决。该测试未运行，也不充当数据库并发证据。此结论仅是增量静态审查，不是整票规格验收或运行质量通过。

后续接线固定比较基点 `1a87f57121d3a4dc39f335286db5d914c3fa6aa2`：独立 Standards / Spec 最终均 PASS、0项未解决。修复了旧数据库事件白名单与流长度约束、个案物流断言、非JSON权限错误分类、检索有界重试，以及 Python / Spring 拒绝共用一次回复修正预算。补充对应源码测试，并让自动结案回读比较完整公开正文、调用记录按实际 logical call 计数。V43按协调明确的“169先、170后”顺序命名；旧170适配契约保持不变。

此阶段源码范围已接通，聚焦批次准备就绪；已请求协调在 #168 释放运行窗口后分配验证。**全部新测试及SQL仍 NOT_RUN**，不从静态通过推导真实行为或语义质量结果。真实模型仍须冻结正式协议和累计费用账本后才运行。
