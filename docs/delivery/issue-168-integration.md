# #168 主线集成与真实验证准备

2026-09-01：协调任务已回读 #190 合入关闭与 main `8bd86e6`，本票已合入该主线，merge 提交 `737382c`，无冲突。本票旧实现保留，不复制前置分支。协调明确将 `knowledge_embedding.py` 的最小公开加载/分词接缝交由 #168 唯一补齐；#169 仍拥有业务授权与 Agent 检索接入，本票不改那些区域或默认检索方法。

随后协调将唯一运行窗口从 #169 移交 #168，授权连续准备依赖、聚焦、真实消融与 ONNX 比较、修复/双轴 CR 及最终交付。当前文档只是执行前协议，不是结果；实际运行逐轮保留到 `.local/issue168-*`，归档后另附结果。BUSY 立即停止、RECOVERY_REQUIRED 升级协调，不因 FREE 自行扩大范围。

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
