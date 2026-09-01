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

结论：当前没有证据支持修改请求构造、解析器或冻结配置。把 `properties` 内容静默解包、删 `strict`、增加样例提示或改走另一传输都会改变已冻结契约，其中前三者还会使用本轮结果调参。保持质量 FAIL 是当前唯一有证据的处理。

## 证据

- `docs/implementation/evidence/issue169-answer-20260902d/answers.json`
- `docs/implementation/evidence/issue169-answer-20260902d/phase.json`
- `docs/implementation/evidence/issue169-answer-20260902d/http-pg.json`
- `docs/implementation/evidence/issue169-answer-20260902d/ledger-reconciliation.json`
- `docs/implementation/evidence/issue169-answer-20260902c/timeout-release.json`
- `docs/implementation/evidence/issue169-httpx-transport-20260902a/container.json`

## 未完成项

- 48 条完整执行与逐条人工语义评审：`NOT_RUN`。
- 回答层质量门槛：`FAIL`（结构失败，整集未完成）。
- 最终 `pwsh ./scripts/check.ps1 -Issue 169`：`NOT_RUN`。
- 推送、PR Ready、合入、关票、`origin/main` 回读：`NOT_RUN`。
