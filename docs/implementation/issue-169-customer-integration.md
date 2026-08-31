# #169 客户接线进度与验证边界

2026-09-01，在 #190 合入 `8bd86e618e1a282d647cc234dcb445035f8cb23a` 后，依协调任务放行推进本票；共享适配已提交 `f31a454fba3d1950b8ce0abbf5598d0120aa45cc` 并通知 #170。本文件接续历史静态记录，不覆盖旧的未测或失败证据。

## 当前源码增量

- 客户 Agent 的 `/internal/agent/tickets/{ticketId}/generations/{generationId}/knowledge/search` 只接受 query；服务端固定 CUSTOMER_PUBLIC。先验证机器 operation 和当前 generation，再检索，最后短事务再次验证并保存回执。检索过程中不持工单锁。相同请求重试复核原回执，不再次编码；同一请求换 query 返回冲突。复用已有 agent_command_request 和其必需参数摘要，没有新增请求身份机制。
- action planner 最终 SUBMIT_CONCLUSION 可在同次选择中产生 nullable knowledgeQuery；客户问题单独标为不可信数据，不进入 Spring 业务事实。查询选择不代表资料充分性判断。graph 尚未消费该字段。
- customer communication 可选 customer-reply-v2 分支保留原 body/业务事实校验，另在同次模型响应内生成 knowledge.status/answer/citations。SUPPORTED 必须有引用，INSUFFICIENT_INFORMATION/CONFLICT 不携带引用。逐字引用必须存在于本次 CUSTOMER_PUBLIC 片段并匹配 articleId/version/chunkId；没有单条 24 字符限制。
- v2 供应商响应完整缓冲，不向客户回调任何 delta；必须后续由 Spring 完成回执来源、版本、当前 generation、公开回复权限及安全正文复核后发布。当前 Java 结论入口仍只接受 v1，v2 不会直接绕过它。

## 协议候选与未完成项

候选 prompt 为 customer-knowledge-communication-v1，schema 为 customer-reply-v2；知识回答正文最多 1500 字符、最多五条引用，整体模型输出默认 1536 token、配置上限 2048。它们是源码候选，**尚未完成真实执行协议冻结，也没有真实调用**。引用不单独截断，整体输出截断属于失败，不补造引用或重新标为资料不足。

尚未完成：graph 的实际查询/回执消费、Java v2 校验及安全公开消息保存、来源组件挂载与恢复、真实数据库授权/版本竞态验证、结构/引用/语义分项质量报告，以及本票完整门禁。结构合法、逐字引文存在或模型自评 SUPPORTED 均不能证明语义正确、无 prompt injection 或整体通过；这些仍待实际路径验证。

运行窗口已归还协调任务。此阶段只写源码/测试源码/文档并进行静态双轴审查，测试、格式/lint/类型检查、构建、Docker、模型/评测均 **NOT_RUN**。旧 `575d10a` 的41项聚焦不覆盖这些增量。未转 Ready、未触发 CI、未合入、未关票。

## 增量静态审查

固定基点 `f31a454fba3d1950b8ce0abbf5598d0120aa45cc`，包含本阶段所有新增源码/测试源码。Spec PASS，0项发现；Standards 首轮发现1项P2：同键并发请求可能让接受阶段返回未经本次复核的旧回执。修复为既有回执必须等于本次已验证结果，否则409，补单元边界测试源码；复核 Standards PASS，0项未解决。该测试未运行，也不充当数据库并发证据。此结论仅是增量静态审查，不是整票规格验收或运行质量通过。
