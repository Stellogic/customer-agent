# Issue #190 C真实合成开发回放：结构失败中止

2026-08-31；关联 [Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [Draft PR203](https://github.com/Stellogic/customer-agent/pull/203)。**C的本次唯一开发回放状态为STOPPED / INVALID_DECISION_SCHEMA；未完成72题，不能给出质量PASS或质量FAIL。** 没有自动重试、换提示/模型、修改数据或进入独立验证。

## 运行身份及实际完成数

- RunId：`issue190-c-development-20260831a`。
- 受测干净HEAD：`526b7d0c4d17fd93c875f8ccfa28844328c946d7`；base：`c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。开始前已fetch/main同步、PR Draft回读；离线预检源码 `b9c46a93` 到本HEAD仅文档/证据增量，源码不变。
- 计划：固定合成开发72题，沿用已保存真实Spring硬过滤后的Top-5；实际发出5次请求，合法判定完成4题，第5题结构检查失败，余下67题未发请求。没有删题来评分。
- 请求/返回模型：均 `deepseek-v4-flash`；5次响应没有可用system_fingerprint，保存为null，不能证明底层权重不变。已保存返回标识中未观察到漂移。
- 提示、schema、配置与开发归档SHA不变，见[静态合同](issue-190-sufficiency-c-static.md)及原始报告 `contract`。这不是默认内部搜索的云接入；没有真实客户或业务资料外发。

## 失败的证据与限制

第5次响应HTTP200、status=completed，输入467 token、输出125 token、reasoning=0、cached=256；费用usage可信并结算。JSON解析之后，固定判定结构检查产生 `INVALID_DECISION_SCHEMA`。这个错误不同于供应商余额失败、网络超时、截断或质量指标不达标。

当前代码在结构非法时只保存固定错误码、响应ID/模型/状态、usage和耗时，**没有保存第5次原始输出文本或解析后的错误对象**。因此只能确认固定检查未通过，不能证明具体是字段缺失/多余、顶层类型、布尔类型或evidence数组哪一项不符，也不能仅凭HTTP200与请求strict schema断言供应商严格遵守结构。该证据缺口如实保留，不能补造原文或付费重发来补日志。

前4题的合法结构化结果和全部5次调用观测均保留。[原始阶段报告](evidence/issue190-c-development-20260831a/sufficiency-development.json)的 `metrics=null`，不拿4题子集计算或宣传质量分数。程序在失败后退出非零，共用账本将该开发阶段记为STOPPED，不允许换RunId自动续跑。

## 中止后的静态请求/校验核对

协调要求在归档中区分模型未遵约、请求/解析工程缺陷与契约不一致。核对仅阅读本次报告、固定合同和受测源码，没有重新执行回放或重发请求。

**请求证据**：第5次保存的请求SHA为 `d3a9e630949ed0093103ac435db610d9eacd9115c92be2e750be5914b056e20b`。`knowledge_sufficiency_run.py`先将body序列化成UTF-8字节，对这些字节记hash，再把同一变量作为HTTP `content` 发送，没有另一套请求构造或SDK重写。报告保存的合同schema和文件hash与冻结文件一致。实际线上请求body未单独存副本，因此这里是“运行hash＋合同快照＋固定源码路径”的证据，不冒称抓到代理/供应商端原始报文。

源码构造的 `text.format` 为 `type=json_schema`、`name=knowledge_sufficiency_c_v1`、`strict=true`，schema就是报告中的完整schema对象，不是误传文件名或JSON字符串。[官方Responses API](https://api-docs.deepseek.com/api/create-response/)列出 `text.format.type=json_schema` 和schema字段；但请求strict标志、HTTP200或status=completed本身都不证明输出已经满足本地全部契约。没有证据显示本轮使用了Chat字段 `response_format` 或错误endpoint。

| 本次失败所在的顶层条件 | 请求schema | 本地校验 | 静态结论 |
| --- | --- | --- | --- |
| 顶层是对象 | type=object | isinstance(decision, dict) | 一致 |
| 只有两个规定字段且均存在 | required=[sufficient,evidence]，additionalProperties=false | 键集合恰为这两项 | 一致 |
| sufficient为JSON布尔 | type=boolean | json.loads后type为bool | 一致；未把字符串布尔隐式转换 |
| evidence为数组 | type=array | json.loads后为list | 一致 |

在这些检查之前，程序已接受完成状态、输出message/单个output_text，并成功执行 `json.loads`，否则应产生不同错误码。因而当前记录把失败范围收窄到上述顶层条件，**未发现请求schema与触发失败的本地条件不一致，亦未发现把正常JSON布尔/数组错误解析的代码证据**。

本地另有“充分时证据非空、不充分时为空、片段不重复且引文存在于输入”等更强的交叉条件；这些主要写在固定prompt与本地校验，未全部编码进JSON schema。它们失败的代码是 `INVALID_EVIDENCE`，本次尚未到达该分支，不能把这处已知结构/语义层次差异当成本次原因，也不应为此放宽校验。

**目前可确认的工程缺陷是失败取证不足**：只有成功解析后才将decision写入结果，失败路径只保留metadata，导致无法判别究竟哪个顶层字段违规。根据现有固定源码路径，“响应内容没有遵守请求顶层schema”是较直接的解释；但没有第5次文本，不能严谨地区分模型生成、供应商结构化输出执行或尚未发现的接缝问题，更不能宣称已经证明是DeepSeek模型能力不足。质量指标未算与取证缺口必须同时保留。

**最小下一步建议（未实施）**：先由协调批准只补实验失败取证，在解析前保存有长度上界的合成 `output_text`/其hash及解析后顶层类型、键名和字段类型，不保存Authorization、请求headers或供应商错误正文；不更改prompt/schema/布尔转换规则。使用离线构造的畸形响应验证“保留证据、原样报错、可信usage仍结算、不重试”，不使用本次已见题新增规则。这只能让未来失败可诊断，不能追回本次原文。任何真实续验都需协调另作一次性授权和停止边界决策，继续原共享账本，不能因记录不全重置预算或自动续跑。

## Token、时间与费用

| 已采集项目 | 数值 |
| --- | ---: |
| 实际请求 / 合法完成 / 计划题数 | 5 / 4 / 72 |
| 输入token | 2338 |
| 输出token | 230 |
| 总token | 2568 |
| 缓存命中输入token | 768 |
| 推理token | 0 |
| Python阶段耗时 | 7.730890000006184秒 |
| 启动至结束含wrapper耗时 | 11.3022841秒 |
| 累计已结算费用上界 | **9084微元＝0.009084元** |
| 未结算预留 | **0元** |

每次在发送前预留3.148032元，获得可信usage后按高峰未缓存价格结算并释放差额，未把预留算作实付。`2338×3 + 230×9 = 9084` 微元；计费核对来源为[官方人民币价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)，本次再次确认Flash高峰输入3元/百万、输出9元/百万，未预支缓存/低峰优惠。运行本地时间04:24:53–04:25:05（UTC+8），记录的核对UTC日期为2026-08-30，不是日期记录错误。

0.009084元是预算账本的保守支出上界，**账单实际扣费未采集**；未为核对费用追加余额或其他隐藏API请求。剩余预算上界5.990916元不表示获准重试或进入下一阶段。峰值内存、吞吐量、生产延迟及机器费用未采集；这5次合成调用不是生产规模或可交付准确率证据。

## 保存与窗口归还

[证据索引](evidence/issue190-c-development-20260831a/index.json)包含阶段报告、launch记录、日志和[共用费用账本副本](evidence/issue190-c-development-20260831a/cost-ledger.json)，均按原字节保存并记录SHA。launch.log为空，不能当作有原始模型输出；索引明确 `invalid_response_text=NOT_CAPTURED`。主账本仍位于Git公共目录旁 `.local/issue190-sufficiency/cost-ledger.json`，未清空、重置或删预留。

进程结束由脚本finally释放自有锁，单次宿主回读FREE后已成功通知协调LOCK_RELEASED，阶段窗口归还。之后仅归档；没有72题重新回放、留出/原冻结评测、完整门禁、合入或默认策略切换。A的失败证据与#189资产/门槛保留，下游仍阻塞。

若后续继续，需要协调先决定结构失败的取证/工程修复边界；本轮不修改提示、容错规则、判定schema或数据，不接受畸形输出当正确拒答，不因剩余预算擅自再试。本文不将未完成的开发回放记为方法质量结论。
