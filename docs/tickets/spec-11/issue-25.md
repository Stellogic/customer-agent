# 使客户公开投影在断线、缺口和旧代次事件下自愈

> 父规格：[#11 规格 客服工单调查与补偿审批 Agent MVP 首个纵向切片](../../specs/issue-11.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/25](https://github.com/Stellogic/customer-agent/issues/25)
> Issue 状态：CLOSED
> 创建时间：2026-08-09T11:24:07Z
> 最后更新时间：2026-08-11T06:40:16Z
> 关闭时间：2026-08-11T06:40:16Z
> 同步日期：2026-08-24
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

- #11

## What to build

把客户帮助中心的权威快照和增量流完善为可恢复的 CUSTOMER_PUBLIC 投影。断线、重复、序号缺口、旧 Agent 处理代次和非法上游事件都不能导致客户看到不连续状态或内部信息。

## Acceptance criteria

- [ ] CUSTOMER_PUBLIC 拥有独立投影形状、epoch 和严格递增 sequence；客户先整体替换权威快照，再从快照游标连接 SSE。
- [ ] sequence 小于等于当前值的重复或旧事件被忽略；恰好下一序号才可增量应用，页面不按时间戳排序业务状态。
- [ ] 出现序号缺口、epoch/view/schema 不兼容、非法 payload 或裁剪历史时，前端停止应用增量、关闭旧流并重新取得权威快照。
- [ ] Spring 在快照与事件重放切换实时流之间不漏事件，并在连接、重放和实时投递时重新校验客户与客服工单关系。
- [ ] 旧 Agent 处理代次的迟到事件在 Spring 投影入口拒绝，客户 reducer 再做防御；迟到事件不能发布消息或进度。
- [ ] 未知 Agent 事件和含 prompt、reasoning、原始模型/工具数据、checkpoint、token、thread/run/trace 或内部审批字段的 payload 不进入产品事件日志。
- [ ] 断线时界面明确显示状态可能过期；恢复后从 Spring 快照收敛，不把新快照与旧本地状态拼接。
- [ ] 测试覆盖重复、旧事件、缺口、裁剪、非法字段、未知事件、快照/重放竞争、断线重连、窄屏会话界面和非本人访问。

## Blocked by

- #16
- #18
