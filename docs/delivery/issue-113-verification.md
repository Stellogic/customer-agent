# Issue #113：受控 DeepSeek Responses adapter 验证

## 范围与边界

本票只新增调查判断模型的 DeepSeek adapter，不把它接入默认 Agent 调查路径，也不调用真实模型。普通运行与 CI 仍使用 `FixedFakeInvestigationModel`；缺少 `DEEPSEEK_API_KEY` 或选择当前 Responses API 不支持的模型时，DeepSeek 配置会显式失败，不回退 fake。

adapter 只把合成调查事实中的 `delaySeconds` 发送给供应商。订单引用和证据引用仅在调用前用于本地范围校验，不进入模型请求；输出 schema 也只允许 `compensationReviewRequired` 与 `reasonCode`，Spring 权威订单事实、补偿方式和金额仍不属于模型输出。

## 官方依据

- DeepSeek 官方 [Responses API](https://api-docs.deepseek.com/api/create-response/) 当前只支持 `deepseek-v4-flash`，并定义 `completed`、`incomplete`、`failed` 状态、`output_text`、`usage` 与 `incomplete_details`。因此 adapter 当前拒绝 `deepseek-v4-pro`，显式解析这些状态，并把 `max_output_tokens` 不完整结果归为截断。
- DeepSeek 官方 [Responses API 兼容说明](https://api-docs.deepseek.com/guides/responses_api/) 说明不支持的参数可能被静默忽略。因此请求体只使用本票白名单参数，并通过模拟传输契约测试固定参数集合和严格 JSON Schema。
- DeepSeek 官方 [错误码](https://api-docs.deepseek.com/quick_start/error_codes/) 将 `400`、`401`、`402`、`422` 归为请求、认证、余额或参数错误，将 `429`、`500`、`503` 归为可短暂恢复的限流或服务端错误。adapter 对前一组不重试，对后一组只在最大三次尝试和整体截止时间内有限重试。

## 验证覆盖

模拟传输测试覆盖：

- 严格 schema、受控参数白名单和最小合成输入；
- 完成、失败、不完整、拒绝、空正文、非法 JSON、schema 不匹配和截断；
- 连接超时、读取超时、整体截止时间、确定性 HTTP 错误不重试，以及 `429`、`500`、`503` 有界重试；
- 每次供应商尝试独立记录 provider、调用/尝试标识、响应标识、请求与响应模型、后端指纹、提示/schema 版本、耗时、usage、缓存命中和内部失败分类，同时不记录密钥、原始输入输出、拒绝正文或思维链。调用者只收到稳定的 `MODEL_CALL_FAILED`，不会感知供应商 HTTP、解析或重试细节。

本票不要求也未运行真实 API key 或真实 DeepSeek 调用；真实合成评测、shadow 与正式切换属于后续独立 Issue。
