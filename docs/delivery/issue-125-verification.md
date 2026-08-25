# Issue #125：DeepSeek Flash 真实契约验证

## 范围与安全边界

本票提供受控、显式 opt-in 的 `deepseek-v4-flash` 真实合成评测入口。它复用 #115 冻结的 `b0-synthetic-evaluation-v1` 数据集、预期与准入门槛，不接入普通 CI、Agent 默认路径或产品流量。脚本只从当前进程继承 `DEEPSEEK_API_KEY`，不会读取 `.env` 文件；密钥不进入命令行值、请求正文、报告、日志、checkpoint 或仓库文件。

评测报告只输出候选模型、版本化计价、调用上限、聚合契约检查、聚合 usage/cache、#115 聚合指标与阻断理由。它不输出或保存 API key、Authorization、订单引用、证据引用、客户正文、提示词、请求/响应正文、供应商 response ID、system fingerprint 或逐场景原始结果。

## 固定调用与费用上限

- #115 的 12 个固定场景重复 5 轮，共 60 个样本；其中错误证据场景每轮都在供应商调用前本地拒绝。
- 真实供应商请求硬上限为 55；每个样本最多 1 次尝试，不重试、不切换模型。
- connect timeout 为 3 秒、read timeout 为 12 秒、单次整体 deadline 为 20 秒、整批 deadline 为 600 秒。
- 401、402、403、429、5xx、网络、超时或供应商 `failed` 状态均立即停止并输出脱敏阻断理由；402 单独标为余额不足。模型拒绝、空输出、非法 JSON、schema 不匹配、不完整或截断响应继续计入 #115 聚合失败率，不会被误报为供应商基础设施阻断。
- 运行前按官方 UTC 峰谷时段冻结本批单价：工作日 01:00–04:00、06:00–10:00 UTC 为峰值，缓存输入/非缓存输入/输出分别为 `0.014/0.44/1.32 USD/M token`；其他时段为谷值，分别为 `0.007/0.22/0.66 USD/M token`。报告记录选择时刻与档位；如果评测跨越计价窗口则阻断准入。不允许看到结果后修改计价输入。

## 契约与准入检查

真实成功响应必须同时证明：strict JSON Schema 请求、`status=completed`、`reasoning.effort=none`、仅允许的请求参数、内部调用/尝试与供应商响应追踪字段、实际 Responses 输出形状、完整 input/output/total usage，以及缓存 token 指标。报告还包含 schema 成功率、业务正确率、安全不变量、拒绝或空输出率、总失败率、P50/P95、成本可测率和单场景平均成本。

只有上述契约检查全部通过，且 60 个样本达到 #115 冻结门槛时，`evaluation.admitted` 才为 `true`；否则必须停止，不能进入真实 shadow。

## 运行与验证命令

离线工程门禁，不读取 key、不访问 DeepSeek：

```powershell
pwsh ./scripts/check.ps1 -Component agent -SkipAcceptance
```

真实运行只能在已把 key 注入当前进程后显式执行：

```powershell
pwsh ./scripts/deepseek-real-evaluation.ps1 -ConfirmProviderSpend
```

脚本不会加载 `.env`。如果凭据保存在 `.env`，操作者必须在受控的当前进程内自行注入，且不得打印、记录、复制或提交密钥。

## 本次真实证据

2026-08-25 在受控一次性进程中从 `D:\customer-agent\.env` 只读取 `DEEPSEEK_API_KEY` 与 `DEEPSEEK_MODEL`，校验模型为 `deepseek-v4-flash` 后执行真实评测。密钥值未被回显、记录、复制到仓库或提交；一次性容器以 `--rm` 结束。脱敏结果如下：

```json
{
  "attempts": {"actual": 55, "maximum": 55, "retries": 0},
  "blockedReason": null,
  "candidateModel": "deepseek-v4-flash",
  "contractChecks": {
    "actualResponseShape": true,
    "allowedParametersOnly": true,
    "cacheReported": true,
    "completedStatus": true,
    "requestTracking": true,
    "strictSchema": true,
    "thinkingDisabled": true,
    "usageReported": true
  },
  "evaluation": {
    "admitted": true,
    "candidateModel": "deepseek-v4-flash",
    "datasetVersion": "b0-synthetic-evaluation-v1",
    "failedScenarioIds": [],
    "failureCounts": {},
    "metrics": {
      "averageCostUsd": 0.000046134,
      "businessCorrectnessRate": 1.0,
      "costMeasurementRate": 1.0,
      "failureRate": 0.0,
      "p50LatencyMs": 770,
      "p95LatencyMs": 1021,
      "refusalOrEmptyRate": 0.0,
      "safetyInvariantRate": 1.0,
      "schemaSuccessRate": 1.0
    },
    "realModelInvoked": true,
    "scenarioCount": 60
  },
  "limits": {
    "callDeadlineSeconds": 20,
    "connectTimeoutSeconds": 3,
    "datasetRepetitions": 5,
    "evaluationDeadlineSeconds": 600,
    "maximumAttemptsPerScenario": 1,
    "maximumProviderAttempts": 55,
    "readTimeoutSeconds": 12
  },
  "pricingObservedAtUtc": "2026-08-25T09:04:45.623181Z",
  "pricingTier": "peak",
  "pricingUsdPerMillionTokens": {
    "cachedInput": 0.014,
    "output": 1.32,
    "uncachedInput": 0.44
  },
  "pricingVersion": "deepseek-time-of-use-2026-08-25",
  "usage": {
    "cacheHitAttempts": 55,
    "cachedInputTokens": 7040,
    "inputTokens": 10065,
    "measuredAttempts": 55,
    "outputTokens": 1014,
    "totalTokens": 11079,
    "unmeasuredAttempts": 0
  }
}
```

结论：Flash 达到 #115 预先冻结的全部准入门槛，可以进入后续独立授权的真实 shadow；本票只形成真实契约与评测证据，不修改 `AGENT_INVESTIGATION_SHADOW_MODE`、不启用产品流量，也不把模型结论提升为 Spring 业务权威。

评测时核对的官方依据：DeepSeek [Responses API](https://api-docs.deepseek.com/api/create-response/)、[Responses API 兼容说明](https://api-docs.deepseek.com/guides/responses_api/)和[模型与价格](https://api-docs.deepseek.com/quick_start/pricing)。

## 本次工程门禁

- `pwsh ./scripts/check.ps1 -Component agent -SkipAcceptance`：ruff、pyright 与 Agent 测试通过；主审及双重审查收紧 4xx fail-fast、实际非思考证据、官方响应形状和整批取消审计后为 `127 passed`。
- `pwsh ./scripts/check.ps1`：Backend、Agent、Frontend 规范化门禁与 `FULL_RESET_GATE` 全部通过，Spring、PostgreSQL、Agent 均为 `UP`。
- 真实 Chromium 主矩阵 `24 passed`；后端重启和加速 Session 到期矩阵通过。
- 完整门禁使用独立 project `customer-agent-issue125-final-c52b`、随机前端端口与镜像 tag `issue125-final-c52b`；浏览器门禁另用独立 project。两组自有容器、卷、网络和专属镜像清理后均回读为空，既有 `customer-agent-baseline` 未被停止或清理。
