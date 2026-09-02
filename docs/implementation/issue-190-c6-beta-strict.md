# Issue #190：c6 Beta strict 通道静态实现

2026-08-31，协调接受官方证据支持的最小结构通道改进，授权独立新版本静态实现、测试源码与双轴CR。**当前没有测试/格式/类型/模型/API运行授权**。c5源码固定提交 `5402bd4c438ff68fc9bbc4a01e55080b12499ce9`及全部旧资产、失败、成绩保留；本轮工作起点 `60ead9ef852ced41639a375be17dc9d6b46eac81`。默认产品策略不切换，不读取未见留出/#189新内容。

## 唯一方法变化

保留c5业务充分性规则、固定BGE/RRF产生的授权Top5、Flash、非思考、temperature=0、输出256、每请求20秒上限。c6将传输改为 `POST https://api.deepseek.com/beta/chat/completions`：两条system/user消息、`thinking.type=disabled`、单个 `submit_sufficiency` 函数、`function.strict=true`、指定同名 `tool_choice`。函数只充当结构化结果声明，不执行函数、不发tool结果、不再次请求模型；不注册任何外部工具。

依据[官方Tool Calls strict说明](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/)使用Beta入口；schema仍为sufficient/evidence和chunk/quote，保留required、additionalProperties=false及编号范围。供应商不支持minLength/maxLength/maxItems，因此请求中的quote使用其支持的 `pattern=^[\s\S]{1,24}$`，不向服务器传maxItems。**本地原1–24字符、最多5项、精确类型/字段、sufficient与空证据关系、授权chunk范围及逐字原文检查全部不变**。不截断、去重或修补非法响应，同来源多摘录不计多个独立来源。

请求提示只调整“如何提交参数”的措辞，去掉与函数声明冲突的“不调用工具”，保持“不执行外部操作”；未增加题目ID、答案、主题特例或新的语义规则。新资产在 `agent/src/baseline_agent/knowledge_sufficiency_development/c6/`，c5目录不改。共用 `request_body/parse_response/response_observation` 增加显式Chat分支，旧Responses调用默认行为不变；新增 `decision_text` 共用原始参数提取与既有 `decision_diagnostic`，不另造日志或runner框架。

## 供应商输出及费用接缝

按[官方Chat API](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/)要求单个 `chat.completion` choice，finish_reason=tool_calls、一个同名function、arguments为字符串；拒绝截断、额外普通消息、思维链正文、多函数和其他函数。函数参数沿用原六层校验。普通JSON消息不是回退；HTTP错误、供应商不支持strict、超时、身份漂移、非法参数均停止，不自动重试。

`usage.prompt_tokens/completion_tokens/total_tokens` 映射到既有输入/输出/合计字段，同时记录原始数值字段名；三项须是非负整数且相加一致，不超过既有输入1,048,576/输出256上界。缓存明细若提供则核对，不预支折扣。Chat文档的completion_tokens_details.reasoning_tokens为可选：未提供记null，不伪报0；请求明确禁用思考，响应不得有reasoning_content，若返回非零reasoning计数则拒绝。可信总completion仍全额计入费用。旧Responses对reasoning明细的校验不变。

唯一账本仍由原runner从Git公共目录定位，运行前读取其当时完整内容；每次请求先持久化最坏预留3.148032元，可信usage按官方峰值未缓存输入3/输出9元每百万token结算。结构失败但usage可信仍结算；缺失/矛盾usage或超时保留预留并停，未结算时禁止新请求。供应商实返身份继续与既有账本比较，不能因换协议清空fingerprint或模型标识。

累计总预算仍≤6元，不是新实验额度。协调允许读取的无留出内容摘要 `D:/customer-agent/.scratch/coordination/issue190-independent-c5/diagnostics/EVIDENCE-DIAGNOSTIC-HANDOFF.md` 报告累计上界0.620805元、未结算0、账本hash `1346c248f6a8ed08638e3ebd5ac9c3dbcc4ad9f451851da2fe8601f14ccd8735`；这是收到的阶段元数据，不是本次现场账本查询，未来执行不得以它覆盖活账本。按现有304次验证预算预测4.435968元只是估算，既不保证完成也不构成新增调用授权。

## 固定开发计划与待运行项

沿用同一已见合成开发72题、原顺序、原标签和已保存授权Top5：`knowledge_sufficiency.development_rows()`所绑定的采集归档hash `b4ec9872012c90c795b0356a74f9ac3f4f7343bff207a76b16d9185265b06387`、数据hash `4ba56767f8729ba064f614c856076c30f08e5852bad0255c2bf6b443c31014b6` 不变。未来入口仍为 `scripts/knowledge-sufficiency.ps1 -DevelopmentVersion c6 ...`，独立phase `development_c6`，整批最多72次，每题一次；首个HTTP前固定全部请求字节hash，不续跑c5或拼接旧成绩。任意契约/供应商/预算失败停且metrics=null；仅72/72合法后计算既定四项指标，门槛仍0.90/0.75/0.90/0.85。

当前请求清单**未物化、未验证**；待获离线窗口后用现有构造器生成并保存，不用手工hash冒充运行结果。需要的离线范围：新版请求/Schema、Chat包络和六层校验、usage结算及预算前置、原失败脱敏/不重试、完整72次Mock编排、旧c5的72项请求字节不变；实际PowerShell→Python入口增加c6模式，相关旧组件及格式/类型检查。Mock只验证工程行为，不代替供应商strict能力或质量实测。离线PASS并冻结源码/清单后，再由协调安排真实开发调用。

独立代理已修复其漏接decision_diagnostic的取证接缝；本任务只读其不含留出内容的交接摘要，没有读取原题、标签或输出。已知独立c5仅为evidence_fields失败，具体分支未知；c6依据旧开发c3/c4错误及官方接口改进，不把它写成本次留出根因或抹除旧失败。以后新独立验证的口径由协调安排，不混为c5首次盲测成功。

## 贡献及状态

本阶段贡献为Codex编写的协议适配、测试源码与预算/验证边界记录；不是用户逐行手写、生产验证或新模型指标。测试/格式/类型/构建/模型/API均 **NOT_RUN**，新增实际费用0，无新质量结论；独立静态双轴CR结果完成后补记。没有修改下游接口、依赖、Compose或门禁锁脚本。
