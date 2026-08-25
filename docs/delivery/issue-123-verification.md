# Issue #123：合成客户文本离线自动回复验证

## 交付范围

- Spring 新增当前客服工单与当前 Agent 处理代次限定的 `customer-communication-input-v1` 读取接口，只返回合成客户描述和最近 20 条公开沟通，不返回订单权威对象、内部记录、审批、执行、凭据或模型数据。
- LangGraph 在完成受控调查后读取该最小上下文，并与 Spring 已授权的订单、延迟、补偿复核结论和证据引用分区后交给独立客户沟通模型。
- 客户文本和公开沟通在模型请求中明确位于 `untrustedCustomerData`；权威调查结果位于 `authorizedInvestigation`。客户文本中的提示注入、退款命令或越权要求不能改变 Spring 的订单、证据、补偿、审批或执行权限。
- 新增可编程离线供应商接缝 `StructuredCustomerCommunicationModel`，严格解析 `customer-reply-v1` 字段集合，并覆盖必要澄清、无需补偿、等待人工审批和转人工四类回复意图。
- 普通运行和 CI 继续使用 `FixedFakeCustomerCommunicationModel`；本 Issue 没有配置、读取或调用真实 DeepSeek/LLM API。

## 安全失败边界

- 供应商拒绝、异常、未知意图、额外字段、错误类型、错误证据或错误 escalation 组合统一形成受控客户沟通失败。
- LangGraph 在沟通上下文缺失或越界时转人工；模型失败、安全校验失败或客户明确要求人工时，不提交调查结论或猜测性回复，而是进入现有人工接管路径。
- 歧义订单的模型澄清 envelope 由 Spring 复核后，其正文通过既有 clarification/public projection 写入；最终调查回复只允许引用当前订单与物流证据可证明的受控自然语言叙述。
- 成功输出仍随调查结论进入 Spring 的同一权威事务；Spring 继续复核当前 generation、`AGENT` 处理模式、生命周期、客户人工偏好、订单、证据、金额和禁止承诺，只有通过后才写入现有公开消息系统。

## 离线评测与规范化门禁

2026-08-25 已执行：

- `pwsh ./scripts/check.ps1 -Component agent -SkipAcceptance`
  - Ruff format/check 通过；
  - Pyright：`0 errors, 0 warnings, 0 informations`；
  - Pytest：`116 passed`；
  - 客户沟通离线评测包含澄清、转人工、不足 24 小时、等待审批、长延迟和提示注入 6 个场景。
- `pwsh ./scripts/check.ps1 -Component backend -SkipAcceptance`
  - Java 编译、Spotless、Checkstyle 与 Gradle `check` 通过。
- `pwsh ./scripts/check.ps1`
  - 三组件完整规范化门禁通过；
  - `FULL_RESET_GATE` 真实 PostgreSQL、Spring、LangGraph、React 与 SSE smoke 通过；
  - 真实 Chromium 跨角色验收 `21 passed`，会话重启/到期门禁通过。

完整 Compose 门禁使用项目 `customer-agent-issue123-44e9`、卷 `customer-agent-issue123-44e9_postgres-data`、网络 `customer-agent-issue123-44e9_{data,services,edge}`、前端端口 `4623` 与镜像 tag `issue123-44e9`。执行前已通过 `docker compose config --format json` 读回；执行后容器、卷和网络均为空。宿主既有 `customer-agent-baseline` 项目及其 `4180` 端口在门禁后仍保持运行。
