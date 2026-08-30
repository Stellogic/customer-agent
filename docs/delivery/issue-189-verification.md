# Issue #189：冻结 rag-eval-v1 中文检索质量基线

## 范围与诚实边界

本票只冻结可复核的中文检索评测资产、协议和内容哈希，作为 #167 后续实现不可污染的质量门。没有实现 Embedding 加载、pgvector 查询、RRF、ONNX 或内部检索页面；那些工作明确留给 #190。普通门禁与本票测试都不联网、不读取生产数据、不调用 DeepSeek。

## 冻结内容

- 数据集 `rag-eval-v1`：64 条查询（36 有答案、12 无答案、12 错误版本或不适用范围、4 条独立越权）。
- 有答案查询覆盖每个当前发布知识条目 12 条，并包含口语/省略与错别字、简称或同义表达。
- 每条有答案样本记录允许命中的条目、版本、适用范围与必要片段。
- 门槛预先固定：有答案 Recall@5 `>= 0.90`、MRR@5 `>= 0.75`；无答案 precision `>= 0.90`、recall `>= 0.85`；错误版本、不适用范围和越权条目 Top-5 命中率 `0%`。
- 协议固定 `BAAI/bge-small-zh-v1.5` revision `7999e1d3359715c523056ef9478215996d62a620`，以及查询指令、CLS pooling、L2 normalization、512 最大长度、右侧 `longest_first` 截断和 512 维输出。
- 内容哈希 `d2d5efdae565395c1dc722e14f66077558575152e23c5c8fbea58b7ebcfd2fe5`；`original_content_sha256` 相同，纠错账本为空。

说明与审查步骤见 [`docs/eval/rag-eval-v1.md`](../eval/rag-eval-v1.md)。机器可读资产在 `agent/src/baseline_agent/rag_eval_v1/`。

## 验证命令

- 聚焦 Agent 测试：`pwsh ./scripts/check.ps1 -Component agent -SkipAcceptance -Issue 189`
- 本票没有运行检索质量门，也没有下载模型权重。
