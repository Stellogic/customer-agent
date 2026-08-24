# Issue #114：DeepSeek adapter 离线故障与兼容契约验证

## 范围与结论

本票通过调查判断模型的公共 `judge` 接口连接本地可控 HTTP 供应商替身，验证 #113 已实现的 DeepSeek Responses adapter。测试不需要 API key，不访问真实 DeepSeek，也没有把 DeepSeek 接入默认 Agent 调查路径；普通 CI 仍使用固定假模型。本票结果只证明当前 adapter 在离线替身所模拟的协议与故障下符合仓库契约，不声称证明真实 DeepSeek 服务兼容。

## 离线契约覆盖

- 请求只包含受控参数集合、最小合成 `delaySeconds`、严格 JSON Schema、固定 required/enum、禁止额外字段和受限输出上限；订单引用和证据引用不会发送给供应商。
- 调查输入中的证据数组必须精确匹配当前订单的订单与物流引用；越界证据在访问供应商前以稳定 `INVALID_INPUT` 失败。
- 本地替身覆盖 `400`、`401`、`402`、`422` 不重试，`429`、`500`、`503` 在整体预算内有限重试，以及读取超时、整体超时和响应是否产生不明确的断线。连接超时通过同一公共接口的纯离线传输替身稳定触发，避免依赖外网路由与操作系统超时差异。
- required 缺失、enum 越界、额外字段和供应商 payload 注入均以稳定 `MODEL_CALL_FAILED` 返回，不能产生固定假模型结果；每次供应商尝试拥有不同尝试标识并形成独立最小审计记录。
- 审计记录只包含调用/尝试标识、模型与版本、响应元数据、耗时、usage、缓存和失败分类。测试同时检查日志及可序列化审计记录不包含密钥、订单引用、原始提示、模型正文或供应商 payload。

## checkpoint 与持久化边界

DeepSeek adapter 仍未接入默认 LangGraph 图。离线测试使用真实 JSONL 文件写入实现验证 `ModelCallAttemptRecord` 持久化形状，并通过 LangGraph `InMemorySaver` 对公共 `judge` 结果执行实际 checkpoint/回读，反向断言两处均不含敏感材料。该测试图只保存受控判断字段，不代表已经完成默认调查图集成；未来把 DeepSeek 接入 shadow 或正式业务路径时，仍必须在对应独立 Issue 中重新验证真实业务图与 PostgreSQL checkpoint，不能把本票证据外推为后续集成证明。

## 验证命令

- Agent 组件：`pwsh ./scripts/check.ps1 -Component agent -SkipAcceptance`
- 仓库完整门禁：`pwsh ./scripts/check.ps1`

两项命令均不读取 `DEEPSEEK_API_KEY`，也不会调用真实模型。
