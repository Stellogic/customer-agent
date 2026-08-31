# #190 分层检索接缝与实现边界

依据 [rag-layered-v2](../eval/rag-layered-v2.md)，本次解除默认检索的实验校准与评分依赖。实验类、配置、测试、数据和失败证据保留；`KnowledgeAnswerabilityPolicy` 不再注册为 Spring 产品组件，只有显式历史实验/测试使用。默认检索也不计算实验四特征。

## #168 / #169 可参考的实际接缝

本文件随源码提交，固定 SHA 以该提交及协调交接为准；提交前不称已集成或已验证。main 在本次同步时为 `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`，其未包含本票混合检索。未发布迁移 `V42__knowledge_vector_index.sql` 不与 main 已有 V36/V37/V39/V40/V41 碰撞，未改已应用迁移。

- Java `KnowledgeRetrievalService.search(principal, query, scope)`；HTTP `GET /api/internal/knowledge/search?q=...&scope=...`，只支持真实内部会话。不存在 `searchAuthorizedScopes`；本票没有 Agent 或客户检索授权 API，不得伪装内部身份调用。
- 响应 `schema=knowledge-hybrid-v2`，顶层 `query/generation/revision/lexicalCandidates/vectorCandidates/results`。不含 `policy`、校准哈希、阈值或 `answerable`；v1 的评分语义不能混用。
- 各 hit 为 `chunkId/articleId/version/title/applicability/sourceFile/startLine/endLine/snippet/score/lexicalScore/vectorScore`，**无 updatedAt**。`results` 是 RRF 有序 Top-5，两个候选数组分别是排名前硬过滤后的最多 20 条词法/稠密候选，不是两个独立已验收的分路输出。
- HTTP 200 的空 `results` 仅表示当前授权范围无匹配，不代表资料不足的语义判断。有效 scope 与当前身份允许范围无交集时，当前行为也是 200 空候选。无权限/客户调用内部接口是 403；400 为无效 query/scope；503 为模型、索引、检索或融合不可用。不能把非 200 当 NO_MATCH。
- 业务错误码来自 `KnowledgeCatalogExceptionHandler`：`KNOWLEDGE_ACCESS_DENIED`、`INVALID_KNOWLEDGE_QUERY`、`INDEX_STALE`、`MODEL_UNAVAILABLE`、`RETRIEVAL_UNAVAILABLE`、`FUSION_UNAVAILABLE`。旧 `CALIBRATION_REQUIRED` 不再是默认路径故障。路由级授权拒绝可能先于该处理器发生，应以 HTTP 403 处理。
- 目录/条目详情 API 有 `updatedAt`，仍要求内部授权，且允许查旧版本；不能以该接口为客户补读或绕过当前发布过滤。#169/#170 共享 Agent 适配、授权范围与来源投影由协调指定的唯一 owner 承接，不在 #190 另建 HTTP 接口或复制其实现。

## 评测接缝

`baseline_agent.knowledge_evaluation.run_query(base_url, query, expected_schema="knowledge-hybrid-v1")` 保留旧默认以防旧实验静默混用；新版显式传 `"knowledge-hybrid-v2"`。返回每题 `id/kind/http_status/recall/reciprocal_rank/checked_prohibitions/violations` 加实际响应。预期身份无权时保留 403 与空数组；服务异常抛出，由运行报告记录 ERROR，不计正确拒答。

`retrieval_metrics(rows)` 只返回 `answered_recall_at_5/answered_mrr_at_5/wrong_version_top5_hit_rate/out_of_scope_top5_hit_rate/unauthorized_top5_hit_rate`。`metrics(rows)` 保留旧空列表拒答含义，不得用它给新版报告标 PASS。正式 `scripts/knowledge-quality-gate.ps1` 显式传 `--protocol rag-layered-v2-retrieval`，报告名 `rag-layered-v2-retrieval-result.json`；完整冻结集合、语料哈希校验、编码协议与真实 Spring/PostgreSQL 路径不变，回答质量标记 `NOT_EVALUATED`。

#168 如需词法/稠密独立 Top-K 的命中计数，应在自身消融模块使用这两路实际候选与同一匹配规则计算，不能复制 RRF 的 recall/rank/violations。候选已可观测，不代表本票已提供分路评测函数；#168 仍拥有消融、tokenizer/feature-model 导出及可选 ONNX，#190 拥有默认 encoder/检索/依赖。不得以固定伪造分路结果补齐报告。

## 验证与试错边界

本次最小改动覆盖默认服务、响应版本、页面用语、正式质量入口和分层指标。既有真实浏览器/API 接缝增加独立园艺问题样例，验证即使无法回答也可以返回授权候选，不再被校准门挡住；原硬过滤/撤权/索引失效验证继续执行。指标测试区分合法无答案候选与禁止版本，旧指标测试保留。

本文编写时上述新增测试未运行，不宣称红绿 TDD。后续聚焦、格式/类型、组件、真实分层质量门及完整门禁证据按 RunId 另存。没有真实 DeepSeek 调用，不读独立留出，不为新口径重算历史失败，不修改 #189 冻结资产。过往试错及其限度见 [reranker 开发与输入审计](issue-190-reranker-development-a.md)。
