# #190：离线 reranker 一次有限可行性方案

2026-08-31；[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [PR203](https://github.com/Stellogic/customer-agent/pull/203)。协调接受本候选的静态实现/测试源码/双CR，**尚未授权任何下载、加载模型、检查或评测**；#173持运行窗口。起点 `48620c9ccd7f4b7e114ef514c7b2117719f2ba17`，已同步 main `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。

## 唯一假设与固定方法

假设：原授权 RRF Top5 的最大 query/passage 联合相关分，能否以一个固定界限同时保留有答案召回并拒绝相关但无答案的问题。相关性不等于充分性；本轮不承诺可行，不训练分类器、不调用云模型、不生成答案、不改变候选与 RRF 顺序。

使用 `BAAI/bge-reranker-base@2cfc18c9415c912f9d8155881c133215df768a70`，MIT，原始单输出 logit；不做 sigmoid、不额外加查询指令。本地 CPU float32、batch=1、torch线程1、eval/inference_mode、确定性算法、eager attention。问题/片段作为 tokenizer 的文本对，最大512 token（含特殊token）、right/longest_first截断。截断可能丢失必要事实，这是方法局限，不会因结果不好改截断重跑。

[官方 BGE 文档](https://bge-model.com/bge/bge_reranker.html)支持中英 query/passage 联合相关性评分；[模型卡](https://huggingface.co/BAAI/bge-reranker-base)提供 Transformers 用法。静态读取[官方模型元数据](https://huggingface.co/api/models/BAAI/bge-reranker-base?blobs=true)及固定 revision 的 config/tokenizer_config 后，将文件大小与 Git blob/LFS SHA 固定在 `agent/src/baseline_agent/knowledge_reranker_v1.json`。只使用 safetensors 和 fast tokenizer.json；不加载 pickle 权重、ONNX 或远程代码。新增模型约1.13GB文件（大小见清单），未下载；复用已有 torch/transformers/safetensors/httpx，不改依赖清单和锁。

## 开发数据与唯一界限选择

复用现有 `development_rows()`：旧 `issue190-logistic-fit-20260831b/calibration-collect.json`，原始归档SHA256 `b4ec9872012c90c795b0356a74f9ac3f4f7343bff207a76b16d9185265b06387`，数据SHA256 `4ba56767f8729ba064f614c856076c30f08e5852bad0255c2bf6b443c31014b6`，采集源码 `98b49949d6d835d510c4959d787b443fa95bc794`。固定原72题顺序、36有答案/36无答案、问题正文和 Spring 当时授权过滤后的完整 Top5。只给评分器问题和各片段正文，不传标签、参考答案、题ID或旧实验输出；不给全库。历史权限探针只作为来源，不宣称本轮重新验证权限。

这批数据已用于 A/C 开发且多次查看，**不是盲测，也不能证明泛化**。本轮不使用原训练144题拟合，不重读题目设计特例，不读 #189 或原封存留出；固定方法后才允许在获准窗口计算这72题分数。

复用 `knowledge_answerability.select_threshold` 的纯选择函数（不执行其中另一个 `fit_once` 函数）：候选界限为最小分数、最大分数的下一个更大浮点数、相邻不同分数中点；接受条件为原向量候选非空且最大logit≥界限。所有四项门槛同时满足才可选；唯一优先顺序为最大有答案Recall、最大无答案precision、最大界限。门槛仍0.90/0.75/0.90/0.85，不训练/标准化新特征，不选最接近但不达标的结果。报告保存全部候选和唯一选择；仅对一次完整72题计算开发结果，不拼接旧成绩。

## 最小实现与停止条件

- `knowledge_reranker.py`：校验本地文件、评分和一次开发选择；逐题保留原候选ID顺序、各片段logit、最大分数，接受时原样返回原Top5。不是产品 endpoint，也不导出或替换 Spring 策略。
- `knowledge_reranker_run.py` / `scripts/knowledge-reranker.ps1`：仅 prepare、development 两阶段；PowerShell沿用仓库共享锁。development使用共享Git目录旁固定 `.local/issue190-reranker-v1/development.json`，独占创建；换RunId不能续跑/覆盖。缺模型、校验失败、非有限分数或任意运行错误保存ERROR与已完成行，停止；无可行界限记INFEASIBLE，停止。进程崩溃留下RUNNING也不能自行清除或改路径续跑。工程前置失败的复验只能由协调另行安排并保留原始证据。
- 开发可行只记 `DEVELOPMENT_FEASIBLE`，不记独立/冻结/交付PASS。随后须先提交唯一参数、源码与原报告，由协调安排独立数据/执行者验证；原留出不由实施者读取。独立验证或189失败则停，不重选、改模型或降低门槛。对新独立数据规模/构造的决策不在此静态入口中实现。
- 默认 `KnowledgeRetrievalService`、BGE Embedding、全文/pgvector、RRF、迁移、UI及 #168/#169/#170 不改；保留 A失败、c6暂停源码及所有旧成绩。取消24字限制的产品原则继续有效，本候选不输出摘录，因此没有字符合同或新增结构化云调用。

## 后续执行入口与证据

**以下仅供协调授权后执行，现在未运行：**

```powershell
pwsh ./scripts/knowledge-reranker.ps1 -Phase prepare -RunId <协调指定RunId>
pwsh ./scripts/knowledge-reranker.ps1 -Phase development -RunId <协调指定RunId>
```

先受锁完成离线公共接缝回归 `agent/tests/test_knowledge_reranker.py`、格式/lint/类型及实际 PowerShell→Python 参数检查，再安排模型准备与一次开发评分；不因锁FREE自行开始。测试源码覆盖可行界限且RRF顺序不变、不可区分分数不得出策略、模型错误保留部分证据、文件缺失停止。人工分数测试只证明编排，不能证明模型分数或质量。

报告含受测SHA/base、RunId、方法/文件清单、来源数据hash、环境版本、完成数、原始分数/候选界限、耗时和费用。全部本地，无付费API，累计6元共享账本不读取、不修改、不重置；历史花费仍保留，新增费用0。模型耗时/内存实际值未采集；未新增遥测框架。本轮代码为Codex编写，非用户逐行手写，不能包装成生产规模或线上收益。

当前状态：静态源码与测试源码已准备，下载/加载/测试/格式/类型/开发/独立/189/完整门禁全部 **NOT_RUN**。尚未产生可行阈值或模型质量结论；双轴审查归档后提交交接，不合入、不关票、不解阻。
