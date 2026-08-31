# #168 主线集成与真实验证结果

2026-09-01：协调任务已回读 #190 合入关闭与 main `8bd86e6`，本票已合入该主线，merge 提交 `737382c`，无冲突。本票旧实现保留，不复制前置分支。协调明确将 `knowledge_embedding.py` 的最小公开加载/分词接缝交由 #168 唯一补齐；#169 仍拥有业务授权与 Agent 检索接入，本票不改那些区域或默认检索方法。

随后协调将唯一运行窗口从 #169 移交 #168，授权连续准备依赖、聚焦、真实消融与 ONNX 比较、修复/双轴 CR 及最终交付。下文保留执行前协议，并记录逐轮真实结果。BUSY 立即停止、RECOVERY_REQUIRED 升级协调，不因 FREE 自行扩大范围。

## 本轮最小接线

- 编码器公开 `load_tokenizer`、`load_feature_model`、`tokenize_texts`，旧 `OfflineBgeEncoder.encode` 复用它们，查询指令、CPU/eager、CLS、L2、截断及默认检索不变。校验仍使用 #189 已有文件清单，不新增一套哈希协议。
- `export_bge_model` 在图中保留 CLS/L2，并复制五份小型冻结分词文件。`OnnxBgeEncoder(Path)` 与原编码器使用同一文本接口；分词加载不读取 PyTorch 权重，也不访问原编码器私有成员。
- `run_layered_ablation` 直接消费已合入的 `run_query(expected_schema="knowledge-hybrid-v2")`、`matches`、`retrieval_metrics`。当前主线无权 scope 是 403，不再沿用旧参考 `802a343` 的 200 空交集行为。旧协议、报告及历史 11 项测试证据保留。
- `knowledge_onnx_evaluation` 在同一完整冻结题与 Spring 真实授权候选上比较向量和 Top-5。默认稠密 SQL 返回过滤后的最多 20 条，无分数阈值，因此小于 20 时可覆盖该题整个授权语料；达到上限时停止，不能只比 PyTorch 已选出的子集。它只比较给定向量，不另造服务检索器或权限过滤器。本地 PyTorch 排序须先与实际服务排序一致，才能解释 ONNX 排序结果。拒绝样本保留 HTTP 状态及空排序，不计回答拒答。

## 先固定容差，再看结果

本次为同权重 FP32 图导出，不量化。独立协议 [issue168-fp32-onnx-v1](../eval/issue-168-onnx-tolerance.json) 在真实比较之前写入并交双轴静态审查：逐坐标绝对误差 <= `1e-4`，余弦距离及 L2 范数偏差 <= `1e-5`；Top-5 重合与完全顺序一致率均要求 `1.0`，不允许排序回退。数值容差用于容纳不同 CPU 算子浮点舍入，不声称由官方保证；最终还必须满足严格排序要求。它不改变 #189 的题、标签、模型协议或质量门槛；失败时保留结果，不根据结果放宽容差。

样本覆盖完整冻结查询和实际全部授权知识片段、query/document、batch 1/8/32、短文本和超过 512 token 的长文本。查询/文档都验证右截断；ONNX 的输入处理与原编码器共用。资源比较对两个后端分别在新进程测量，包含导入/校验/加载/首编码，按相同硬件、单线程、文本顺序、batch8、warmup1/measured3 执行；query/document 各做三组配对并交替顺序。记录所有批次延迟、吞吐、P50/P95、峰值 RSS、软件环境。OS 文件缓存不清理，不能称磁盘冷缓存。

`MEASURED` 仅表示采集完成，不等于 ONNX 合格；一致性 FAIL 必须保留。资源收益由完整配对结果解释，不因任何单个指标改善自动切默认。本票计划保留 PyTorch 默认；没有一致性和明确资源收益时更不能切换。RRF 候选数及排序参数不调整；消融收益必须复现后才能提出冻结决策。

## 依赖及官方依据

新增可选 `onnx` dependency group：`onnx==1.20.1`、`onnxruntime==1.24.2`；常规 runtime/dev 组不额外安装 ONNX，不改 Compose 或 Dockerfile。锁文件仅新增二者及 `flatbuffers/ml-dtypes`，原依赖版本不升级。正式 ONNX 窗口显式安装该组；常规完整门禁的可选合成图测试可缺包跳过，但不能用该跳过代替本票 ONNX 的真实验证。

