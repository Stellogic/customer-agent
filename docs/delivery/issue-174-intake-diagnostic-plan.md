# Issue #174 单次受理诊断冻结

用户在原累计 5 元预算之外明确追加 3 元，当前项目累计上限为 8 元。本诊断不代表发布验收重跑或通过，不变更五场景的既有通过标准。

- 运行标识：`issue174-intake-diagnostic-01`，只执行一次。
- 固定 `deepseek-v4-flash`、既有受理提示与 schema，不更换模型或改写提示。
- 复用 L174-01 的合成订单及两段原输入，最多发起两次受理请求；若首段未返回澄清状态则停止，不创建工单，不触发调查/审批/执行。
- 客户受理适配器单次 POST，无自动重试，输出上限 600 token。为两个受理请求预留 100000 micro-CNY（0.10 元）；不据此声称已获得实际 usage。
- 原已结算 3810222 micro-CNY 和旧轮 1000000 micro-CNY PENDING 全部保留；诊断开始后合计占用上界 4910222 micro-CNY，低于新上限 8000000 micro-CNY。
- 保留原 5000 ms 页面断言结果，额外观察同一请求至 30000 ms，只用于区分等待与结果差异，不将超过 5 秒计为原场景通过。
- 仅保存 HTTP 状态、耗时、允许列表中的受理状态/问题类别、问题数量和 5 秒内标题可见布尔值。不得保存 ID、URL、正文、完整响应、trace、页面快照或凭据。只读解析响应后丢弃未允许字段。
- 原始 Playwright 错误上下文仍留在临时容器中，不导出；专用 JSON 通过 `/diagnostics` 挂载直接保存。
- 诊断有调用后无论观察完成或失败均保留本轮预留 PENDING，不能重新使用；不得自动重跑。
- 所有 Compose 资源与镜像使用新 run ID，清理只针对本轮；运行遵守共享门禁锁。

入口：`pwsh ./scripts/issue174-live-acceptance.ps1 -ConfirmProviderSpend -IntakeDiagnostic -RunId issue174-intake-diagnostic-01`。

诊断完成后先评估证据再决定下一步；不能由诊断自动转入整套发布验收、合入或关票。

## 本次结果

测试提交 `a761826`，运行标识 `issue174-intake-diagnostic-01`。用例加载检查通过，诊断观察完成（Playwright 1 passed，12.0 秒）；这里的 passed 仅表示诊断程序执行完成，不是 L174-01 通过。

初次请求 HTTP 201，3989 ms，NEEDS_CLARIFICATION，issues 数量 0；追加确认请求 HTTP 201，2803 ms，仍为 NEEDS_CLARIFICATION，issues 数量 0。原 5 秒标题观察为 false。证据见 `issue-174-intake-diagnostic-result.json`。

这次观察排除了“只因第二次响应超过 5 秒”的解释，但不能反推旧轮的确切原因。状态未进入确认，也未形成任何拟建问题。Spring 的 `JdbcCustomerIntakeService` 在 Agent 不可用时也可创建人工协助受理并返回类似状态，因此 HTTP 201 不等于模型理解成功；两次 HTTP 操作也不等于两次供应商调用。当前诊断没有记录人工协助原因或供应商失败分类，不能进一步断言模型分类、契约校验或传输哪一环失败。

本次无后续调用。累计已结算仍为 3.810222 元，旧轮 1 元及本次 0.10 元均保留 PENDING，预算占用上界 4.910222 元，剩余未预留额度 3.089778 元。专属资源清理完成，锁回读 FREE。产品接缝的安全错误分类证据仍是下一步所需；本票不通过修改提示、阈值或业务逻辑来掩盖失败。
