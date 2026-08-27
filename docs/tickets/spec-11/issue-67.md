# 修复补偿提案延迟事实一致性与零金额退款边界

> 父规格：[#11 规格 客服工单调查与补偿审批 Agent MVP 首个纵向切片](../../specs/issue-11.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/67](https://github.com/Stellogic/customer-agent/issues/67)
> Issue 状态：CLOSED
> 创建时间：2026-08-12T18:53:06Z
> 最后更新时间：2026-08-23T06:52:10Z
> 关闭时间：2026-08-23T06:52:10Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

Part of #11

## 问题

补偿提案模块存在两个确定性边界缺陷：

1. 延迟事实同时保存 `delayHours` 与 `delaySeconds`，但缺少单一来源或数据库级严格一致性约束；内容摘要未覆盖全部决定 revision 的事实时，可能在事实矛盾或变化后错误复用旧 revision。
2. 已支付订单在 `paidAmount <= 0`，或部分退款比例计算后舍入为 `0.00` 时，可能生成 `eligible` 的零金额提案并由数据库约束以 500 拒绝；这应在业务边界明确判定为不可补偿或受控拒绝。

## 领域词汇与契约

- **延迟事实（Delay fact）**：决定政策档位与提案版本的不可变权威事实。若同时持久化小时与秒，两者必须由数据库确定性约束证明严格一致；内容摘要必须覆盖所有决定 revision 的事实，不能靠摘要掩盖矛盾。
- **可提案金额（Proposable compensation amount）**：经过政策计算、封顶并按分舍入后仍严格大于 `0.00 CNY` 的金额。`paid=true` 不代表正数实付金额；非正实付金额或舍入为零的部分退款不得形成 eligible 提案。
- 数据库继续作为纵深防御，拒绝金额小于等于零的补偿提案；应用层不得把该约束异常暴露为 500。

## 验收标准

- 延迟事实只有一个一致来源，或有数据库级确定性约束保证 `delayHours`/`delaySeconds` 严格一致；迁移与 fixture 证明权限边界。
- 内容摘要覆盖全部决定 proposal revision 的不可变事实。
- 仅改变 hours 或 seconds 的矛盾输入不能被旧 revision 掩盖；相同内容幂等复用；真实事实变化生成新 revision。
- `paid=true` 且 `paidAmount = 0` 或负值时返回明确 ineligible/受控业务拒绝，不创建提案。
- 部分退款计算舍入至 `0.00` 时返回明确 ineligible/受控业务拒绝，不创建提案。
- 正常正金额退款行为保持不变。
- PostgreSQL 约束继续拒绝零/负 proposal amount，应用权限不被扩大。
- 记录并验证迁移、fixture 与角色权限边界。
- 从实时 `origin/main` 开始，以 TDD 完成，运行字面 `pwsh ./scripts/check.ps1`，通过独立 Standards/Spec 双审和 GitHub 四项检查后合并并关闭本 Issue。

## 非目标

- 不改变补偿比例、封顶值或审批/执行生命周期。
- 不创建后继任务。