复用 [Transformers tokenizer 的离线加载和 NumPy/PyTorch 张量输出](https://huggingface.co/docs/transformers/v4.57.1/main_classes/tokenizer)，不引入第二套 tokenizer。[PyTorch 2.10 导出接口](https://docs.pytorch.org/docs/2.10/onnx.html) 已支持本模块使用的 opset17 与 dynamic_axes；保留既有小型导出包装，不引入 Optimum。[ONNX 1.20.1](https://pypi.org/project/onnx/1.20.1/) 与 [ONNX Runtime 1.24.2](https://pypi.org/project/onnxruntime/1.24.2/) 提供本轮固定版本；版本存在不等于本项目已验证兼容，兼容性以本票实际导出/执行为准。

## 首轮依赖准备记录

`issue168-deps-20260901a`：本票 uv 0.8.22 工具安装成功；人为指定 `uv lock --no-build` 排除既有 forbiddenfruit 源码依赖，解析报告约束冲突；未同步项目环境、未模型运行，原锁文件未变。finally 释放现有锁，已向协调发送 LOCK_RELEASED。后续重试允许正常构建既有依赖，不降低版本、不换模型。

`issue168-deps-20260901b`：去掉人为的 no-build 后解析成功，115 个依赖包，原包版本不变；本票 `.local/issue168-runtime-venv` 安装完成。两轮原始日志见 [a](evidence/issue168-deps-20260901a/phase.json)、[b](evidence/issue168-deps-20260901b/phase.json)，两轮锁均已释放并通知协调。

## 聚焦与执行前双轴审查

- `issue168-focused-20260901a`：33 项通过，类型通过；9 个文件格式化后，17 项 lint 使整轮 FAIL，失败日志保留。
- `issue168-focused-20260901b`：33 项通过，lint/type 通过；仅 ONNX 文件混合行尾使格式检查 FAIL。统一行尾后 Git 内容 diff 为空，不修改逻辑或容差。
- `issue168-focused-20260901c`：33 项通过、0 跳过，12 文件格式检查与 lint/type 全通过；受测代码 `a393f88`。包含合成 feature model 的实际导出及动态 batch/sequence 执行，但不是 BGE 质量证明。TorchScript 导出路径有 2 条已知弃用 warning，没有当成失败或隐去。

三轮均通过现有锁执行并释放，通知已送达。证据分别为 [a](evidence/issue168-focused-20260901a/phase.json)、[b](evidence/issue168-focused-20260901b/phase.json)、[c](evidence/issue168-focused-20260901c/phase.json)；各目录含 pytest/JUnit、格式、lint、类型与环境原文。原模板的 `model_calls=0` 指没有外部模型/BGE 调用，合成图的本地 Torch/ONNX 运算确已执行，不把它当真实 BGE 指标。

两个独立代理在真实 BGE 执行前审查 `737382c...a393f88`，Standards PASS / Spec PASS，均 0 项发现；特别确认 FP32 容差可按该协议预先冻结。它们没有运行测试或接触真实结果，静态 PASS 不替代后续质量和完整门禁。

## 真实消融：通过检索质量门，但没有混合收益

`issue168-runtime-20260901a` 在代码 `a393f88865dd46195c1dba682a1115ccdd722173`、主线 `8bd86e618e1a282d647cc234dcb445035f8cb23a` 上执行。独立 Compose 启动 PostgreSQL、迁移、Spring、Agent 与前端，真实请求 Spring；没有替换检索或编码器。相对主线无新增/修改迁移，实际初始化迁移成功。冻结模型 revision 为 `7999e1d3359715c523056ef9478215996d62a620`，数据集 SHA-256 为 `d2d5efdae565395c1dc722e14f66077558575152e23c5c8fbea58b7ebcfd2fe5`。仅只读挂载已有冻结模型，没有下载或付费模型调用。

前置 PyTorch 质量检查 `PASS`，embedding contract `PASS`。随后三轮各执行全部 64 题，各路线独立评分，三轮汇总完全相同：

| 路线 | Recall@5 | MRR@5 | 错版本/越范围/无权命中率 | 检索质量 |
| --- | ---: | ---: | --- | --- |
| 词法 | 0.944444 | 0.902778 | 0 / 0 / 0 | PASS |
| 稠密 | 0.944444 | 0.825000 | 0 / 0 / 0 | PASS |
| RRF | 0.944444 | 0.868056 | 0 / 0 / 0 | PASS |

12 道无答案题：词法 4 题各返回 2 条候选，其余为空；稠密 12 题各返回 8 条候选；RRF 12 题各返回 5 条结果。原始逐题候选、分数、实际 HTTP 状态均归档。不能由这些分数认定存在可回答证据，也不计算语义拒答 PASS；回答质量为 `NOT_EVALUATED`，由 #169/#170 承接。

RRF 相对最佳单路的 MRR 低约 0.034722，Recall 没有提高，故**不满足可复现混合收益条件，不冻结或调优参数**。本轮记录的 candidate_limit=20、rrf_k=60、top_k=5 仅是既有运行值，不是优化推荐。现有词法已含写入前 CJK 分词并通过冻结质量门，未触发召回不足时的扩展比较，不引入 pg_trgm 或 PGroonga；本票也不切换既有默认检索路线。

## 真实 ONNX：一致性通过，保留 PyTorch 默认

完整对照有 222 组向量、64 题排序；本地 PyTorch 与真实 Spring 排序 64/64 一致。当前授权候选全部小于服务上限，未将截断候选子集当完整语料。短文本、长文本右截断及 batch 1/8/32 均通过。

| 指标 | 实测 | 预先固定要求 |
| --- | ---: | ---: |
| 最大逐坐标绝对误差 | 2.477318048477173e-7 | <= 1e-4 |
| 最大余弦距离 | 1.2045919817182948e-12 | <= 1e-5 |
| 最大范数偏差 | 3.50593070241878e-7 | <= 1e-5 |
| 最小 Top-5 重合率 | 1.0 | 1.0 |
| 完全顺序一致率 | 1.0 | 1.0 |

一致性 `PASS` 只覆盖上述冻结样本，未推广到任意语料。导出 manifest 中的 `consistency_status/resource_status=NOT_RUN` 是导出时快照；后续结果以同目录 `onnx-result.json` 为准，没有用导出成功代替验证。

资源环境：Windows 11 10.0.26200、AMD64 Family 25 Model 117 Stepping 2、16 逻辑 CPU（编码各限 1 线程）、Python 3.13.13、torch 2.10.0+cpu、transformers 4.57.6、ONNX 1.20.1、ORT 1.24.2、NumPy 2.5.2。下表为每组三次独立新进程结果的算术平均；P50/P95 列是各进程分位数的平均，不是合并样本的分位数。query=false 用同一组冻结文本去掉查询指令以控制工作量，不冒称生产文档长度分布。

| 输入模式/后端 | 首结果冷启动 ms | 峰值 RSS MiB | batch8 P50 ms | batch8 P95 ms | 文本/秒 |
| --- | ---: | ---: | ---: | ---: | ---: |
| query / PyTorch | 18177.98 | 453.54 | 99.73 | 114.02 | 80.20 |
| query / ONNX | 18778.65 | 493.78 | 80.02 | 89.80 | 100.66 |
| document / PyTorch | 17819.57 | 454.19 | 56.72 | 70.35 | 139.53 |
| document / ONNX | 17626.79 | 494.61 | 45.57 | 58.13 | 174.75 |

12 个进程均 `MEASURED`。ONNX 吞吐约改善 25%，但 RSS 多约 40 MiB，冷启动没有稳定改善；OS 文件缓存不受控，也没有整机内存或在线端到端延迟结论。综合收益不支持本票默认切换，**保留 PyTorch，ONNX 仅作可选离线优化**。资源数字来自实测进程，不由模型文件大小推算。没有量化、参数试探或放宽容差。

## 证据、复现与正式交付边界

原始 [运行阶段及清理记录](evidence/issue168-runtime-20260901a/phase.json)、[PyTorch 质量](evidence/issue168-runtime-20260901a/quality.json)、[三轮消融汇总](evidence/issue168-runtime-20260901a/ablation.log)、[ONNX 完整对照](evidence/issue168-runtime-20260901a/onnx-result.json) 及同目录原始消融 JSON、构建/服务/清理日志入库；不提交模型权重或 ONNX 图。总耗时 1022.260204 秒，环境 `CLEANED`，锁已释放并向协调发送 `LOCK_RELEASED`。

复现须先获得协调窗口并使用现有测试锁；在 agent 环境执行 `uv sync --frozen --group onnx`，使用按 #189 校验通过的本地模型、已初始化冻结知识的真实 Spring 服务。归档的 `run-ablation.py` 通过 `ISSUE168_BASE_URL/OUTPUT/HEAD/BASE` 显式传参并保存三轮结果。然后运行以下模块（路径按本机填写，不能对未初始化服务或未校验模型套用结果）：

```text
python -m baseline_agent.knowledge_onnx_evaluation --model-directory <冻结模型目录> --onnx-directory <本票输出目录> --ablation <ablation-0.json> --tolerance <repo>/docs/eval/issue-168-onnx-tolerance.json --output <onnx-result.json> --hardware-id <同机标识> --head-sha <HEAD> --base-sha <origin/main>
```

本记录中的代码与真实结果已完成；正式合入仍以最终提交的增量 Standards/Spec PASS、完整 `pwsh ./scripts/check.ps1 -Issue 168` 和 PR #206 的门禁证据为准。完整门禁后不再修改受版本控制内容；最终 run/head/base 和合入回读留在 PR/Issue 交付记录，不用旧受测提交替代最终门禁。
