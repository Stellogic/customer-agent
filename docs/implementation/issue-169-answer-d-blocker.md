# Issue #169：answer-d 真实回答阻塞记录

## 结论

`issue169-answer-20260902d` 证明连接修复有效，但冻结客户回答协议未达到质量门槛。运行在 7 条问题后停止：1 条通过产品解析与 Spring 接受，6 条在各自两次 compose 后仍为 `SCHEMA_MISMATCH`，其余 41 条未运行。冻结协议要求 48 条全部执行，因此本次不能评分为 PASS，也不能进入最终完整门禁、合入或关票。

不能根据本次模型结果修改 prompt、选参或冻结输入。也不能把供应商返回的 schema 描述包装静默解包成产品回答；该包装不符合 `customer-reply-v2` 顶层契约，接受它会削弱现有严格校验并把评测反馈写回产品行为。

## 已验证事实

- 运行 HEAD：`27bba7c30eb895d8bf5fdbcf4c0bd4241feb7820`。
- 隔离确定性前置：Python 静态检查 PASS，HTTP/PG 29 项 PASS，投影 SQL PASS，Compose 清理 PASS。
- 供应商连接：13 次请求均得到 HTTP 200；此前 3 秒连接超时未复现。
- 产品结果：1 `ACCEPTED_AWAITING_SEMANTIC_REVIEW`、6 `MODEL_FAILED`、41 `NOT_RUN`。
- 13 次请求中 12 次由 runner 直接按可信 usage 结算；最后一次 HTTP 200 `response.completed` 因 schema 解析先失败而未进入正常 usage 记录，随后只依据已归档完成帧精确补结算。
- 补结算完成后唯一累计账本 SHA-256 为 `6977d70206e53c30371b79243a5a55ba7b49fe983bcac64c20d383c449040a8b`：302 `SETTLED`、2 `TIMEOUT_RELEASED`、0 `PENDING`，累计保守费用 739938 micro-CNY；answer-d 13 次共 119133 micro-CNY。6 CNY 上限未重置。
- 最后一帧为 `deepseek-v4-flash`、`status=completed`、1250 input / 314 output / 1564 total tokens，补结算 6576 micro-CNY。schema 失败分类仍保留。

## 失败形状

失败响应请求了 `text.format.type=json_schema`、`strict=true`，供应商完成帧也回显相同 schema；实际 `output_text` 顶层却是 `type` 与 `properties`，把应有的 `schemaVersion`、`body`、`intent`、`knowledge` 等实例字段放在 `properties` 下。产品按冻结的 `customer-reply-v2` 拒绝该形状是正确行为。

仓库已有 #190 调研记录同类限制：Responses 文档列出 `text.format=json_schema`，但供应商仍可能不遵约；历史开发曾以输出样例调整提示。#169 的冻结协议明确禁止读取本轮模型结果后修改 prompt 或选参，因此不能复用该做法继续付费重跑。

## 接缝诊断

实际 `_build_request` 把输出约束放在 `text.format`，其中 `type=json_schema`、`name=customer_agent_public_reply`、`schema=<customer-reply-v2 JSON Schema>`；answer-d 保存的 `response.created` 原样回显了该对象和 `strict=true`，因此没有请求层级错位或传输丢字段。

