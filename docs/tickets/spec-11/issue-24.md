# 在补偿执行结果不明确时安全对账

> 父规格：[#11 规格 客服工单调查与补偿审批 Agent MVP 首个纵向切片](../../specs/issue-11.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/24](https://github.com/Stellogic/customer-agent/issues/24)
> Issue 状态：CLOSED
> 创建时间：2026-08-09T11:24:03Z
> 最后更新时间：2026-08-11T05:22:20Z
> 关闭时间：2026-08-11T05:22:20Z
> 同步日期：2026-08-24
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

- #11

## What to build

让补偿执行器在请求失败或响应丢失时区分“确认未发生补偿”和“结果未知”，并始终使用同一执行身份先对账。重点演示模拟部分退款已经记录但首个补偿执行响应丢失后，系统自动找到同一结果且不会产生第二笔补偿。

## Acceptance criteria

- [ ] 模拟器可确定性注入副作用发生前失败、副作用发生后响应丢失、对账成功、对账确认未发生和对账持续不确定。
- [ ] 结果无法判断时补偿执行进入 UNKNOWN 并记录追加式执行尝试；UNKNOWN 不是失败。
- [ ] UNKNOWN 状态禁止普通执行重试，也不得生成新的 executionId 或 idempotencyKey；客户看到受控的自动确认中说明。
- [ ] 对账使用原 executionId/idempotencyKey 查询模拟器；若副作用已发生，发现同一补偿并推进为 SUCCEEDED，最终只有一条补偿记录。
- [ ] 只有权威确认未发生补偿时才允许从 UNKNOWN 转为 FAILED 并释放额度预占；副作用发生前的已确认失败也遵守这一条件。
- [ ] 对账预算耗尽后保持 UNKNOWN、保留额度预占，并产生不在本项目业务角色界面处理的域外运维告警；不能伪装为 FAILED。
- [ ] 稳定身份不同参数、重复对账投递、对账 worker 并发及响应再次丢失均不产生第二次补偿。
- [ ] 端到端自动化验收证明 268.00 CNY、80 小时示例最终得到唯一 26.80 CNY 模拟退款以及相同客户结果。

## Blocked by

- #23
