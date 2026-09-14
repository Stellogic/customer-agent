# 支付样本失败原因分析

本文保留修复前的诊断事实；后续实现与验证见[修复记录](2026-09-14-payment-fix-verification.md)，原始真实账本没有改写。

## 结论

本次真实失败已定位到**客户回复的流读取阶段**，不是受理失败、动作提前转人工，也没有证据证明是正文语义被 Spring 拒绝。

另通过离线回放确认一个代码缺陷：**普通支付回复收到带 usage 的 `response.incomplete` / `response.failed` 时，适配器仍丢弃该终态的全部元数据与用量**。这能完整复现本次“SCHEMA_MISMATCH、无具体诊断、usage 全空、预算 PENDING”的记录形态。

但是原始失败流没有留存，事件序号异常或流结束未收到终态也能产生同样记录。因此“此次真实请求一定因输出截断而失败”仍不能成立。应分别看待已经证实的代码缺陷与尚未唯一确定的本次触发条件。

## 本次真实失败链

受测提交 `3ab5fc06a2371a64ecfc545274e104c939564480`，运行 `issue230-real-audit-20260914`，场景 `payment_handoff / sample 1`。

1. 受理成功，正式创建支付工单；订单、补偿和支付读取成功，`PAYMENT=PAID`、`REFUND_STATUS=NOT_FULLY_REFUNDED`。
2. 行动模型选择 `SUBMIT_CONCLUSION`，没有选择 `HANDOFF`。
3. 客户回复角色于北京时间 14:24:25.909544 开始请求，约 7.431 秒后失败。记录 HTTP 200、`SCHEMA_MISMATCH`，而 response ID、response status、response model、usage、validationDiagnostic 全为空。
4. Agent 把回复失败转成 `INVALID_MODEL_OUTPUT`，业务代次进入 `HANDED_OFF`。没有发布 Agent 的支付事实说明，客户收到固定转人工通知。
5. usage 未知使账本保持 PENDING，保留 0.094320 元预留；用例间检查返回未结算停止条件，后五个样本 NOT_RUN。它不是超过了本轮 1.5 元额度。
6. 浏览器测试的 `complete()` 只等待 `COMPLETED`，没有在 `HANDED_OFF` 时提前结束，额外等待约 120 秒，因此整例耗时 129.961 秒不代表模型花了这么久。

## 为什么收窄到流读取

`agent/src/baseline_agent/deepseek_customer_communication_model.py`：

- 第 147 行先设 `payload=None`，第 167–177 行等待 `_read_streamed_response()` 返回后才保存 payload。
- 第 268–284 行把流读取抛出的 `CustomerCommunicationFailure` 归为 `SCHEMA_MISMATCH`。如果读取器未返回，payload 和具体诊断仍为空。
- 第 289 行之后才做完整回复结构/信封校验；该分支通常保留已接收的 payload、usage 和字段诊断。
- 支付场景在流读取时缓冲正文，不调用逐段公开发布，所以不符合“Spring 拒绝正文发布后继续读用量”的已有处理分支。

本轮这组空字段与流读取提前抛错一致；不能仅从 `SCHEMA_MISMATCH` 这个宽泛分类就判定“模型完整 JSON 缺字段”。

## 七组离线对照

使用当前源码、真实回复适配器和预算类，HTTP MockTransport 提供合成流，Docker `--network none`。输入复用已有支付测试夹具，仅更换一个流条件；全部是离线诊断，不是额外真实样本或成功率数据。

