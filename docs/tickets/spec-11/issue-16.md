# 通过当前客户澄清请求恢复同一 Agent 处理代次

> 父规格：[#11 规格 客服工单调查与补偿审批 Agent MVP 首个纵向切片](../../specs/issue-11.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/16](https://github.com/Stellogic/customer-agent/issues/16)
> Issue 状态：CLOSED
> 创建时间：2026-08-09T11:22:22Z
> 最后更新时间：2026-08-09T17:26:56Z
> 关闭时间：2026-08-09T17:26:56Z
> 同步日期：2026-08-24
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

- #11

## What to build

当订单无法唯一识别时，让 Agent 以受控客户澄清请求暂停调查。客户对当前有效请求的回复恢复同一 Agent 处理代次和 thread；错误、重复或失效输入不能启动错误工作流。

## Acceptance criteria

- [ ] 订单存在歧义时，Spring 记录当前客户澄清请求，将客服工单置为 WAITING_FOR_CUSTOMER，并向客户发布不泄露内部事实的受控问题。
- [ ] LangGraph 使用调查内部 interrupt 暂停；审批和补偿执行不使用 LangGraph interrupt。
- [ ] 有效回复使用稳定消息身份和 resumeRequestId，绑定当前客服工单、澄清请求、处理代次及答案摘要，并恢复同一 thread。
- [ ] 同一 resumeRequestId 与相同答案重复提交返回原 run 映射；同一身份不同答案返回冲突；一个处理代次允许恢复产生多个 run。
- [ ] 无关回复、旧澄清请求、已替代处理代次、已转人工状态和客户人工偏好均不能恢复调查。
- [ ] 有效恢复后解决计时从原累计值继续，回答不会创建新客服工单或重置首次响应事实。
- [ ] 恢复响应未知时使用稳定身份查询对账，不创建第二个有效恢复；晚到结果受处理代次 fencing。
- [ ] 自动化验收覆盖 duplicate reply、并发客户回复、stale reply、duplicate resume 和浏览器断线后的恢复查询。

## Blocked by

- #14
