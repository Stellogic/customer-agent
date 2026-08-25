# Issue #121 离线澄清、恢复与人工接管验收

## 交付边界

- 普通门禁固定使用 `fixed-fake-model-v1` 与受控 Spring 工具替身，不调用真实 LLM API。
- 本票证明 B1 的离线工程路径：必要澄清、同一处理代次恢复、迟到副作用围栏、人工接管与客服授权投影。
- 本票不声明真实 DeepSeek 已完成 B1，也不把 shadow、供应商 smoke 或离线 fake 结果当作真实模型证据。

## 可重复证据

从仓库根目录运行：

```powershell
pwsh ./scripts/check.ps1
```

规范化全栈 smoke 使用真实 Spring Boot、LangGraph Agent Server、PostgreSQL checkpointer 与 PostgreSQL 业务库，并验证：

1. 歧义订单只产生订单确认码问题；非法或重复客户回复遵循稳定幂等语义。
2. 合法回复通过原 thread、原 generation 恢复并最终形成结论，不创建替代处理代次。
3. checkpoint 只保留恢复所需的 `clarificationRequestId`，不保存 `answerDigest` 或 `answerSummary`；这些字段也不进入客户、客服或审批投影。
4. 客户请求人工后，generation 进入 `HANDED_OFF`；迟到事实读取、澄清、结论和回复均被 Spring 当前授权围栏拒绝。
5. Agent 转人工后，未分配客服无法读取详情；当前负责人领取后可读取受控调查行动、事实和证据引用，且看不到 checkpoint 或原始工具/模型 payload。

## 诚实声明

该证据只说明离线、确定性的 B1 工程路径达到本票验收要求。由于本票明确禁止调用真实 LLM API，真实 DeepSeek 的自主策略质量、延迟、成本和供应商失败表现均未在此验证。
