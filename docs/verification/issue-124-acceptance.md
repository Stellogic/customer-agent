# Issue #124 无密钥全栈就绪验收

## 验收边界

- 规范化门禁固定使用 `FixedFakeInvestigationModel`、`FixedFakeCustomerCommunicationModel` 与受控 Spring 工具替身。
- 验收不读取已保存的 DeepSeek key，不配置供应商凭据，不调用任何真实 LLM API。
- 本票证明的是 React、Spring Boot、LangGraph、PostgreSQL 与真实 Chromium 组成的离线安全就绪路径，不是任何真实供应商能力证明。

## 可重复证据

从仓库根目录运行：

```powershell
pwsh ./scripts/check.ps1
```

完整门禁中的固定 Chromium、单 worker、零重试矩阵覆盖：

1. 客户创建合成工单，经真实 LangGraph 和 Spring 权威复核收到无需补偿自动回复；客户文本中的提示注入和退款命令只作为不可信业务数据。
2. 歧义订单在原工单、原处理代次请求必要澄清，客户回复后恢复调查，并只收到“等待人工审批”而非未批准金额或执行结果。
3. 客户明确要求人工后停止自动处理；客服在领取前看不到详情，领取后只看到当前分配内的公开沟通、受控事实与证据。
4. 客户 SSE 断线后页面清除旧内容，只从 Spring 权威快照恢复；既有跨角色矩阵继续验证分配撤销和审批租约失效后的即时清屏。
5. 浏览器请求路径、请求体、API 响应和生产全部 JavaScript/CSS bundle 不包含模型密钥标识、Agent 私有地址、模型输入分区、原始响应、工具 payload 或 checkpoint。

## 诚实声明

该证据只表明代码与离线安全就绪。真实 DeepSeek 的自然语言质量、供应商协议表现、延迟、成本与线上失败率均未在本票验证；父规格 #110 的 B0 真实模型切换、B1 真实模型自主策略和 C 真实供应商客户沟通仍未正式完成。

## 本次门禁结果

2026-08-25 已从仓库根目录运行 `pwsh ./scripts/check.ps1`：

- Backend、Agent、Frontend 三组件规范化门禁全部通过；Agent 为 `116 passed`，Frontend 为 `86 passed`。
- `FULL_RESET_GATE` 的 Spring、PostgreSQL 与 Agent 状态均为 `UP`，完整离线 integration smoke 通过。
- 真实 Chromium 主矩阵为 `24 passed`；后端重启和加速 Session 到期矩阵分别通过。
- 生产 bundle 扫描覆盖 24 个 JavaScript/CSS 文件，模型边界禁用内容匹配为 0。
- 完整门禁使用隔离 project `customer-agent-issue124-7c91d6`、端口 `53771` 与镜像 tag `issue124-7c91d6`；浏览器子门禁另用唯一 project。两组自有容器、卷、网络与镜像清理后均回读为空，既有 `customer-agent-baseline` 未被停止或清理。
