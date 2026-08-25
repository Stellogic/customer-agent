# Issue #128 Flash 自主调查正式验收

## 验收边界

- 正式路径同时显式选择 `deepseek-v4-flash` 调查行动模型与调查判断模型；不允许切换模型或回退 fake。
- 行动模型每轮只接收当前处理代次内的最小规范化合成事实，只能返回一个严格 schema 行动；Spring 继续授权工具、返回权威事实并复核结论。
- 单个处理代次冻结为最多 6 个行动、90 秒墙钟、12000 tokens、100000 微美元估算费用、行动循环最多 6 次供应商尝试和 0 次重复行动；每次供应商行动调用仅 1 次、12 秒截止。末端调查判断也仅 1 次、20 秒截止，因此一次成功路径的总上限是 7 次逻辑模型调用、7 次供应商尝试。
- 调查异常统一安全转人工；客户、客服和审批人产品投影不包含思维链、供应商 payload、原始工具响应、提示或 checkpoint。

## 可重复证据

普通 CI 和完整门禁不读取供应商凭据，继续使用确定性行动模型与 fake 判断模型：

```powershell
pwsh ./scripts/check.ps1
```

真实供应商验收必须由调用进程显式提供 `DEEPSEEK_API_KEY` 和固定模型名，并确认费用：

```powershell
$env:DEEPSEEK_MODEL = 'deepseek-v4-flash'
pwsh ./scripts/deepseek-b1-acceptance.ps1 -ConfirmProviderSpend -Phase success
```

该场景通过独立 Compose project、镜像 tag、端口、卷和网络运行真实 Spring、LangGraph、PostgreSQL 与 Flash。断言允许五种事实能力以任意合法顺序出现，只要求完整能力集合、最终提交、受控证据、Spring 权威业务结果和冻结预算；结束后只清理并回读本次自有资源。

失败路径在 checkpoint 只保留稳定失败分类、实际供应商尝试数和已完成工具轮数；Spring 终态断言只输出生命周期、处理模式、受控转人工原因和计数，不输出业务标识、供应商正文或内部 thread/checkpoint 标识。

供应商拒绝、无效输出、缺失或冲突事实、工具暂时失败、重复无进展、预算耗尽、客户人工偏好及旧代次围栏由严格契约测试、Agent 图测试、真实 PostgreSQL/全栈 smoke 与浏览器安全矩阵共同覆盖。真实验收中若出现非预期供应商异常，立即停止，不重跑数据集、不切换模型，并确认该工单安全转人工。

## 脱敏工程指标

- 成功验收固定使用 `deepseek-v4-flash`，实际完成 7 次逻辑模型调用、7 次供应商尝试，估算费用 1056 微美元；Spring 权威终态为调查代次和提交均完成、由 Agent 处理且未转人工。
- 保留的失败证据显示：第三次逻辑调用重复了相同受控行动，系统在第三次工具执行前判定 `REPEATED_NO_PROGRESS`；该轮共 3 次供应商尝试、2 个已完成工具轮次、估算费用 512 微美元，checkpoint 与 Spring 均确认安全转人工，公开原因为 `TOOL_RETRY_EXHAUSTED`。
- 两个 P1 已离线修复：完整事实存在冲突或无法安全继续时，动态严格 action schema 只允许明确 `HANDOFF`；行动、供应商尝试、token、费用和墙钟剩余预算进入 LangGraph checkpoint，跨节点和恢复持续递减，恢复不会重置或扩张预算。
- 最终 Agent 规范门禁通过 168 项测试；完整 `pwsh ./scripts/check.ps1` 通过后端、Agent、前端、全栈与 24 项主浏览器验收。相关冲突、checkpoint 恢复和预算耗尽测试均包含在上述门禁中。

以上指标只来自本票已落盘的脱敏 report、checkpoint/Spring 一致性证据与规范门禁结果；不包含凭据、提示、供应商响应正文、原始工具 payload 或业务标识。

## 里程碑声明

本票只正式完成 B1：真实 Flash 在合成工单中自主选择受控调查行动。客户沟通模型仍为独立的确定性实现；真实供应商客户沟通与里程碑 C 不在本票范围内。