| 输入条件 | 业务调用 | 记录 token | 记录诊断 | 账本 |
| --- | --- | ---: | --- | --- |
| 正常 completed + 正确信封 | 成功 | 110 | 无失败 | SETTLED |
| incomplete，终态明确含 110 token | 失败，SCHEMA_MISMATCH | null | null | PENDING |
| failed，终态明确含 110 token | 失败，SCHEMA_MISMATCH | null | null | PENDING |
| 终态序号重复，后续载荷含 usage | 失败，SCHEMA_MISMATCH | null | null | PENDING |
| 首个事件缺少序号 | 失败，SCHEMA_MISMATCH | null | null | PENDING |
| 收到文本后正常 EOF，但没有终态 | 失败，SCHEMA_MISMATCH | null | null | PENDING |
| completed，但 JSON 缺 schemaVersion | 失败，SCHEMA_MISMATCH | 110 | REQUIRED / $.schemaVersion | SETTLED |

“序号错误后载荷包含 usage”不代表应用已接受该终态；这两项用于证明日志不能区分原因。**incomplete / failed 两项则已进入明确终态分支，读取到含 usage 的事件后仍主动丢弃，是已经证实的计量缺陷。**

首次运行七组现状断言全部吻合。随后启用“终态含用量就必须保留”的回归断言，容器退出 1：

```text
AssertionError: BUG_REPRODUCED: terminal event supplies usage but adapter discards it
```

这条 RED 捕获的是已证实的终态计量缺陷，不等于回放了原始真实流；本次没有修改实现，尚无修复后的 GREEN。

## 缺陷机制与已有测试缺口

流读取器第 499–504 行对于 incomplete / failed，仅在 `publication_stopped` 为 true 时保留 `candidate` 并返回；其他情况下立即抛错。

支付路径刻意缓冲正文，`publication_stopped` 一直为 false，因此不会进入上述保留路径。上层拿不到终态 candidate，审计记录也拿不到它已有的 usage，预算随后保留 PENDING。

现有 `test_publication_rejection_drains_same_stream_usage_without_publishing_or_retrying` 覆盖的是先发生发布拒绝、再接收失败终态的路径，不能证明普通支付回复也保留失败终态用量。问题是分支覆盖缺口，不需要引入新的架构。

普通回复当前 `max_output_tokens=384`，账本也记录 reservedOutputTokens=384。若供应商确实以 `max_output_tokens` 结束，则会命中本缺陷；但没有真实 incomplete_details，**不据此断言 384 token 是本次根因，也不直接通过加额度掩盖问题**。

## 最小修复建议

1. 将终态元数据/usage 的提取与业务回复是否成功分开：incomplete / failed 仍应使业务失败，但收到的实际 usage、响应 ID、终态和受控原因应保留。
2. 区分流事件解析、序号检查、缺少终态、供应商未完成和完整信封校验；记录失败阶段及简短受控诊断，不必保存全部原文，更不能记录凭据。
3. 用普通支付输入增加终态含 usage 的回归，补上现有测试未覆盖的分支。保持业务失败和转人工断言，不把失败终态当作成功答案。
4. 浏览器等待器遇到错误业务终态时立即给出失败证据，不继续等满 120 秒；此修改改善诊断速度，不改变通过条件。

完成离线修复后再决定单支付样本复验，不能重置本轮 PENDING 或重跑整批来猜原因。本次仅分析，没有新增付费调用、修改业务代码、执行完整门禁或宣称缺陷已修复。

## 证据与复现

- [原评测报告](2026-09-14-project-audit-and-real-llm.md)、[真实调用数据](2026-09-14-real-llm-data.json)。
- [七组离线结果](2026-09-14-stream-diagnosis-data.json)。
- 本地诊断脚本：`.local/audit-20260914/diagnose-stream.py`；RED 日志：`.local/audit-20260914/stream-red.log`。
- 运行前读取 `docs/agents/test-gate-lock.md`，获取门禁；在现有 `customer-agent/agent-test:local` 镜像中挂载当前 `agent/src`、`agent/tests` 和诊断目录，使用 `--network none` 执行 `/app/.venv/bin/python /diag/diagnose-stream.py`。添加 `--require-terminal-usage` 可运行上述缺陷断言。
- 两次离线执行均使用合成凭据、独立容器内临时账本，容器自动移除，未改写真实评测账本。