DeepSeek 官方 [Create Response](https://api-docs.deepseek.com/api/create-response/) 文档列出 `text.format` 的 `text`、`json_object`、`json_schema` 三种类型，并说明 `name` 与 `schema` 是 `json_schema` 所需字段、输出必须符合给定 schema。官方 [Responses API 指南](https://api-docs.deepseek.com/zh-cn/guides/responses_api/) 将 `text.format` 标为“完整支持”，同时说明不支持的参数会被静默忽略。Create Response 参数表没有单独列出 `strict` 子字段；这只能说明没有专项承诺，不能证明删掉 `strict` 会修复本次输出。冻结协议又明确要求 strict JSON schema，因此不凭猜测改变该字段。

产品流解析从 `response.completed.response.output[].content[].output_text` 读取最终文本，并验证它与全部 `response.output_text.delta` 拼接结果一致。该路径与官方 SSE 事件表一致，answer-d 中的失败文本在 delta、`output_text.done` 和 `response.completed` 三处一致。因此失败不是本地选错事件或截断，而是供应商完成响应本身不符合其回显的 schema。

后续协调核查确认 `strict` 并非 DeepSeek 官方 `text.format` 三键之一。适配提交 `dccc92b` 因此只删除该未文档字段，不改 prompt、schema 或质量门槛，并先保留完整 `response.completed` 再做严格解析，使失败也能正常结算 usage。离线回归与双轴审查均 PASS。

稳定 HEAD `c596400ae543270022979c96242daa32e31638f8` 随后只执行一次冻结 canary `issue169-canary-20260902a`，固定 `delivery-01-a` 且最多一次 compose。供应商返回 HTTP 200 completed，顶层已经是 `body/escalationRequired/evidenceRefs/intent/knowledge/referencedOrder/schemaVersion`，不再是 `{type,properties}` schema 描述包装；但完整产品解析/校验仍判定 `SCHEMA_MISMATCH`。该次 1261 input / 587 output / 1848 total tokens 已按 9066 micro-CNY 结算，账本 0 PENDING。

Canary 证据仅保存了非敏感顶层形状和审计字段，没有保存具体回答字段值；在一次 canary 限额已用完后，无法不新增付费调用地进一步区分引用、正文授权、枚举或其他深层值错误。不能因顶层正确而降低完整 envelope、引用和 Spring 校验，也不能补跑第二次 canary。因此该路线仍保持质量 FAIL 并停止付费调用。

协调随后授权在唯一 6 CNY 账本内继续做有界诊断。稳定 HEAD `9ff05aa70716fd64fb1cca11593a66b4ce597b11` 的 `issue169-canary-diagnostic-20260902b` 仍只执行 `delivery-01-a` 一次 compose：HTTP 200 completed、顶层七键与完整 JSON Schema 均通过，失败被收窄到根级 `DOMAIN_VALIDATION/customer_reply_policy`。该次 1261 input / 753 output / 2014 total tokens，保守结算 10560 micro-CNY；累计账本 304 `SETTLED`、2 `TIMEOUT_RELEASED`、0 `PENDING`、759564 micro-CNY，SHA-256 为 `07f00fa5078c93e513eb4b8e98d1ab480a90c8400d32d436c86e0cc72eb4d076`。

根级代码仍不足以区分知识引用、证据引用、意图、正文授权与事实叙述规则。后续源码把原校验逐项映射为固定规则码与 JSON path，校验入口继续对任一违规抛出同一 `INVALID_OUTPUT`；诊断不保存正文、引文、标识符或密钥。`issue169-20260902-focus44` 的 Ruff format/lint、生产源码 Pyright 与 45 个 owned tests 均 PASS，`paid_model_calls=0`，Standards / Spec 双轴审查均 PASS。下一次付费 canary 必须绑定该诊断源码的稳定提交，仍固定一题和最多一次 compose。

稳定提交 `44dca0ae271290cc95cfa195a16e841886ed2484` 上两次申请执行 `issue169-canary-policy-20260902c` 均被宿主 auto-review 拒绝。第一次以当前显式禁模边界为由；第二次在协调任务转述用户永久授权及纯合成输入、唯一账本不超过 6 CNY 等限制后，仍因授权不是本任务中的直接用户确认而拒绝。两次均未获取测试锁、未启动运行环境、未调用供应商且账本未变化。不得通过间接脚本或其他路径绕过审批。

用户随后在本任务直接授权所有 DeepSeek 调用，并把唯一累计上限收紧到 5 CNY。`issue169-canary-policy-20260902c` 因而在 HEAD `73926b5e6f9a1ed65a809fdcc8d5bbd0ef7ca10e` 合法执行一次：HTTP 200 completed、JSON Schema 和顶层七键通过，失败定位为 `DOMAIN_BODY_AUTHORIZATION` at `$.body`。该次 1261 input / 892 output / 2153 total tokens，已结算 11811 micro-CNY；账本变为 305 `SETTLED`、2 `TIMEOUT_RELEASED`、0 `PENDING`、累计 771375 micro-CNY，SHA-256 `bd8b1e50f18a965d2ee10434103aa7e59c32123423edbe81de9fe3df6defc14b`。确定性 HTTP/PG 29 项、投影 SQL、清理均 PASS。

`BODY_AUTHORIZATION` 仍合并金额、时限承诺、敏感泄露、姓名签收、工单状态、订单号范围与补偿措辞等规则，不能据此判断具体失败接缝。后续继续复用同一正文策略函数，仅把原 `False` 等价映射为有限固定子码；不记录正文、匹配片段或实际值，也不改变拒绝顺序。`issue169-20260902-focus45` 的 Ruff、生产源码 Pyright、45 tests 和 Standards / Spec 双轴审查均 PASS，`paid_model_calls=0`。

稳定 HEAD `9b44b254d84cdf666b06e6e1ec72e38325d2be28` 的最终定向 canary `issue169-canary-body-policy-20260902d` 再次只执行 `delivery-01-a` 一次 compose。供应商返回 HTTP 200 completed，JSON Schema 与顶层七键通过，但固定子码明确为 `DOMAIN_BODY_COMPENSATION_LANGUAGE` at `$.body`：生成正文没有满足冻结的补偿措辞规则。该规则已经由冻结 prompt 明确要求，按模型结果放宽正文或修改 prompt/schema 都会降低门槛并污染评测，因此不存在合法的本地映射或兼容接缝；付费诊断路线在此停止，回答质量保持 FAIL。

本次 1261 input / 866 output / 2127 total tokens，已结算 11577 micro-CNY。唯一账本最终为 306 `SETTLED`、2 `TIMEOUT_RELEASED`、0 `PENDING`，累计 782952 micro-CNY（0.782952 CNY，低于用户直接授权的 5 CNY 上限），SHA-256 `2627bb4fbf09bfe66515ebd393c13064790faa63a0b95a21d987eb3104c2d312`。确定性 HTTP/PG 29 项、投影 SQL、Compose 清理和锁释放均 PASS。

用户随后明确要求优先尽快跑通，并允许在不影响实际使用的前提下放宽过严规则。仓库 ADR 0008 要求自然语言不受少数固定模板限制，Issue #149 测试决策也禁止逐字断言自然语言；因此“必须逐字包含当前不符合补偿条件”属于展示文案约束，不是业务安全边界。修订后由结构化 intent 与 Spring 权威事实承载补偿结论，正文仍拒绝明确的已/将/会/承诺/同意补偿或退款、金额、时限承诺、敏感内容、错订单、提前结案与无依据事实，但允许自然否定表达。正文不触发任何补偿或退款执行。`issue169-20260902-focus50` 的 Ruff、生产源码 Pyright、60 tests 和 Standards / Spec 双轴审查均 PASS；Java 测试源码已补，待下一次真实 Spring canary 重新编译并验收。

HEAD `c1ecf5069aab50cf9a992d03e8594e71b78421f9` 的 `issue169-canary-natural-20260902e` 重新编译了 Spring 并执行一次单题 compose。自然补偿措辞已不再阻塞，新的固定失败码为 `DOMAIN_BODY_ORDER_REFERENCE_REQUIRED`：结构化 `referencedOrder` 正确，但正文没有重复打印订单号。本次 1261 input / 896 output / 2157 total tokens，结算 11847 micro-CNY；账本 307 `SETTLED`、2 `TIMEOUT_RELEASED`、0 `PENDING`、累计 794799 micro-CNY，SHA-256 `7305f21b6b66017597a391367beb06b65c665e9501839e8890d66480bbaf3ac1`。

订单号重复同样是展示格式。修订允许正文省略当前订单号，但正文显式出现任何其他 `ORDER-*` 仍拒绝；结构化 `referencedOrder`、evidence 与当前工单继续精确绑定，场景词和数值事实 grounding 保留。`issue169-20260902-focus52` 的 Ruff、生产源码 Pyright、61 tests PASS，最终 Standards / Spec 双轴复审均 PASS；Java 完成流入口的重复检查也已删除并补正反测试源码。

## 证据

- `docs/implementation/evidence/issue169-answer-20260902d/answers.json`
- `docs/implementation/evidence/issue169-answer-20260902d/phase.json`
- `docs/implementation/evidence/issue169-answer-20260902d/http-pg.json`
- `docs/implementation/evidence/issue169-answer-20260902d/ledger-reconciliation.json`
- `docs/implementation/evidence/issue169-answer-20260902c/timeout-release.json`
- `docs/implementation/evidence/issue169-httpx-transport-20260902a/container.json`
- `docs/implementation/evidence/issue169-canary-20260902a/canary.json`
- `docs/implementation/evidence/issue169-canary-20260902a/phase.json`
- `docs/implementation/evidence/issue169-canary-diagnostic-20260902b/canary.json`
- `docs/implementation/evidence/issue169-canary-diagnostic-20260902b/phase.json`
- `docs/implementation/evidence/issue169-canary-diagnostic-20260902b/ledger-summary.json`
- `docs/implementation/evidence/issue169-20260902-focus44/phase.json`
- `docs/implementation/evidence/issue169-canary-policy-20260902c/approval-blocked.json`
- `docs/implementation/evidence/issue169-canary-policy-20260902c/canary.json`
- `docs/implementation/evidence/issue169-canary-policy-20260902c/phase.json`
- `docs/implementation/evidence/issue169-canary-policy-20260902c/ledger-summary.json`
- `docs/implementation/evidence/issue169-20260902-focus45/phase.json`
- `docs/implementation/evidence/issue169-canary-body-policy-20260902d/canary.json`
- `docs/implementation/evidence/issue169-canary-body-policy-20260902d/phase.json`
- `docs/implementation/evidence/issue169-canary-body-policy-20260902d/ledger-summary.json`
- `docs/implementation/evidence/issue169-20260902-focus50/phase.json`
- `docs/implementation/evidence/issue169-canary-natural-20260902e/canary.json`
- `docs/implementation/evidence/issue169-canary-natural-20260902e/phase.json`
- `docs/implementation/evidence/issue169-canary-natural-20260902e/ledger-summary.json`
- `docs/implementation/evidence/issue169-20260902-focus52/phase.json`

## 未完成项

- 48 条完整执行与逐条人工语义评审：`NOT_RUN`。
- 回答层质量门槛：`FAIL`（供应商正文未满足冻结补偿措辞，整集未完成）。
- 最终 `pwsh ./scripts/check.ps1 -Issue 169`：`NOT_RUN`。
- 推送、PR Ready、合入、关票、`origin/main` 回读：`NOT_RUN`。
