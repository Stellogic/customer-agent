## Parent

Part of #149

Child of #167

## What to build

使用 #189 已冻结的质量基线，在本地 CPU 上交付可工作的中文混合检索纵切片：固定 revision 的 BGE Embedding、PostgreSQL 全文候选、pgvector 精确向量候选、权限与版本硬过滤、RRF 融合，以及连接真实结果的内部检索页面。任何客户或客服 Agent 消费前必须通过冻结质量门。

## Non-goals

- 不实现客户 Agent 知识引用或客服 Agent 辅助，它们分别由 #169 和 #170 承接。
- 不要求 ONNX 才能完成本票，也不提前选择 HNSW 或 IVFFlat。
- 不修改 #189 的查询、期望结果或阈值来取得通过结果。

## Acceptance criteria

- [ ] BAAI/bge-small-zh-v1.5 使用 #189 固定的完整 revision 与文件清单准备，模型权重不进入 Git；运行阶段只从校验通过的本地路径离线加载，缺失或校验失败时 fail closed。
- [ ] 以 CPU PyTorch/Safetensors 实现 #189 固定的查询指令、pooling、L2 normalization、最大长度、截断策略和 512 维 Embedding，并提供确定性契约测试。
- [ ] PostgreSQL 全文候选与 pgvector 精确向量候选分别可观测；权限、发布状态、版本和适用范围在排名前硬过滤，RRF 只融合过滤后的合法候选。
- [ ] 真实内部检索页面展示条目标识、版本、适用范围和片段位置，并覆盖桌面、窄屏、loading、empty、error 与索引过期状态。
- [ ] 在未修改 #189 的前提下运行冻结质量门并保存环境、revision、数据集哈希、各项指标与通过结论；未达标时诚实保存结果并保持 #167 及其下游消费票被阻塞，不降低阈值或无限调参。
- [ ] 模型、索引、数据库扩展或融合阶段不可用时停止知识结果，不以无来源内容填补；完整规范化门禁和对应真实 PostgreSQL/浏览器验收通过后才能交付。

## Blocked by

- #189

## Boundary

本票交付从本地模型到内部用户可见检索结果的完整纵向切片。中文消融与可选 ONNX 仍属于 #168，客户和客服 Agent 的知识消费仍属于 #169、#170。