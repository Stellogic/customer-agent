# #168 分层消融协议与交接（rag-layered-v2）

状态：**CODE_READY_NO_TESTS，仅本轮静态增量。** 2026-08-31 读取正式 [#149](https://github.com/Stellogic/customer-agent/issues/149)、[#168](https://github.com/Stellogic/customer-agent/issues/168)、[#190](https://github.com/Stellogic/customer-agent/issues/190) 后承接。规范来源是三张票据的正式分层修订；这不是重新设计检索或回答模型。

独立 Standards / Spec 静态审查均 PASS，0 项发现，详见 [双轴记录](../delivery/issue-168-layered-v2-review.md)。

本轮从本票已有提交 `facfd84632a0b2a23f500c48c4a432610e70597e` 继续，不复制前置，不同步尚未交付的 #190，不改其他 owner。当前只读参考 PR203 固定 `802a34310d4c01991ea480082a6025372da016a8` 的 `docs/implementation/issue-190-layered-interface.md`、`docs/eval/rag-layered-v2.md` 与 `knowledge_evaluation.py`，不是动态跟随前置分支。旧 [静态协议](issue-168-static-contract.md)、[v1 模板](issue-168-report-template.json)、#189 冻结资产、原始失败及 [11 项纯逻辑历史实测](../delivery/issue-168-pure-focused-plan.md) 均保留；历史实测只覆盖旧受测提交 `0ec0fb7`，不为本轮新代码背书。未回算或重标任何旧成绩。

## 检索和回答分别验收

| 层 | 指标与完整样本要求 | 负责方 |
| --- | --- | --- |
| 检索 | 同一完整冻结集，每路保留全部逐题结果；有答案 Recall@5 >= 0.90、MRR@5 >= 0.75；错误版本、范围、越权 Top-5 命中率均为 0%。无答案题完整执行并保留候选，不能因为它们非空而算错误拒答 | #190 提供公开执行/评分；#168 负责编排与消融 |
| 回答 | 无答案拒答 precision >= 0.90、recall >= 0.85；分别验收结构合法性、引用真实性、语义充分性 | #169/#170 各自知识回答路径，同一次 DeepSeek 调用判断充分性并生成回答或资料不足说明；#173/#174 汇总 |

检索分数只排序，不能由低分、空列表、logistic 或 reranker 分数推断语义充分性；本票不增加充分性模型、云调用或问答搜索入口。合法片段不等于能回答。权限失败、基础设施失败、合法无匹配须区分；服务异常抛出并保存局部证据，不当作正确拒答。合法无匹配可以是空 `results`，也不直接等于回答拒答。

只有合法的资料不足回答才计入回答层拒答。检索/供应商故障、格式失败不计正确拒答，不得删掉失败样本后宣称通过。#168 不生成或评分回答，报告的 `answer_evaluation.status=NOT_EVALUATED`、`metrics=null` 只是责任边界，绝不是回答 PASS。资料不足本身不自动转人工，故障/安全处理仍遵循正式规格；此处不实现 #169/#170 的行为。Spring 业务权威、客户引用和客服权限不变。

## 本票显式输入与版本隔离

- `report_template(..., protocol="rag-layered-v2")` 和 `run_ablation(..., protocol="rag-layered-v2")` 默认使用新版；schema 为 `knowledge-ablation-v2`，`evaluation_protocol=rag-layered-v2-retrieval`，`pass_scope=RETRIEVAL_ONLY`。报告的 dataset 仍叫 `rag-eval-v1`，因为题集没变；dataset 名称不能代替验收协议版本。
- 新版 `thresholds` 只含 K 和五项检索指标，数值直接来自 #189 未变资产；拒答的两个数值目标另列在 `answer_evaluation.thresholds`。不修改冻结 JSON、标签、哈希、模型 revision 或阈值。
- 回调仍为本票已有 `run_query(mode, EvalQuery)` 和 `metrics(rows)`，每路接收完整冻结集，不过滤 unanswered。固定参考已确认行包含 `id/kind/http_status/results/recall/reciprocal_rank/checked_prohibitions/violations`，加实际候选、schema、revision 等响应字段；不能复制融合分数给词法或稠密候选。
- 新版汇总必须恰好给出五项检索指标：`answered_recall_at_5`、`answered_mrr_at_5`、`wrong_version_top5_hit_rate`、`out_of_scope_top5_hit_rate`、`unauthorized_top5_hit_rate`。不能把 v1 汇总去掉两个键后当新版，也不能仅换标签；需要 #190 按新版执行与评分。代码会拒绝直接混入七项旧指标，但回调语义仍需集成审查及真实证据确认。
- 未执行模式保持 `NOT_RUN`；只跑部分模式为 `PARTIAL`；三路完成为 `MEASURED`，每路 `PASS/FAIL` 只覆盖检索层。局部错误仍保存已有行并抛出，不能以已有样本计算完成结果。报告完整计数须能由每路全部 `rows` 按 kind 复核。
- `protocol="rag-eval-v1"` 显式保留旧 schema、七项指标及旧行为，供历史协议使用；不是新版产品默认。`run_reference_rrf` 固定走这个旧入口，只适用于原参考 PR203@`5402bd4c438ff68fc9bbc4a01e55080b12499ce9` 的旧评分语义。将来 #190 替换公开实现后，必须复核该入口，不能拿新版模块冒充历史重现。
- 新旧运行输出使用不同路径，不覆盖旧报告。新 [证据模板](issue-168-layered-v2-report-template.json) 与旧模板并存；所有模型指标为空，不产生 PyTorch 合格、参数冻结或默认切换结论。

## 接口缺口与协调交接

最初向协调任务 `01a043aa-d724-7353-b6c5-9266277846d6` 报告新版评分接缝缺失；随后 #190 owner 提供上述固定提交，已只读核对并通知协调任务。接入仅为静态源码，不是前置质量通过或运行授权：

1. 新增 `run_layered_ablation`：复用公开 `run_query(base_url, query, expected_schema="knowledge-hybrid-v2")`，每个冻结查询仅请求一次，三路共用同一响应；`results` 为 RRF Top-5，`lexicalCandidates/vectorCandidates` 各为排名前硬过滤后最多 20 条候选。本票按原序取各路 Top-5，不重排或过滤分数；`score_candidates` 复用公开 `matches(hit, AllowedHit)`，独立计算该路 recall/rank/禁止命中，汇总直接委派 `retrieval_metrics(rows)`。单路计数归属由 #190 owner 明确为 #168，不复制检索器或融合评分值。保留完整原始候选和 HTTP 状态，RRF 行不改写；不增加 HTTP 框架。主分支尚无这些接口时运行会直接失败，不加载固定 SHA 的文件冒充已集成模块。
2. 预期无权身份的 HTTP 403 由 #190 返回明确状态与空候选，属于权限证据，不称 NO_MATCH；非预期 403、400、503 和其他服务异常由其公开入口抛出，本票保存 ERROR 后继续抛出。200 空候选只说明无匹配或请求 scope 与授权 scope 无交集，不是语义拒答。测试 stub 不证明服务鉴权行为；真实接线与质量仍等前置正式交付。
3. ONNX tokenizer/feature-model 导出适配仍归 #168，但可复用的公开加载/分词接缝尚未提供；本轮不重新实现编码器或访问 `_model/_tokenizer`，继续保留已审查的显式注入契约，集成时明确共享边界。`knowledge_embedding.py`、`knowledge_evaluation.py`、默认检索、模型准备、pyproject/uv.lock、Compose、门禁入口继续归 #190。

## ONNX 范围完整保留

仍需在合格 PyTorch 基线上完成固定 feature-extraction 导出、查询指令、CLS pooling、L2、截断、动态 batch/sequence、512 维向量差异与含版本/片段的 Top-K 排序一致性。`compare_consistency` 的两端空列表只表示排序一致，单侧空列表表示排序差异，不表示回答层拒答；计算公式与原数值/排序容差要求未改变。

冷启动、吞吐、batch P50/P95、OS 峰值 RSS、同硬件/线程/输入/batch/warmup/repeat 条件、交替多次比较与环境/原始结果留存均不减少，不能从权重体积推断资源。容差须在真实结果前单独审查；排序一致且资源收益明确后仍需正式决策才能切默认，否则保留 PyTorch。本阶段不宣称 PyTorch 已合格。词法不足时的 pg_trgm/预分词/PGroonga 证据比较、混合收益可复现后才冻结参数的要求继续保留。

## 静态验证与后续放行

新增测试源码覆盖新版阈值分层、完整冻结题调度、无答案题非空候选保留、检索门槛与权限违规判定、拒绝旧指标误标新版、单路独立命中/排名/版本违规计数、每题只请求一次与 Top-5 截取、HTTP 状态保留与异常传播；旧版模板/调度/RRF 测试保留。stub 只验证编排，不是合法候选或质量证明。仅更新一致性测试名称及注释，不缩减断言。

本轮未运行测试、格式化/格式检查、lint/type、构建、模型准备/下载/推理/导出、真实评测、Docker/Compose、完整门禁或 CI；不查询、获取或持有测试锁。#190 持唯一运行窗口。本票只做双轴静态 CR，结论仅限上述已实现范围，不沿用旧 11 项 PASS。

集成与真实比较仍须 #190 **rag-layered-v2 检索质量 PASS + 最终本地完整门禁 PASS + 合入 main + Issue 关闭**。随后同步最新 main、核对接口/归属/迁移（本票未新增迁移）、增量 CR，并获得明确串行运行窗口后持锁执行本票验证及最终 `pwsh ./scripts/check.ps1 -Issue 168`。新版规格发布、静态 CR PASS 或锁 FREE 均不自动解阻。当前保持 Draft PR，不 Ready、不合并、不关票；CI 关闭。未来获批运行结束仍须通知 `LOCK_RELEASED`。
