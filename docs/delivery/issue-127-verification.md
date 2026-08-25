# Issue #127：正式启用 DeepSeek Flash 调查结论并安全转人工

## 交付边界

本票只把已经通过 #125 真实契约评测与 #126 真实业务 shadow 准入的
`deepseek-v4-flash` 提升为可显式选择的正式调查判断模型。模型仍只返回是否需要补偿复核及受控理由；
Spring 继续重新读取当前处理代次与权威事实，并独立决定补偿资格、方式、金额、审批和执行。
客户沟通模型、B1 自主工具策略、RAG 和自动审批均未在本票扩展。

## 配置与失败边界

- `AGENT_INVESTIGATION_MODEL_MODE=fixed-fake` 是普通运行和 CI 的默认值，不读取供应商凭据。
- `AGENT_INVESTIGATION_SHADOW_MODE=deepseek` 继续表示零业务副作用的 shadow；正式模式与任一启用的
  shadow 配置同时出现时启动失败。
- `AGENT_INVESTIGATION_MODEL_MODE=deepseek-formal` 才允许 Flash 结论进入 Spring 复核；缺少 key、
  缺少显式模型、非 `deepseek-v4-flash` 模型或未知模式均显式配置失败，不回退 fake。
- 每个正式判断最多两次供应商尝试，connect/read/整体截止时间分别为 3/12/20 秒，最大输出 128 token。
  429、500、503 只在该总预算内重试；401、402、拒绝、空输出、非法 JSON、schema 不匹配、截断、
  timeout 和预算耗尽均收敛为受控模型失败。
- 正式模型失败只提交稳定 `INVALID_MODEL_OUTPUT` 转人工请求。V22 数据库迁移将既有 Spring 受控枚举
  与 PostgreSQL 封闭约束对齐；内部失败码不进入客户投影，且不会创建补偿提案或调用 fake。

## 真实与故障验收

2026-08-25 在一次受控外层进程中，仅从 `D:\customer-agent\.env` 读取
`DEEPSEEK_API_KEY` 与 `DEEPSEEK_MODEL`，校验模型仍为 `deepseek-v4-flash` 后运行一个合成工单正式成功场景。
密钥未回显、记录、复制、写入报告或提交。真实模型判断经真实 LangGraph 与迁移后的 PostgreSQL 进入
Spring 当前处理代次复核，最终形成一个既有待人工审批补偿提案，工单仍为 `AGENT / INVESTIGATING`。

随后只使用受控无效凭据运行 401 故障场景，不再读取真实 key。结果为：

- Agent 处理代次 `HANDED_OFF`，可靠提交 `COMPLETED`；
- 工单切换为 `HUMAN`，内部理由为 `INVALID_MODEL_OUTPUT`；
- 补偿提案数为 0，转人工请求数为 1；
- 客户只看到固定安全转人工文案，看不到供应商或内部失败码；
- 没有 fake 调用或模型切换。

离线测试另证明 429 在恰好两次尝试后耗尽预算并返回 `MODEL_CALL_FAILED`，以及正式配置错误、模型拒绝、
timeout、无效输出和 schema 失败不会产生 fake 结果。既有 Spring 代次 fencing、客户人工偏好、并发幂等
与晚到结果测试继续作为越权副作用防线。

真实验收使用唯一 Compose project、前端端口、镜像标签、卷与网络；结束后容器、卷和网络均读回为空。

## 规范化验证

提交前从仓库根目录执行：

```powershell
pwsh ./scripts/check.ps1
```

该完整门禁固定使用 fake，不读取 key、不访问 DeepSeek，并覆盖真实 PostgreSQL、真实 LangGraph、Spring、
React、补偿执行器与浏览器验收。本次执行以退出码 0 完成，其中 Agent 测试 147 项、主浏览器验收
24 项通过；Session 重启/到期分组也完成预期的通过与跳过结果。正式 Flash 的显式验收入口为：

```powershell
pwsh ./scripts/deepseek-formal-acceptance.ps1 -ConfirmProviderSpend
```
