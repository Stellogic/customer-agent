# Issue #190 实现边界与验证记录

基线：`782c004f1e3beaa03450c4e3edae3f820a456cb1`。#189 的 `rag-eval-v1` 文件不修改。

## 决策与证据

- 使用 [BGE 官方模型说明](https://huggingface.co/BAAI/bge-small-zh-v1.5) 的 Transformers/CLS/L2 路径；实际编码参数、revision 和文件哈希全部读取冻结协议。不引入 FlagEmbedding、ONNX 或额外搜索服务。
- 使用 [PyTorch 官方 CPU wheel](https://download.pytorch.org/whl/cpu/torch/)；CPU、eval、确定性算法和单线程推理，无远程代码、无运行时模型下载。模型准备命令与运行加载分离。
- [pgvector 官方说明](https://github.com/pgvector/pgvector) 支持精确余弦距离与 PostgreSQL 全文检索融合。使用无 ANN 索引的精确扫描；合法候选物化后分别排名，以 RRF 常数 60 融合。未引入中文分词/消融，留给 #168。
- 新增 `/api/internal/knowledge/search`，保留 #166 的目录与历史审计接口。Spring 会话确定读权限；请求的范围只能收窄身份范围。Python 不取得业务数据库凭据，只通过已有私有、认证的 LangGraph 服务提供批量向量化。
- 索引启动构建在目录初始化之后执行，绑定目录 generation、正文和模型 revision。读取发现构建失败、代次不符、缺向量时返回 503，不退回词法结果。
- 无答案判定预先采用最高向量相似度 `0.80`，不因冻结题实测结果修改；RRF 不作为置信度。此值不是质量通过声明。冻结门不通过则保存失败证据并阻塞下游。

## 验证边界

沿用 Issue 明确要求的外部边界：编码接口的离线/维数/确定性契约，Spring HTTP 检索接口的真实 PostgreSQL 权限与版本过滤，真实浏览器页面状态，冻结评测查询。测试不得把内部方法调用次数当业务正确性。

当前共享锁曾查询为 #164 BUSY；尚未运行测试、构建、模型推理或质量评测。最终完整门禁和合入需要协调任务明确放行；本文不是 GATE_READY 或完成证明。

## 准备与执行（必须持共享锁）

1. 使用 `pwsh ./scripts/prepare-knowledge-model.ps1 -Uv <uv可执行路径>` 下载冻结文件，逐文件校验。默认保存在被 Git 忽略的 `.local/models/bge-small-zh-v1.5`。可用 `KNOWLEDGE_MODEL_HOST_PATH` 指向另一只读准备目录；不复制进镜像。
2. 数据库使用官方 `pgvector/pgvector:0.8.6-pg18-bookworm`，初始化脚本由管理员安装扩展。已有数据库需要 DBA 安装扩展；迁移角色和应用角色不提升权限。
3. 完整 `pwsh ./scripts/check.ps1 -Issue 190` 的 smoke 阶段执行冻结质量门，浏览器阶段执行 #190 的真实会话、真实数据库及桌面/窄屏验收。单独质量门是继承锁的子入口，不能裸跑绕锁。
4. 原始逐题结果、两路候选、指标与环境保存到 `.local/gate-evidence/<runId>/rag-eval-v1-result.json`；正式交付时另保存审查用摘要。ERROR 与 FAIL 都阻止交付。

评测进程仅临时取得 `spring_fixture` 的知识语料只读连接，不将 Spring 数据库凭据写入产品 Agent 的配置。`local-demo` 额外提供两个不具备知识读权限的隐藏合成账号，供冻结越权题核对角色与能力；生产配置不包含这些身份。没有调用付费对话模型，当前费用为 0 元。
