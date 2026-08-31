# #169/#170 共享检索适配接线契约

2026-09-01，#190 已合入 main 并关票，协调授权 #169 单独实现共用 Spring→Agent 检索适配及客户知识回答，#170 实现自有 HUMAN 编排。以已合入检索为基础，不复制引擎、不伪造内部主体。

## Java 入口

同包 `KnowledgeRetrievalService.searchAuthorizedScopes(query, scopes)` 仅供可信适配调用，复用已有检索主体；员工原 search 的身份/scope 检查不变。未新增内部客户身份或客户访问内部知识页面权限。

公开 Spring bean `com.stellogic.customeragent.knowledge.AgentKnowledgeRetrievalAdapter`：

- `searchCustomer(String query)`：范围固定 CUSTOMER_PUBLIC；外层先验证当前客户工单 generation。
- `searchSupport(String principalId, String query)`：principalId 来自当前客服身份；要求知识读取能力且有 SUPPORT 范围，实际范围固定 INTERNAL/SUPPORT。
- `revalidateCustomer(AgentKnowledgeResult receipt)` / `revalidateSupport(String principalId, AgentKnowledgeResult receipt)`：不编码、不重新排名；核对当前索引代次、发布/当前版本、条目与片段范围、canonical 元数据和完整片段内容。支持零条目但仍检查索引。返回通过复核的 receipt。

四个公开方法均须经 Spring 代理，在只读 REPEATABLE_READ 事务中运行。外层编排不持事务：先短事务授权，调用适配结束后，再短事务复核 generation/assignment 并接受结果。复核方法不代替调用方的工单授权，也不证明资料足够回答。

返回公开 record `AgentKnowledgeResult(String schema, long indexGeneration, List<AgentKnowledgeResult.Source> results)`，schema=agent-knowledge-v1，最多五条；嵌套公开 Source 字段为 articleId/version/chunkId/title/updatedAt/applicability/startLine/endLine/snippet。updatedAt 是 Instant，applicability 是 List<String>。同事务从实际 Top-5 对应 article/version/chunk 补读规范元数据，结果无 sourceFile、分数、内部候选或校准字段。

复核的 receipt 必须来自本次授权检索的已保存回执。#170 可以构造保留同一 schema/indexGeneration、只包含已选 Source 的子集；它负责证明模型引用属于本次 Top-5，不能传模型自造 Source。#169 客户回执由当前 generation/request 绑定。模型回答 schema 不共享，两条路径分别在同次 DeepSeek 中判断充分性并输出回答。

## 错误与所有权

复用全局 KnowledgeCatalogExceptionHandler：403 KNOWLEDGE_ACCESS_DENIED、400 INVALID_KNOWLEDGE_QUERY、503 INDEX_STALE/MODEL_UNAVAILABLE/RETRIEVAL_UNAVAILABLE/FUSION_UNAVAILABLE；失效引用或字段不匹配为422 INVALID_KNOWLEDGE_CITATION。索引/权限失败不能降为无匹配；Python共用纯解析仍由knowledge_retrieval.py唯一承担。Java调用方可让异常交给原handler，不复制错误转换或知识SQL。

#169 修改 knowledge 适配/投影、客户 investigation/Agent graph/communication、公开消息和 App.tsx；#170 修改自有 queue/HUMAN/SupportWorkbench，拥有 langgraph.json 的 support_assistance 图注册与 V43 迁移。#169 使用 V44__customer_knowledge_reply.sql；#168 独占 encoder 公开加载、ONNX、消融和相应依赖增量，本票不改 encoder/pyproject/uv.lock。

本文件的首次接线提交只经过静态检查与审阅，不宣称运行通过；聚焦、真实质量和最终完整门禁证据后续记录。旧575d10a的41项聚焦不覆盖本次接线。
