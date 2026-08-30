# Issue #190：A 停止后的可回答性路线证据

日期：2026-08-31。关联 [Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [PR #203](https://github.com/Stellogic/customer-agent/pull/203)。状态：仅一手资料研究，不构成实施或运行授权。本次未读取留出、冻结题或历史逐题数据，未运行测试、安装、下载模型、训练、校准、评测或付费调用；仅新增本文。A 已按主任务报告停止，本文不重新选 A 的参数，也不依据其逐题结果选择规则。

**建议优先论证“项目既有 DeepSeek 接口 + 一次给定 Top-5 的充分性判定”，把离线 BGE reranker-base 保留为不外发时的替代研究路线。** 这是任务目标匹配上的工程判断，不是实测性能结论。前者可直接询问证据是否充分，后者的官方任务仍是相关性排序；但前者会新增检索中的网络依赖、数据外发和供应商版本漂移，不能以“项目已有 DeepSeek”自动获得这三项规格许可。

## 两条主要路线及第三候选

| 路线 | 一手资料支持的目标 | 本票适配判断与限制 |
| --- | --- | --- |
| B：`BAAI/bge-reranker-base` | query/passage 联合编码，输出 relevance 分数；原始 logit 无固定范围。官方中英模型，278M 参数，约1.11GB，模型卡 MIT | 比余弦信号包含更多文本交互，但最高相关性不等于全部必要信息充分；仍要独立验证拒答界限。可离线固定 revision/文件哈希；宿主 CPU 延迟、内存、兼容性未验证 |
| C：DeepSeek 给定上下文充分性判定 | DeepSeek 官方提供通用生成模型及结构化输出接口，没有承诺专用 answerability 准确率。query/context 二元充分性判定具有直接研究先例 | 不生成业务答案、不执行工具；一次读取固定合法 Top-5，返回 yes/no 与来自这些片段的引用。能直接表达缺失条件、跨段组合等判定要求，但这是提示任务，不是确定性证明；会误判，也可能受知识文本指令干扰 |
| D：现成多语 NLI，如 `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`，不优先 | premise/hypothesis 的 entailment / neutral / contradiction；模型卡 MIT，文件页单 safetensors 约558MB | 问题不是候选答案断言。直接把“上下文包含答案”作假设不等于已训练的 NLI 任务；若先生成答案再验证，会增加一个生成步骤及错误来源，超出本轮最小改进。CPU表现、固定revision及充分性效果未验证 |

B 的事实来源：[BAAI 模型卡](https://huggingface.co/BAAI/bge-reranker-base)、[官方模型说明](https://bge-model.com/bge/bge_reranker.html)。D 的事实来源：[作者模型卡](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli)、[作者文件清单](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli/tree/main)。本文不引入第三个模型，也不建议再自训一层分类器。

## 为什么 C 比相关性阈值更接近目标

ICLR 2025 的 *Sufficient Context* 将“上下文具有回答所需全部信息”与“内容相关但不充分”分开，并用输入 query/context、输出二元标签的 LLM autorater 进行判定。作者报告中的最佳设置使用提示后的 Gemini，不进行微调。这证明存在成熟的直接判定路线，**不证明 DeepSeek、中文合成数据或本项目的质量门可通过**，也不能照搬论文成绩为项目收益。[Google Research 一手说明](https://research.google/blog/deeper-insights-into-retrieval-augmented-generation-the-role-of-sufficient-context/)、[论文](https://arxiv.org/abs/2411.06037)

若选择 C，最小合同可限定为：输入只有问题、固定合法 Top-5 的片段 ID 与正文；输出 `sufficient` 布尔值及 `evidence` 中的片段 ID/短原文引用，不输出业务结论、补偿建议或行动。接受时保留原 RRF 顺序，拒绝时不提供知识结果。不要求模型给一个可扫描阈值的“置信度”，不把它与 B 串成多级模型。这是待决定的工程形式，尚未改产品。

引用 ID 必须属于本次 Top-5，引用文本必须来自对应片段；这些检查只能确认来源真实性，不能机械证明全部证据充分。知识正文只是数据，不执行其指令；不给判定调用任何工具。超时、供应商错误、空内容、截断或结构非法要作为运行失败保留，不能算作正确拒答来提高质量指标。DeepSeek 服务协议明确输出可能不准确且相同输入可能得到不同输出，因此温度设零、JSON 有效或引用检查均不等于语义正确。[官方开放平台协议第7.4节](https://cdn.deepseek.com/policies/zh-CN/deepseek-open-platform-terms-of-service.html)

## DeepSeek 当前接口与版本限制

本次读取官方文档时，Chat Completions 的 `model` 枚举为 `deepseek-v4-flash`、`deepseek-v4-pro`、`deepseek-v4-flash-vision-exp`；价格页把前两者对应到 DeepSeek-V4-Flash-0731、DeepSeek-V4-Pro-0813。官方变更记录曾公告旧 `deepseek-chat` / `deepseek-reasoner` 于2026-07-24停用，并明确 Flash 名称指向最新版本。**不能再把旧名称写成固定 V3.2，也不能把价格页版本说明当成已支持的日期快照 API 名称。** 本次未调用 models 接口验证账号实际可用项。[Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)、[价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[变更记录](https://api-docs.deepseek.com/updates/)

已查接口未给出等价于本地 BGE 文件 SHA 的不可变权重固定机制。后续即使固定请求 model、参数及提示词，也应记录返回 model、system_fingerprint、日期和原始 usage；这提供追踪性，不保证供应商模型永久不变。若规格要求整个可回答性链完全离线、权重可重复，则 C 不符合，须选择本地路线或明确接受规格变化。

结构化输出应匹配**项目实际接口**，不能混用能力：

- Chat Completions 当前提供 `response_format: {type: json_object}`。官方要求提示中写明 JSON 与示例，提示可能空内容，且达到长度上限可截断；应用仍须验证字段类型、引用范围及结束原因。[官方 JSON 指南](https://api-docs.deepseek.com/guides/json_mode/)
- Responses 当前提供 `text.format.type=json_schema`，但这不意味着已有 Chat 调用自动支持同一参数。即使 schema 受约束，也只约束结构，不保证 `sufficient` 真实。[官方 Responses API](https://api-docs.deepseek.com/api/create-response/)
- 思考模式当前默认开启，温度在思考模式中无效。若未来决定采用较小成本的非思考判定，必须显式关闭，而非只设温度；若决定思考模式，则把 reasoning tokens 纳入输出预算。不因一轮失败切换模式或模型。[官方思考模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)

## 人民币成本边界

官方价格按每百万 tokens 计，读取于2026-08-31。高峰为北京时间周一至周五9:00–12:00、14:00–18:00，其余空闲；实际运行前仍需核对官方变价。[官方人民币价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)

| API模型 | 输入缓存未命中：峰/谷 | 输入缓存命中：峰/谷 | 输出：峰/谷 |
| --- | ---: | ---: | ---: |
| deepseek-v4-flash | 3 / 1.5元 | 0.10 / 0.05元 | 9 / 4.5元 |
| deepseek-v4-pro | 9 / 4.5元 | 0.30 / 0.15元 | 27 / 13.5元 |

预算建议按高峰、输入全部未命中估计，不预支缓存折扣。Flash 单次上界表达为 `3×输入token上限/1e6 + 9×输出token上限/1e6`；这需要真正落实输入 token 上限和服务端输出上限，不能用字符数假装准确 token 数。仅作算例：若每次4096输入、512输出，单次约0.016896元，200次约3.3792元；**这不是已确定样本数或实测费用**。Pro 在同一算例下为三倍。超时后费用可能未知，重复请求也消耗预算，须预留并计入累计上界。

沿用用户总预算≤6元，只能在协调授权的有界运行中使用；不得把每阶段6元累加成更高总额。余额、供应商、版本或预算失败即停止，不自动充值、换供应商、换模型或假回退。未来需由主方案在任何调用前同时固定请求总数、输入/输出上限、重试上限及停止条件；若预算不能覆盖全部计划，先缩小开发试验范围，不降低冻结标准。本次付费模型调用为0；机器、研究工具、网络和人工成本未采集。

## 数据外发边界

C 会把问题及片段正文送往 DeepSeek API；固定 BGE 的编码可仍在本地，但整条检索判定链不再是离线链。不能只因返回 yes/no 就说没有内容外发。官方开放平台协议要求开发者拥有输入处理权限，且对终端用户数据处理自行告知和负责；官方隐私政策适用范围包含 API，但对下游应用的数据处理另有边界。查阅材料不足以承诺“本项目 API 输入零留存且永不训练”，也不据通用对话条款断言每一条 API 输入一定被训练。[官方平台协议第3.5、4.1、5.5节](https://cdn.deepseek.com/policies/zh-CN/deepseek-open-platform-terms-of-service.html)、[官方隐私政策](https://cdn.deepseek.com/policies/zh-CN/deepseek-privacy-policy.html)

本项目最小做法是仅在已授权研究阶段外发明确可外发的合成/脱敏材料；API key只留服务端，不进入证据。未来默认内部检索是否允许外发知识正文，需要明确范围，不从既有 Agent 调用权限推导出所有检索页面都可发送。无需为学习项目另建遥测或复杂合规框架，但不能用“学习项目”掩盖这一真实数据流变化。

## 有界下一步建议

先由主方案确定 C 的网络/版本/数据边界是否可接受；若接受，以**一个固定模型、一个固定判定合同、一次开发检查后锁定的提示词**做小规模可行性验证，不从 A 已见结果增加领域规则，不把冻结题作提示示例。新的路线仍需独立保留数据验证；已经打开的材料不能再次冒称未见，冻结原门槛完全保留。

如接口/预算/数据边界不可落实，停止 C 并讨论离线 B；B 也不能只设 relevance 阈值就宣称充分性已解决。两者不能一边看同一留出成绩一边切换；未见集或冻结门失败后保留失败，不自动扩成提示词搜索、模型赛马或额外自训。本文只提供来源比较及决策限制，实际接入复用程度、规格接受、提示词、样本和运行窗口由后续主方案确定。
