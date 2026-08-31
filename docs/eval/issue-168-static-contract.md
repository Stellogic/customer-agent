# #168 隔离静态预开发契约

本文件记录最初的消融、ONNX、一致性、资源与测试源码静态契约。后续获批完成的纯逻辑聚焦验证见 [验证记录](../delivery/issue-168-pure-focused-plan.md)；它不涉及模型或真实检索。仍没有 PyTorch 质量结论、ONNX 指标或参数冻结结论，也没有默认切换。报告模板中的 `null` 表示模型评测未运行，不是零。

## 基线、归属与事实源

- 当前开发起点：`origin/main` = `2ca9d097da1f93d4cdf3eeef347c62cf51f0e058`。
- 最新任务边界：[Issue #168](https://github.com/Stellogic/customer-agent/issues/168)，再次读取于 2026-08-31；本文件补充阶段说明，不改写原始验收条件。
- 冻结资产来自已在 main 的 #189：[`rag-eval-v1.md`](rag-eval-v1.md)。查询、答案、模型 revision、编码协议和质量阈值均未修改。
- 前置只读参考：[PR203](https://github.com/Stellogic/customer-agent/pull/203) 本轮固定 `5402bd4c438ff68fc9bbc4a01e55080b12499ce9`，替代首轮参考 `4317fd35897d2b2665dff0d21219a16cd23ad5d6`。本分支沿用原起点，未集成该前置。不检出/复制其实现，不访问编码器私有成员。
- #190 继续独占 `knowledge_embedding.py`、`knowledge_evaluation.py`、默认检索、模型准备、`pyproject.toml`、`uv.lock`、Compose 和门禁入口；本阶段不改这些文件。
- #168 只新增 `knowledge_ablation.py`、`knowledge_onnx.py`、`knowledge_consistency.py`、`knowledge_resources.py`、对应独立测试和本说明/报告模板。

## 显式接缝和留待集成的部分

| 模块 | 当前输入/职责 | 必须等待的真实接线 |
| --- | --- | --- |
| 消融 | `run_ablation(run_query, metrics, environment, parameters, output)`，逐模式逐冻结题执行，保留原始行并复用传入的评分汇总；失败保存局部证据并抛错 | 适配器 `run_query(mode, EvalQuery)` 必须给出该路独立的合法 Top-5、拒答结果和 #190 评分字段；当前 #190 的 `run_query(base_url, query)` 没有模式参数。不能直接截取两路候选再继承混合的 recall/MRR。需要复用 #190 评分/检索接缝，不能复制实现 |
| 导出 | `export_feature_extraction(..., verify_model_directory, feature_source)` 先调用校验器，再把调用者提供的 CPU feature model 包装为 CLS + L2 图 | 校验器应直接使用 #190 的 `verify_model_directory`。`feature_source(verified_path)` 返回本地 CPU/eager feature model 和 BERT 三项示例张量；当前公开 `OfflineBgeEncoder` 未暴露此接缝，加载适配必须在集成时明确 |
| ONNX 执行 | `OnnxFeatureExtractor.extract(tokens)` 接收 int64 的 `input_ids/attention_mask/token_type_ids`，返回 512 维向量，只用 CPU provider | 它不是 `encode(texts, query=...)`。文本/tokenizer 适配须复用经批准的编码规则，并验证查询指令只加一次、文档无指令、512 右截断、padding/batch 一致；不能假装现在已经接上 #190 |
| 一致性 | `compare_consistency` 接收标识对齐的两端向量和权威检索排序，输出逐样本差异、Top-K 重合与完全顺序一致率 | 真实样本必须覆盖所有冻结查询/语料，区分 query/document、短文本/长截断与多 batch；排序标识含条目、版本、片段。相同空列表表示两边同拒答，一边空则不一致。它只判断传入样本，不重做检索或代替质量门 |
| 资源 | `measure_encoder(module:factory, model_directory, workload, timeout_seconds, hardware_id)`；工厂返回符合 `encode(list[str], query=bool)` 的对象 | PyTorch 可直接指向 #190 的 `baseline_agent.knowledge_embedding:OfflineBgeEncoder`；ONNX 工厂需等待文本适配。模块本身没有 CLI、模型下载或门禁入口，只有获批持锁的外层入口才能调用 |

以上缺口已通知协调任务 `01a043aa-d724-7353-b6c5-9266277846d6`。输入契约是 #168 的独立适配要求，不冒充 #190 已承诺的新接口。本阶段不补共享接线，剩余独立工作可以继续。

消融适配器返回字段沿用 #190：`id/kind/results/recall/reciprocal_rank/checked_prohibitions/violations`，可保留候选及 HTTP 状态。`results` 必须来自各自完成权限、版本、发布状态、适用范围过滤及拒答判定后的该模式；服务异常必须抛出。汇总直接传 #190 `metrics`，不得改冻结门槛。环境记录应含实际代码 SHA、前置 SHA、PostgreSQL/pgvector、硬件和依赖版本；参数记录每路候选数、RRF 常数、拒答阈值、排序/同分规则和重复运行标识。当前编排只报告每路质量是否达到 #189 阈值，不宣布混合收益可复现。

## 2026-08-31 固定接口复核与有限适配

本轮唯一运行代码增量是 `run_reference_rrf(base_url, environment, parameters, output)`：延迟导入 #190 的 `knowledge_evaluation`，把冻结查询原样交给公开 `run_query(base_url, query)`，再直接调用其 `metrics(rows)`。不重算评分、不截取候选、不把融合分数改名为单路分数。主分支尚无该前置模块时，调用会因缺少模块失败；不加载固定提交文件作为运行代码，也不复制前置。

`run_ablation` 仍默认执行完整三路；新参数 `modes` 允许显式选择已具备接口的模式。RRF 适配只传 `("rrf",)`，即使所选模式执行完成，报告整体也只能为 `PARTIAL`，词法和稠密两路的 `rows=[] / metrics=null / status=NOT_RUN` 不变。异常时 RRF 和整体为 `ERROR`。这些是将来调用后的行为约定；本轮未实际调用，真实状态仍为 `NOT_RUN`。

固定提交的接缝证据如下：

| 源文件/公开接口 | 只读确认 | 本票边界 |
| --- | --- | --- |
| `knowledge_evaluation.run_query(base_url, query)`、`metrics(rows)` | 仍只对 `results` 评分，未接受模式参数；评分仍内嵌在 `run_query` | 只完成 RRF 调用适配，不将 `lexicalCandidates/vectorCandidates` 继承融合 recall/MRR |
| `KnowledgeRetrievalService.developmentCandidates` 和 `/api/internal/knowledge/development-candidates` | 有分路与融合候选、特征；线上 `search` 另做 answerability 判定后才返回最终 `results` | 候选不是各路独立最终答案/拒答，不能直接拿来声称三路无答案评测已接通 |
| `knowledge_embedding.load_model_protocol()` | 新公开接口只读取原始 `model` 配置，包含 tokenizer 大小写和中文切分设置 | 可作为后续完整模型元数据来源；配置不能替代分词器或 feature model，不因此声称 ONNX 文本适配完成 |
| `OfflineBgeEncoder.encode(texts, query=bool)`、`knowledge_embedding_graph.embed` | 只返回向量；模型与分词器仍为私有成员 | 不访问 `_model/_tokenizer`，本轮 ONNX 运行实现保持不变 |

尚缺的最小接口需求（**仅为请求，未实现或依赖这些假定签名**）：

1. #190 提供公开的模式执行/评分入口，例如扩展 `run_query(base_url, query, mode=...)`，返回该路实际排序、独立拒答、recall/MRR 和违规字段，保留现有融合默认；或公开独立的 `score_results(query, hits)`，同时明确单路最终候选与拒答接缝。单独一个评分函数不能解决拒答来源问题。无需另造检索器或改变现有默认。
2. 从现有编码实现提取可共用的本地加载/分词函数：分词器加载与 `tokenize(tokenizer, texts, query, return_tensors)`、CPU/eager feature model 加载。ONNX 文本运行端应能只加载分词器，不能为了调用分词而同时加载整份 PyTorch 模型，污染资源比较。具体签名由 #190/协调任务确认；当前只保留既有显式输入契约，不自行写私有适配器。

新增测试源码只验证公开调用委派、结果行不改写、未执行模式保持空以及错误传播；stub 仅用于单元测试，不能视作真实分路验证。模板参考 SHA 已更新，指标仍为空。协调任务提到的 c5 开发 PASS 不构成 #190 冻结质量或正式交付通过；本轮没有运行或独立复核 c5 评测。

## 导出实现选择和依赖

复用 PyTorch 2.10 官方 `torch.onnx.export`，显式选择 `dynamo=False`/`dynamic_axes`、opset 17、单文件权重和动态 batch/sequence；这是该版本已提供的导出路径，不自动尝试另一条路径。相比另引入 Optimum/Sentence Transformers，此处只需要小型固定 BERT 图包装，不增加另一套模型加载/检索体系。CLS 与 L2 在图内，避免 ONNX 只输出 token hidden states 后遗漏 pooling。保存固定模型协议、图 SHA-256、框架版本与导出设置；ONNX checker 成功只表示图结构可检查，不代表真实 BGE 导出/数值通过。[PyTorch 2.10 文档](https://docs.pytorch.org/docs/2.10/onnx.html)

CPU 会话显式固定单线程和 `CPUExecutionProvider`，禁用 provider fallback；运行前核对导出 manifest 和文件哈希。[ONNX Runtime Python API](https://onnxruntime.ai/docs/api/python/api_summary.html)

目前主分支尚无所需模型依赖。模型侧依赖沿用 #190 已选版本；本模块额外需要 `onnx`、`onnxruntime`、`numpy`，**版本兼容验证与锁文件接入待 #190 交付及协调允许**。本阶段没有安装、锁定或声称这些版本已兼容。使用延迟 `import_module`，模块的只读导入不加载推理框架；缺包在显式运行时直接失败，没有 fake fallback。

## 原验收范围及仍缺证据

1. 在相同冻结题上重复报告词法/稠密/RRF 的 Recall@5、MRR@5、无答案 precision/recall、错误版本/范围/越权命中率。混合收益需多次可复现后才能冻结候选数、RRF 和排序参数。
2. 如果词法召回不足，依据逐题失败证据比较 `pg_trgm`、写入前中文分词和 PGroonga；本阶段不新增扩展、不自行调整参数。
3. 对真实固定 revision 执行 ONNX 导出，验证查询/文档的指令、pooling、L2、截断、批次以及向量差异和 Top-K 排序一致性。#189 **没有 ONNX 数值/排序容差**；`ConsistencyTolerance` 无默认值，必须在看到真实比较结果之前记录独立审查的容差协议。单测里的 `synthetic-test-only` 不是验收阈值。
4. 冷启动定义为新进程创建前至首次编码返回，包含 Python 启动、导入、模型校验/加载、首推理；文件系统缓存未清理，不能声称磁盘冷缓存。另列 import/load 和 first encode。warmup 与首推理不进入稳态 P50/P95；P50/P95 是 batch 延迟，吞吐是文本/秒，保留每次 batch 的原始延迟。资源基准不是端到端检索延迟。
5. 两端必须在同一硬件、CPU 限额、同一文本顺序、batch、query 标志、线程和 warmup/repeat 下顺序运行，多次交替先后顺序，并保存两端软件环境与 workload hash；不得拿不同条件比较。工厂负责落实框架单线程，报告 `threads=1` 表示请求的配置，真实配置须集成核对。
6. 峰值 RSS 取独立工作进程的 OS 高水位，含加载/首推理/warmup/测量：Windows `PeakWorkingSetSize`、Linux `ru_maxrss * 1024`、macOS `ru_maxrss`。不包含外部服务，不以采样峰值或权重体积替代。[Windows API](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters)、[Python resource](https://docs.python.org/3.13/library/resource.html)
7. 排序容差满足且资源收益明确，仍需要正式决策才可切默认；未通过或无证据时保留 PyTorch。当前所有模块都不修改默认。
8. 仓库证据必须含环境、模型 revision、数据集 hash、代码 SHA、原始逐题/资源结果、容差来源和通过/未通过结论；失败结果也要保存。模板见 [`issue-168-report-template.json`](issue-168-report-template.json)。运行产物/权重放 `.local/`，只把人工检查后的证据提交到仓库。

## 测试源码与正式集成

测试源码覆盖三路/冻结题调度、部分失败证据、排序逆序/版本差异/单边拒答、非有限输出、真实子进程计时与 RSS 边界，以及小型合成 feature model 的真实 ONNX 动态维度导出。后续独立窗口仅运行消融编排及纯数值一致性共 11 个既有测试并通过；ONNX 和资源测试仍未运行。合成图测试缺可选依赖会 skip；这不是 BGE 质量/性能证据，正式 ONNX 验收不允许用 skip 代替通过。

#190 必须先冻结质量实测 PASS、最终本地完整门禁 PASS、PR 合入 main 且 Issue 关闭。之后本票同步最新 main，核对以上公开接口与归属、迁移编号（本票未新增迁移），补真实接线/依赖和必要增量 CR。只有协调任务明确放行后才可持锁执行聚焦验证与最终 `pwsh ./scripts/check.ps1 -Issue 168`。锁 FREE 不放行、不轮询；获批运行结束向协调任务发 `LOCK_RELEASED`。GitHub Actions 关闭，不运行或等待 CI。当前阶段不得 Ready、合并或关票。
