# DeepSeek API 兼容性与调查模型选择

> 调研日期：2026-08-24
> 范围：DeepSeek 官方 API 文档、开放平台条款与隐私政策；仅以 OpenAI 官方文档作为现有实现和价格候选的对照。
> 验证边界：本轮未持有或使用任何模型密钥，未发起计费请求；文中的“支持”表示官方文档声明，仍需用本仓库合成评测集实测。

## 结论

**DeepSeek 已经是本仓库现有 Responses API smoke 的自然适配候选，不必先退回 Chat Completions。** 官方文档现已明确提供 `client.responses.create(...)`，并列出 `deepseek-v4-flash`、`deepseek-v4-pro` 和实验性视觉模型；`text.format` 被标为完全支持，现有 strict JSON Schema 请求形状有较高复用价值。[DeepSeek：Using the Responses API](https://api-docs.deepseek.com/guides/responses_api/)

但“OpenAI 格式兼容”不等于“OpenAI 语义完全等价”：

- DeepSeek Responses API 是无状态接口，不支持 `previous_response_id`、`conversation`、`background`、`metadata` 等能力；不支持的参数可能被**静默忽略**，不能依赖 4xx 暴露误配置。
- `store` 参数不受支持，响应固定显示 `store: false`；与此同时，DeepSeek 的上下文硬盘缓存默认开启，每次请求都会构建缓存，通常数小时到数天后清理。`store: false` 因而不能解释为“请求不产生任何服务端暂存”。[DeepSeek：Responses compatibility details](https://api-docs.deepseek.com/guides/responses_api/#compatibility-details) / [DeepSeek：Context Caching](https://api-docs.deepseek.com/guides/kv_cache)
- DeepSeek 当前隐私政策写明会收集用户输入，并将“开发、改进及训练技术”列为用途；但该政策同时声明，下游应用终端用户个人信息的处理规则不在该政策覆盖范围内。官方公开材料未给出可供本项目确认的 API payload 精确保留期、API 输入是否可退出训练、Zero Data Retention 或企业级不训练承诺。[DeepSeek 隐私政策](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html) / [DeepSeek 开放平台服务条款](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html)

因此建议：

1. 第一阶段只实现 `FixedFakeModel` 与 `DeepSeekInvestigationModel`，默认仍为 fake；DeepSeek 先进入合成结构化事实的 shadow 路径。
2. 首轮基准模型使用 `deepseek-v4-flash`；同时用同一评测集少量对照 `deepseek-v4-pro`。这只是基于价格、并发和任务形态的**待验证起点**，不是质量结论。
3. 在真实评测通过后，才允许 DeepSeek 输出提交 Spring，达成短期目标 B。
4. 客户描述或消息进入模型前，必须另行解决数据处理、保留、训练、披露与授权问题；在这些事实未澄清前，不应进入目标 C。

## 1. OpenAI 兼容到什么边界

### 1.1 已确认支持

DeepSeek 的入门文档明确写明其 API 采用兼容 OpenAI/Anthropic 的格式；OpenAI SDK 只需把 `base_url` 改为 `https://api.deepseek.com`，密钥改为 DeepSeek 密钥。官方 Chat 示例使用 `client.chat.completions.create(...)`。[DeepSeek：Your First API Call](https://api-docs.deepseek.com/guides/function_calling/)

截至调研日，DeepSeek 还明确支持 Responses API：

```python
from openai import OpenAI

client = OpenAI(
    api_key=deepseek_api_key,
    base_url="https://api.deepseek.com",
)
response = client.responses.create(
    model="deepseek-v4-flash",
    instructions="...",
    input="...",
)
```

非流式响应沿用 Responses 对象形状；流式使用语义事件，并以 `response.completed`、`response.incomplete` 或 `response.failed` 结束，不使用 Chat Completions 的 `data: [DONE]`。[DeepSeek：Using the Responses API](https://api-docs.deepseek.com/guides/responses_api/)

对本仓库当前 smoke 用到的请求字段，官方兼容表给出的状态是：

| 字段 | DeepSeek Responses 状态 | 对当前 smoke 的意义 |
|---|---|---|
| `model` | 支持 | 模型名必须换为 DeepSeek 模型 |
| `instructions` | 支持，插为首条 system message | 现有安全提示形状可复用 |
| `input` | 支持字符串或 item list | 当前 JSON 字符串输入可复用 |
| `text.format` | 完全支持 | 现有 `json_schema`/`strict` 形状可直接作为首轮实测对象 |
| `max_output_tokens` | 支持 | 生产接入应显式设置，防止截断和费用失控 |
| `store` | 不支持，响应固定为 `false` | 无需把它当作请求开关，但也不能据此推断无缓存/无留存 |
| `previous_response_id` / `conversation` | 不支持 | 多轮历史必须由应用显式管理 |
| `metadata` | 不支持 | 不能依靠供应商侧 metadata 保存内部关联 |
| `background` | 不支持 | 不可照搬 OpenAI 后台响应工作流 |

来源：[DeepSeek：Responses compatibility details](https://api-docs.deepseek.com/guides/responses_api/#compatibility-details)

### 1.2 不能视为等价的部分

- DeepSeek 文档明确说，不支持的 Responses 参数会被静默忽略。因此适配器必须维护本项目自己的参数白名单，并用契约测试证明关键参数确实生效。
- `developer` role 在 DeepSeek Responses 兼容表中会被当作 `user`，而 `instructions` 被插入 system message。当前 smoke 使用顶层 `instructions`，不受这个差异直接影响；未来若把安全策略放在 developer message，优先级语义可能发生变化。
- Responses 工具只完整支持 function 和服务端 web search；其他多种 OpenAI 内置工具会被忽略。本次“结构化调查判断”不需要供应商工具，第一阶段应保持 `tools` 为空。
- DeepSeek Responses 无服务端对话状态。LangGraph checkpoint 仍是本项目的工作流状态，但若未来目标 C 需要多轮客服对话，应用必须明确选择、授权并重发哪些历史消息。

## 2. JSON Output、JSON Schema 与 Structured Outputs

DeepSeek 存在三条不同能力，不能混为一谈。

### 2.1 Chat Completions JSON Output

Chat Completions 的 `response_format={"type":"json_object"}`只保证合法 JSON 字符串，不保证满足业务 schema。官方还要求提示中包含 `json` 字样并给出目标格式示例，并警告该模式偶尔可能返回空 `content`；`finish_reason="length"` 时内容也可能被截断。[DeepSeek：JSON Output](https://api-docs.deepseek.com/guides/json_mode) / [DeepSeek：Create Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion)

这条能力弱于本仓库当前 strict JSON Schema smoke，不应作为首选迁移路径。

### 2.2 Chat Completions strict tool call

DeepSeek 还提供 strict function tool call，但它是 Beta，要求使用 `https://api.deepseek.com/beta`，所有 function 都设 `strict: true`。官方列出的 schema 类型包括 object、string、number、integer、boolean、array、enum、anyOf；所有 object 属性必须 required，且 `additionalProperties` 必须为 false。[DeepSeek：Tool Calls strict mode](https://api-docs.deepseek.com/guides/tool_calls/#strict-mode-beta)

这可作为 Responses structured output 失败时的备选实验，却会把“返回调查结论”伪装成工具调用并引入 Beta 端点，不宜优先采用。

### 2.3 Responses `text.format`

DeepSeek Responses 兼容表把 `text.format` 标为“fully supported”。按其引用的 OpenAI Responses 定义，`type: json_schema` 与 `strict: true` 正是 Structured Outputs 请求形状。因此，本仓库当前 schema（object、boolean、string enum、定长 string array、全部 required、`additionalProperties: false`）应作为**直接迁移候选**。[DeepSeek：Responses compatibility details](https://api-docs.deepseek.com/guides/responses_api/#compatibility-details) / [OpenAI：Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

不过 DeepSeek 文档没有单独列出 Responses `text.format` 支持的 JSON Schema 子集，也没有给出当前 schema 的完整示例。以下内容必须实测后才能升级为项目保证：

- `minItems = maxItems = 2` 是否被严格执行；
- enum、required 和 `additionalProperties: false` 的组合是否稳定；
- refusal、内容过滤或资源不足时返回的是结构化失败状态、空正文还是其他输出 item；
- thinking 默认开启时，structured output 是否有延迟、费用或稳定性差异；
- 非流式响应中的 `status`、`error`、`incomplete_details` 和 output item 形状是否与当前解析器假设一致。

无论供应商声称 Structured Outputs，Spring 提交前仍必须保留本地 JSON 解析、字段集合、证据白名单、订单引用和业务不变量校验。

## 3. 当前模型、上下文、价格、缓存与容量

### 3.1 模型与价格快照

DeepSeek 官方定价页在 2026-08-24 列出：

| 模型 | 后端版本标识 | 上下文 / 最大输出 | 输入缓存命中 | 输入缓存未命中 | 输出 | 账户并发 |
|---|---|---:|---:|---:|---:|---:|
| `deepseek-v4-flash` | DeepSeek-V4-Flash-0731 | 1M / 384K | $0.007 非高峰；$0.014 高峰 | $0.22 非高峰；$0.44 高峰 | $0.66 非高峰；$1.32 高峰 | 2500 |
| `deepseek-v4-pro` | DeepSeek-V4-Pro-0813 | 1M / 384K | $0.022 非高峰；$0.044 高峰 | $0.66 非高峰；$1.32 高峰 | $1.98 非高峰；$3.96 高峰 | 500 |

价格单位均为每百万 token；高峰时段为周一至周五 01:00–04:00、06:00–10:00 UTC。价格会调整，实施票和运行手册不应把数值硬编码成永久事实。[DeepSeek：Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)

官方列出的 API 模型 ID 是别名，而定价页另列当前“MODEL VERSION”。公开文档未证明可直接使用 `deepseek-v4-flash-0731` 或 `deepseek-v4-pro-0813` 作为不可变 API snapshot。因此，**固定模型快照能力是未知项**；适配器至少应同时记录请求模型名和响应 `model`/`system_fingerprint`，并以持续 eval 识别后端变化。[DeepSeek：List Models](https://api-docs.deepseek.com/api/list-models) / [DeepSeek：Create Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion)

### 3.2 模型起点

首轮推荐从 `deepseek-v4-flash` 开始，原因仅是：当前任务是小型结构化分类、其价格低于 pro、官方并发额度更高。`deepseek-v4-pro` 是否在拒答、边界案例、中文自然语言理解或提示注入上显著更好，官方价格页不能回答，必须用同一评测集比较。

建议评测矩阵至少同时记录：schema 成功率、业务不变量通过率、拒答/空输出率、P50/P95 延迟、输入/输出/推理 token、缓存命中、单工单成本，以及 flash/pro 分歧率。未达到预先定义阈值时不得因“模型更贵”推断它更可靠。

### 3.3 自动缓存

DeepSeek 上下文硬盘缓存默认对所有用户开启，不需要代码改动。只有已持久化并完整匹配的前缀单元才能命中；缓存是 best effort，不保证命中。响应 usage 可读 `prompt_cache_hit_tokens` 和 `prompt_cache_miss_tokens`；Responses 形状中对应 `input_tokens_details.cached_tokens`。缓存通常在数小时到数天内清理。[DeepSeek：Context Caching](https://api-docs.deepseek.com/guides/kv_cache) / [DeepSeek：Responses API usage](https://api-docs.deepseek.com/guides/responses_api/#response-fields)

这意味着：

- 把稳定 system 指令与 schema 放在输入前缀有利于缓存，但不得为省费扩大客户数据发送范围；
- `user_id` 可用于 KV cache、安全与调度隔离，官方要求它只含字母、数字、连字符或下划线，并明确不要放隐私信息；可传内部不可逆分区标识，不能传客户 ID、邮箱、订单号等原值。[DeepSeek：Rate Limit & Isolation](https://api-docs.deepseek.com/quick_start/rate_limit/)
- 自动缓存本身构成服务端暂存事实；目标 C 的隐私评审必须将其纳入，而不能只检查 Responses 的 `store` 字段。

### 3.4 限流、超时、错误与重试

官方当前列出 400、401、402、422、429、500、503。429 表示超并发/请求过快，500/503 建议短暂等待后重试。[DeepSeek：Error Codes](https://api-docs.deepseek.com/quick_start/error_codes/)

DeepSeek 还说明：请求等待期间，非流式连接可能持续返回空行，流式返回 keep-alive 注释；若 10 分钟仍未开始推理，服务端关闭连接。[DeepSeek：Rate Limit & Isolation](https://api-docs.deepseek.com/quick_start/rate_limit/#request-keep-alive-mechanism)

对本项目的工程含义：

- 当前 smoke 的 `httpx.Client(timeout=60.0)` 是单一总超时，可能早于 DeepSeek 服务端等待上限；生产适配器应分别定义 connect/read/total 或整体截止时间，并把超时分类为显式人工接管原因。
- 400/401/402/422 不应自动重试；429/500/503 只做有上限、带抖动且服从整体截止时间的重试。
- 官方公开文档未找到请求幂等键或重复计费保护保证。网络超时后无法确认供应商是否已完成推理时，重试可能产生第二次调用和费用；必须用内部 attempt ID 记录每次尝试，不能把重试伪装成同一次供应商调用。
- DeepSeek 的不支持参数可被静默忽略，所以“请求返回 200”不足以证明配置正确。

## 4. 数据保留、训练与隐私：能确认和不能确认的事实

### 4.1 能确认

- DeepSeek 隐私政策（2026-02-10 更新）把文本输入、提示、上传文件、聊天历史等列为可能收集的 User Input，并把提供服务、改进与训练技术、安全及研究列为处理用途。
- 该政策没有为所有数据给出统一天数；写的是按数据量、类型、敏感性、处理目的和法律要求而异，并举例称在提供服务时账户、输入和支付信息可随账户保留。
- 政策写明为提供服务会在中华人民共和国境内直接收集、处理和存储个人数据。
- 政策还明确说，服务不是为处理敏感个人数据而设计或预期使用，不应向其提供敏感个人数据。
- 开放平台条款要求开发者对其输入拥有必要权利、许可和授权，并采取组织与技术措施保护系统和数据；下游应用的终端用户数据处理政策由开发者作为控制者披露。
- DeepSeek Responses 固定显示 `store: false`，同时自动上下文缓存会暂存请求前缀数小时到数天。这两项并不矛盾：前者只说明不支持 OpenAI 式响应存储能力，不能覆盖缓存和其他合规/安全处理。

来源：[DeepSeek 隐私政策](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html) / [DeepSeek 开放平台服务条款](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html) / [DeepSeek：Responses API](https://api-docs.deepseek.com/guides/responses_api/) / [DeepSeek：Context Caching](https://api-docs.deepseek.com/guides/kv_cache)

### 4.2 不能从公开材料确认

- API 请求正文是否默认用于训练，是否存在账户级 opt-out；
- API prompt/output 的精确保留期，以及安全日志、缓存、人工审查、备份各自的期限；
- 是否提供 Zero Data Retention、Modified Abuse Monitoring、DPA、企业不训练条款或可选数据驻留；
- 删除账户或删除历史是否覆盖 API payload、缓存、备份和衍生数据；
- 客户工单描述中不同类别个人信息是否满足 DeepSeek 对敏感个人数据的限制。

因此，B 阶段只能发送本仓库授权范围内的**合成、最小化结构化事实**，且仍按敏感边界管理；C 阶段把真实客户描述/消息发送给 DeepSeek，应视为新的数据处理决策，必须先取得上述问题的书面答案或合同保证，并完成面向客户的披露与授权设计。

## 5. 从现有 Responses strict JSON Schema smoke 迁移

当前 [`release_evaluation.py`](../../agent/src/baseline_agent/release_evaluation.py) 使用裸 `httpx` 调用 `https://api.openai.com/v1/responses`，传入：

- 顶层 `instructions`；
- 一段序列化的固定合成 facts；
- `text.format.type = json_schema`、`strict = true`；
- 本地 `_response_text()` 提取 `output_text`；
- 本地 `evaluate_conclusion()` 再验证字段集合、证据引用、订单引用和业务结论。

### 5.1 可以直接保留

- schema 与最小合成 facts；
- 不发送推理、密钥、审批、执行和最终金额的提示约束；
- `json.loads` 后的本地不变量校验；
- ordinary CI 永远不调用真实模型的原则；
- LangGraph 与 Spring 的既有权限边界。

### 5.2 必须调整

| 位置 | 当前 | DeepSeek 接入建议 |
|---|---|---|
| Endpoint | `https://api.openai.com/v1/responses` | 官方 SDK 配置 `base_url=https://api.deepseek.com` 后调用 Responses；裸 HTTP 的最终路径（是否带 `/v1`）必须先从 SDK 请求或官方支持确认，不自行猜测 |
| 密钥 | `OPENAI_API_KEY` | 独立 `DEEPSEEK_API_KEY`，只进入 Agent Server 进程 |
| 模型 | `OPENAI_MODEL=gpt-5.6-terra` | `DEEPSEEK_MODEL=deepseek-v4-flash` 起步，不复用 OpenAI 变量名 |
| 请求 | 未设输出上限 | 显式设置小型 `max_output_tokens`，第一阶段关闭供应商工具 |
| 思考模式 | 由 OpenAI 模型语义决定 | DeepSeek v4 默认 thinking；应分别实测 enabled/disabled，选择后显式配置并记录 |
| 响应解析 | 只找首个 `output_text` | 先检查顶层 status/error/incomplete，再区分 refusal、空正文、非法 JSON和多 output item |
| 审计 | 只打印模型和场景 | 记录内部 call/attempt ID、供应商 response ID、响应模型、`system_fingerprint`、耗时、usage、cache hit、失败分类；不记录原始正文 |
| 数据参数 | 尚未显式 `store: false` | DeepSeek 不支持 `store`，固定为 false；文档与实现必须同时承认自动缓存仍存在 |

### 5.3 先实测再实现生产 adapter 的契约清单

1. 现有 schema 正例，以及 24/48/72 小时和不满足资格的负例。
2. schema 不合法、额外字段、错误 enum、数组长度不符。
3. thinking enabled/disabled 下的输出稳定性、推理 token、延迟和成本。
4. `response.completed`、`response.incomplete`、`response.failed`、空 output、内容过滤/拒答。
5. 400、401、402、422、429、500、503 与连接、读取、总截止时间超时。
6. 不支持参数被静默忽略的防护测试。
7. 相同前缀请求的缓存命中、`user_id` 隔离与 usage 字段。
8. 网络断开后的重复调用与审计记录；确认任何模型失败均显式转人工，不回退 fake。

## 6. 是否存在更自然且价格合理的候选

由于本仓库已经使用 OpenAI Responses strict JSON Schema，OpenAI 模型在**语义一致性**上仍是最自然对照。OpenAI 官方当前把 `gpt-5.6-luna` 定位为成本敏感、高吞吐模型，支持 Responses 与 Structured Outputs，1.05M 上下文，标价为每百万 token 输入 $0.20、缓存输入 $0.02、输出 $1.20。[OpenAI：GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

与 DeepSeek v4 flash 比较：

- DeepSeek v4 flash 在非高峰输出更便宜（$0.66 vs $1.20），缓存命中输入也更便宜；其非高峰未缓存输入 $0.22 与 Luna $0.20 接近。高峰时 DeepSeek 为输入 $0.44、输出 $1.32。
- DeepSeek 现在也支持 Responses `text.format`，所以“必须重写为 Chat Completions”已不再构成劣势。
- OpenAI 的数据控制文档明确说明 API 数据默认不用于训练，并列出各 endpoint 的滥用监控和应用状态保留规则；DeepSeek 的公开 API 数据处理边界目前更不明确。[OpenAI：Data controls](https://developers.openai.com/api/docs/guides/your-data)

但价格和接口表无法证明任何模型对本项目中文客服、提示注入、证据选择或拒答更优。本阶段不建议再实现第二个生产 provider；可以保留 OpenAI `gpt-5.6-luna` 作为少量离线对照，只有同一评测集显示出明确质量、隐私或总成本优势，才另立 provider 票据。

## 7. 推荐实施边界

### 短期目标 B

1. 建立领域化 `InvestigationModel`，仅有 fake 与 DeepSeek 两个实现。
2. 使用 DeepSeek Responses API，而不是降级到较弱的 Chat JSON Output。
3. 先 shadow，再以同一合成评测集比较 v4 flash/pro。
4. 模型输出只给有限调查判断；Spring 保留授权、事实重读、资格、金额、审批与执行权。
5. 所有模型故障显式转人工，禁止静默回退 fake。
6. 达到预先冻结的 schema、业务正确率、延迟、失败率和成本阈值后，才允许 DeepSeek 结论提交 Spring。

### 最终目标 C

真实客户文字进入模型前，除模型质量外还必须完成：

- API 数据保留、训练退出、缓存、数据位置和合同条款核验；
- 客户文字的字段级最小化、脱敏和授权；
- 提示注入与恶意内容测试；
- 意图、澄清、调查摘要和回复草稿各自的 schema 与权限；
- 客户可见披露、人工接管和删除/更正流程；
- 回复发送前的 Spring 状态机、generation fence 与证据白名单校验。

目标 C 不是把 B 的 input 从 facts 换成全文，而是一项新的产品、隐私和安全能力。

## 8. 未知项与后续证据请求

以下问题在正式发送真实客户数据前必须关闭：

1. DeepSeek 是否能书面确认 API inputs/outputs 默认是否用于训练，以及 opt-out 条件。
2. API 正文、安全日志、硬盘 KV cache、备份的分别保留期和删除范围。
3. 是否提供 DPA、企业不训练、ZDR 或数据驻留选项。
4. Responses `text.format` 的 JSON Schema 子集、refusal/content filter 具体响应形状。
5. 是否存在可调用的不可变模型 snapshot；若不存在，后端模型升级如何通知。
6. 请求 ID 响应头、官方追踪字段、幂等键及重复计费语义。
7. v4 flash/pro 在本项目合成评测集上的质量、延迟、成本和缓存数据。

在这些问题中，4、6、7 可通过受控合成 smoke 验证；1、2、3 需要官方支持或合同材料，不能用一次 API 调用推断；5 需要官方文档或支持确认。
