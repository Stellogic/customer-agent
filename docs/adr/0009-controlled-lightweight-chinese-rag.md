---
status: accepted
---

# 引入受控的轻量中文 RAG

第一阶段使用仓库内版本化中文 Markdown 知识条目，为 Agent 和客服辅助提供带条目标识、版本、适用范围与片段位置的真实检索和引用能力。RAG 只解释一般规则与客服知识；订单、物流、支付、补偿资格、金额和执行结果仍由 Spring 权威业务接口提供。DeepSeek 继续作为唯一负责调查规划、结论形成和回复的对话模型，本地 Embedding 模型只负责文本向量化。

首选 Embedding 候选为固定 revision 的 `BAAI/bge-small-zh-v1.5`。官方资料确认其采用 MIT 许可证、约 2400 万参数、单份 Safetensors 权重约 95.8 MB，并面向中文检索。模型由 Python/LangGraph 服务在本地 CPU 加载，权重不提交进 Git，构建或准备阶段按固定 revision 和校验值取得，运行阶段不依赖临时联网下载。先使用 PyTorch/Safetensors 建立 pooling、归一化、查询指令和检索质量的正确性基线；ONNX Runtime 只有在导出、向量与 Top-K 一致性、冷启动、延迟和峰值内存验收通过后才可成为默认。

混合检索首选 PostgreSQL 全文检索、pgvector 稠密向量检索和 RRF 融合，不先引入独立搜索服务。PostgreSQL 内建全文检索是最小基线，但不预先承诺连续中文自然语言的分词与召回质量；必须使用项目客服语料评测词法、向量和混合方案。若基线不达标，再根据证据选择 `pg_trgm`、写入前中文分词或 PGroonga。编辑、审核和发布后台第一阶段按原型保留并明确显示“开发中”，不得伪造成功；查看、检索、版本和引用必须连接真实数据。

证据与尚待实测边界见 [`docs/research/lightweight-chinese-rag-evaluation.md`](../research/lightweight-chinese-rag-evaluation.md)。

2026-08-31 用户确认补充：检索分数只负责候选排序，不再作为语义可回答性的门控。问题和授权片段交给负责生成回答的同一次 DeepSeek 调用判断充分性并回复；默认不增加独立判断模型或调用。检索与回答分别验收，实施归属和新旧口径边界见 [rag-layered-v2](../eval/rag-layered-v2.md) 及正式 #149。此修订保留旧冻结资产与失败证据，不表示旧质量门已通过。
