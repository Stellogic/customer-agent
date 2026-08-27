# 第一阶段中文轻量 RAG 与混合检索方案调研

> 调研日期：2026-08-28
>
> 目标：核验 `BAAI/bge-small-zh-v1.5` 是否适合作为第一阶段本地中文 Embedding 候选，并评估与现有 Python/LangGraph、Spring Boot、PostgreSQL 技术栈自然适配的“全文检索＋向量语义检索”实现。
>
> 证据范围：只采用模型发布方、Hugging Face、Sentence Transformers、ONNX Runtime、PostgreSQL、pgvector 与 PGroonga 的官方模型卡、文档和仓库；仓库事实来自本调研工作树。没有安装依赖、下载模型、导出 ONNX、启动服务或运行检索基准。
>
> 验证边界：本文证明的是许可证、公开模型规格与官方工具链能力，不证明本项目已经达到某个中文召回率、延迟或内存占用。所有性能数字与检索质量都必须用本项目语料实测。

## 1. 结论摘要

1. **可以把 `BAAI/bge-small-zh-v1.5` 作为第一阶段首选 Embedding 候选。** 官方模型卡将它标为 Chinese、Feature Extraction，列出 24M 参数，并明确 FlagEmbedding 采用 MIT 许可证、发布模型可免费商用；官方文件页显示单份 `model.safetensors` 为 95.8 MB。[官方模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5) / [官方文件页](https://huggingface.co/BAAI/bge-small-zh-v1.5/tree/main) / [FlagEmbedding LICENSE](https://github.com/FlagOpen/FlagEmbedding/blob/master/LICENSE)
2. **“首次取得后可完全本地、离线、CPU 运行”有官方工具链支持。** Transformers 支持预先下载后从本地目录加载，并可用 `HF_HUB_OFFLINE=1` 或 `local_files_only=True` 禁止联网；Sentence Transformers 的默认后端可落到 CPU，也提供使用 `CPUExecutionProvider` 的 ONNX 后端。[Transformers 离线模式](https://huggingface.co/docs/transformers/installation#offline-mode) / [Sentence Transformers 推理后端](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)
3. **ONNX Runtime 是可验证的优化候选，不是已经验证的既成事实。** 该模型配置是 BERT 架构，而官方 ONNX 工具链支持 feature-extraction；但模型仓库当前公开的是 PyTorch/Safetensors 权重，没有随仓库提供已验收的 ONNX 文件。第一阶段若采用 ONNX，必须固定模型 revision，执行一次导出，并验证 pooling、归一化与 PyTorch 基线的向量/排序一致性。[模型配置](https://huggingface.co/BAAI/bge-small-zh-v1.5/blob/main/config.json) / [Sentence Transformers ONNX 说明](https://sbert.net/docs/sentence_transformer/usage/efficiency.html#onnx)
4. **当前栈最自然的混合检索基线是 PostgreSQL + pgvector + Psycopg 3 + RRF。** pgvector 官方明确建议与 PostgreSQL 全文检索组合，并使用 Reciprocal Rank Fusion（RRF）或 cross-encoder 融合；其 Python 官方仓库已有 Sentence Transformers + Psycopg 的完整 RRF 示例。本项目已经使用 PostgreSQL 18.4 和 `psycopg[binary,pool]`，因此不必先引入独立搜索服务。[pgvector Hybrid Search](https://github.com/pgvector/pgvector#hybrid-search) / [pgvector-python RRF 示例](https://github.com/pgvector/pgvector-python/blob/master/examples/hybrid_search/rrf.py)
5. **不能把 PostgreSQL 内建全文检索直接等同于高质量中文分词。** PostgreSQL 官方全文检索提供 `tsvector`、`tsquery`、`@@`、`ts_rank`/`ts_rank_cd` 与 GIN 索引，但官方没有承诺内建 parser 能完成中文分词。PGroonga 官方也明确把中文等亚洲语言列为 PostgreSQL 默认全文检索的缺口。因此，先做中文评测门；若内建基线召回不足，再决定写入前分词或引入 PGroonga，不能把未经验证的中文效果写入验收结论。[PostgreSQL parser](https://www.postgresql.org/docs/current/textsearch-parsers.html) / [PGroonga 概览](https://pgroonga.github.io/overview/)
6. **RAG 只能解释知识，不扩大业务权威。** DeepSeek 继续是唯一负责调查规划、结论形成和客户回复的 LLM；本地 Embedding 模型只把文本映射为向量，不是第二个对话模型。订单、物流、支付、补偿资格、金额与执行结果仍只能来自 Spring 权威业务接口。

## 2. 仓库当前事实

调研工作树当前的相关事实是：

- `compose.yaml` 使用 `postgres:18.4-bookworm`，尚未包含 pgvector 或中文全文检索扩展。
- Agent 依赖已经包含 LangGraph、PostgreSQL checkpointer 与 Psycopg 3，但没有 Sentence Transformers、Transformers、ONNX Runtime、pgvector Python adapter、文档分段器或 Retriever。
- Spring 已通过 PostgreSQL JDBC 与 Flyway 管理业务库；LangGraph PostgreSQL checkpointer 是工作流状态存储，不能被视为知识库。
- 浏览器只连接 Spring；现有网络边界没有理由让浏览器加载模型或直接查询知识存储。

因此，本文建议是后续实现候选，不代表当前仓库已经具备 RAG。

## 3. 模型候选核验

### 3.1 许可证与商用边界

官方模型卡的 License 段写明 FlagEmbedding 为 MIT，并明确发布模型可免费商用；FlagEmbedding 官方仓库的 `LICENSE` 是标准 MIT 文本，要求分发软件副本或实质部分时保留版权与许可声明。[模型卡 License](https://huggingface.co/BAAI/bge-small-zh-v1.5#license) / [官方 LICENSE](https://github.com/FlagOpen/FlagEmbedding/blob/master/LICENSE)

可据此采用，但实现时仍应：

- 在第三方声明中记录模型名、固定 revision、许可证与来源；
- 不把模型权重提交进 Git；
- 通过可审计的下载脚本或镜像构建步骤取得权重，并校验预期文件；
- 不只写浮动的 `main`，应保存最终解析到的完整 commit/revision 与文件校验值。

### 3.2 参数、文件体积与模型结构

| 项目 | 官方事实 | 解释边界 |
|---|---|---|
| 参数量 | 模型卡显示 24M params | 可以写“约 2400 万参数” |
| 单份核心权重 | `model.safetensors` 为 95.8 MB | 可以写“核心权重约 96 MB” |
| 仓库展示总量 | 文件树显示约 192 MB | 因同时包含约 95.8 MB 的 Safetensors 与 PyTorch `.bin` 权重，不能把 192 MB 当成单份运行权重 |
| 架构 | `BertModel`，4 层，hidden size 512 | 说明它是小型编码器，不是生成式对话模型 |
| 输出维度 | 模型卡与配置对应 512 维 | 数据库 `vector` 维度应由固定版本的实际输出再次验收 |

来源：[官方模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5)、[官方文件树](https://huggingface.co/BAAI/bge-small-zh-v1.5/tree/main)、[官方配置](https://huggingface.co/BAAI/bge-small-zh-v1.5/blob/main/config.json)。

“运行时通常占几百 MB 到 1–2 GB 内存”不是这些官方资料给出的模型特定保证。权重大小不能直接推出进程峰值内存，因为运行时、tokenizer、中间张量、batch、线程池和 Python 环境都会增加占用。文档和 UI 可以把它描述为待测容量预估，不能作为已验证指标。

### 3.3 中文检索适用性

官方模型列表把 `bge-small-zh-v1.5` 标为 Chinese，并给出中文检索指令“为这个句子生成表示以用于检索相关文章：”；模型卡还给出 C-MTEB 等中文任务结果与 Sentence Transformers/Transformers 推理示例。[官方模型卡的模型列表与用法](https://huggingface.co/BAAI/bge-small-zh-v1.5)

这足以证明它是面向中文检索训练和发布的合理候选，但排行榜分数不能直接外推到客服知识库。本项目仍需覆盖：

- 客户口语、错别字、简称和同义表达；
- 规则名称、订单术语、金额、时效与版本号；
- 相似但适用范围不同的知识条目；
- “应该拒答/不应引用”的无关查询；
- 同一问题在旧版本与新版本条目之间的选择。

模型卡明确区分短查询与长文档：查询侧建议添加检索指令，语料侧不添加；实现与评测必须固定这套编码约定，不能一边有指令、一边无指令却混用旧向量。[官方 Usage](https://huggingface.co/BAAI/bge-small-zh-v1.5#usage)

## 4. 离线 CPU 与 ONNX 可行性

### 4.1 离线运行

Transformers 官方文档给出两种离线方式：预先下载后指向本地目录，或使用已缓存文件并设置 `HF_HUB_OFFLINE=1`；`from_pretrained(..., local_files_only=True)` 只加载本地文件。[Transformers Offline mode](https://huggingface.co/docs/transformers/installation#offline-mode)

因此建议部署契约是：

1. 构建/准备阶段按固定 revision 取得模型与 tokenizer；
2. 运行阶段只使用本地绝对目录，并启用离线模式；
3. 生产启动时若文件缺失或校验失败则 fail closed，不临时联网下载浮动版本；
4. 模型只由 Python/LangGraph 服务加载，浏览器和 Spring 不加载权重。

### 4.2 CPU 与 ONNX Runtime

Sentence Transformers 官方文档说明默认 PyTorch 后端会在 CUDA、MPS 与 CPU 中选择可用设备；其 `onnx` extra 面向 CPU，支持显式 `CPUExecutionProvider`。当仓库没有 ONNX 文件时，它会尝试导出，并建议保存导出结果，避免每次启动重复导出。[官方推理效率文档](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)

这支持“无需显卡”的能力判断，但不支持预先承诺延迟。官方同一文档也明确提示：不同文本长度与硬件下，ONNX、OpenVINO 和 PyTorch 的相对表现会变化，应在具体模型与数据上测试。

建议以两级实现门控制：

- **先建立正确性基线：** CPU + PyTorch/Safetensors，固定 pooling、归一化、查询指令和 revision。
- **再做 ONNX spike：** 导出 feature-extraction 模型，使用 CPU provider；对同一批语料比较向量余弦差异、Top-K 排序、吞吐、P50/P95、峰值 RSS 与冷启动时间。只有收益成立才把 ONNX 设为默认。

特别注意：Sentence Transformers 官方说明，仅导出的 Transformer 会输出 token embeddings；若脱离 Sentence Transformers 直接调用 ONNX Runtime，调用方必须自己正确实现 pooling 和 normalization。[ONNX 注意事项](https://sbert.net/docs/sentence_transformer/usage/efficiency.html#onnx)

## 5. 混合检索候选

### 5.1 首选基线：PostgreSQL 全文检索 + pgvector + RRF

pgvector 官方仓库明确展示：向量检索可与 PostgreSQL full-text search 组合，全文侧用 `plainto_tsquery`、`@@` 和 `ts_rank_cd`，再用 RRF 或 cross-encoder 合并。[pgvector Hybrid Search](https://github.com/pgvector/pgvector#hybrid-search)

pgvector-python 官方 RRF 示例与本项目尤其贴近：

- 使用 Sentence Transformers 生成 embedding；
- 使用 Psycopg 连接 PostgreSQL；
- 语义检索与关键词检索分别取 Top-K；
- 通过 SQL `RANK()` 和 `FULL OUTER JOIN` 计算 RRF；
- 向量表使用 `vector(384)` 只是示例，本项目应采用固定模型实测维度。[官方 RRF 示例](https://github.com/pgvector/pgvector-python/blob/master/examples/hybrid_search/rrf.py)

PostgreSQL 官方全文检索提供 `tsvector`/`tsquery`、`@@`、`plainto_tsquery`、`ts_rank` 与 `ts_rank_cd`；官方也强调“相关性”是应用相关概念，允许组合额外因素。因此，把条目适用范围、版本状态等先作为硬过滤，再在许可候选内做排名，符合官方能力边界。[全文检索函数](https://www.postgresql.org/docs/current/functions-textsearch.html) / [排序搜索结果](https://www.postgresql.org/docs/current/textsearch-controls.html#TEXTSEARCH-RANKING)

优点：

- 沿用现有 PostgreSQL 与 Psycopg，不先引入独立搜索集群；
- 结构化元数据、全文索引、向量和版本状态可以在同一查询边界过滤；
- pgvector 官方支持 PostgreSQL 13+，覆盖当前 PostgreSQL 18；官方还提供 Docker 安装路径。[pgvector 安装](https://github.com/pgvector/pgvector#installation)

成本与风险：

- 当前 `postgres:18.4-bookworm` 不含 pgvector；实现必须采用固定 pgvector 版本的镜像/构建与迁移，不能仅增加 Python 包；
- HNSW/IVFFlat 的选择、索引参数和召回率都需按数据规模验证；小型第一阶段语料可先用精确向量搜索，避免无依据地提前调 ANN；
- RRF 的两个候选集大小与常数需要评测，不能把官方示例中的 `20` 和 `k=60` 当成项目标准。

### 5.2 中文词法侧的三档路径

| 路径 | 一手依据 | 判断 |
|---|---|---|
| PostgreSQL 内建 FTS | 原生 `tsvector`、GIN、`ts_rank_cd`；pgvector 官方混合示例直接使用 | **作为最小基线**，但不承诺中文分词质量 |
| PostgreSQL `pg_trgm` | PostgreSQL 随附的 trusted extension，支持 trigram 相似度及 GIN/GiST 加速的 `LIKE`/`ILIKE`/相似度查询 | **适合加入基线对照**，尤其是编号、型号、短语和拼写近似；中文效果仍需实测 |
| PGroonga + pgvector | PGroonga 官方明确支持包括中文在内的多语言全文检索，仍在 PostgreSQL 内、无需跨库 ETL | **原生基线不达标时的候选**；增加扩展、镜像、升级、备份恢复和许可证审查成本 |

来源：[PostgreSQL `pg_trgm`](https://www.postgresql.org/docs/current/pgtrgm.html)、[PGroonga Overview](https://pgroonga.github.io/overview/)、[PGroonga 官方站](https://pgroonga.github.io/)。

推荐先用真实中文知识条目做盲测，比较：

1. 内建 FTS + 稠密向量 + RRF；
2. `pg_trgm`/精确短语 + 稠密向量 + RRF；
3. 如果前两者在中文词法召回上不达标，再原型验证 PGroonga + 稠密向量。

这比先承诺某种中文分词扩展更符合仓库“成熟组件优先，但重要依赖先有证据与权衡”的原则。

## 6. 第一阶段推荐边界

### 6.1 知识条目

继续采用仓库内版本化中文 Markdown，至少包含：

- `id`：跨版本稳定的条目标识；
- 标题；
- 版本；
- 更新时间；
- 适用范围；
- 正文。

索引构建应产生稳定 chunk id，并保存条目 id、条目版本、标题、适用范围、源文件与分段位置。Agent 回复引用的是这些可审计字段，不引用一个无法追溯来源的自由摘要。

### 6.2 权威边界

```text
客户自然语言
  -> Agent 自主决定是否检索知识
  -> 词法候选 + 向量候选
  -> 适用范围/版本硬过滤
  -> RRF 合并和 Top-K
  -> Agent 基于引用解释规则

订单、物流、支付、补偿资格/金额/执行
  -> 只能调用 Spring 权威接口
```

- Embedding 模型只做 feature extraction；DeepSeek 仍是唯一推理和回复 LLM。
- RAG 只支持规则说明与知识解释，不能推断当前订单事实或补偿资格。
- 检索结果必须携带条目 id、版本和引用位置；适用范围不匹配的条目不得仅因向量相似而进入回答依据。
- 编辑、审核、发布等后台功能第一阶段可以按原型显示“开发中”，不能伪造保存或发布成功；查看、检索、版本和引用必须是真实能力。

## 7. 实现前验收门

1. **供应链：** 固定模型完整 revision、下载文件清单和校验值；记录 MIT notice；运行镜像不依赖启动时联网。
2. **Embedding 正确性：** 固定查询指令、pooling、归一化、最大长度和截断策略；同一版本重建结果可复现。
3. **ONNX 一致性：** 与 PyTorch 基线比较向量与 Top-K；单独记录冷启动、P50/P95、吞吐和峰值 RSS，不能只看权重文件大小。
4. **中文检索集：** 用真实客服知识构造 query—相关条目—不相关条目集合，至少度量 Recall@K、MRR/nDCG、无答案精度和错误版本命中率。
5. **混合检索消融：** 分别测词法、向量、RRF；证明混合方案优于单路后再固定参数。
6. **权限与适用范围：** 先过滤权限、发布状态、版本和适用范围，再排序；测试不可见条目即使高相似也不会泄露。
7. **引用：** 每条知识性结论可回到仓库 Markdown 的 id、版本与具体分段；更新后旧引用仍可审计。
8. **故障语义：** 模型文件缺失、索引过期、Embedding 失败或数据库扩展不可用时停止知识结论或转人工，不以无来源内容填补。
9. **运维：** 验证 pgvector/可选中文扩展的迁移、升级、备份恢复与 Compose 隔离；不得对现有基线资源执行破坏性重置。
10. **仓库门禁：** 后续实现完成前从仓库根目录运行 `pwsh ./scripts/check.ps1`。

## 8. 最终建议

接受 Q53 的轻量 RAG 方向，并将表述固定为：

> 第一阶段引入受控的轻量 RAG。知识源为仓库内版本化中文 Markdown；Agent 使用混合检索获得带条目 id、版本和位置的引用。RAG 只解释一般规则，Spring 继续权威提供订单、物流、支付、补偿资格、金额和执行事实。
>
> Embedding 首选候选为固定 revision 的 `BAAI/bge-small-zh-v1.5`：官方标注 MIT、24M 参数，单份 Safetensors 权重约 95.8 MB，面向中文检索。模型由 Python/LangGraph 服务在本地 CPU 加载，不进入浏览器或 Spring，也不提交权重到 Git。先以 PyTorch 建立正确性基线；ONNX Runtime 作为优化 spike，只有导出、向量一致性和本机资源基准通过后才设为默认。
>
> 混合检索首选 PostgreSQL + pgvector + Psycopg 3 + RRF，不先增加独立搜索服务。PostgreSQL 内建全文检索作为最小基线，但不预先承诺中文分词质量；以项目评测决定是否加入 `pg_trgm`、写入前分词或 PGroonga。

这保留了用户建议中的轻量、离线、中文、引用和单一推理 LLM 目标，同时把三个尚未实测的断言——中文全文召回、ONNX 结果一致性、内存/延迟——明确留给实施验收。
