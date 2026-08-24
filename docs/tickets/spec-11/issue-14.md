# 由 Agent 调查无需补偿的工单并自主解决

> 父规格：[#11 规格 客服工单调查与补偿审批 Agent MVP 首个纵向切片](../../specs/issue-11.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/14](https://github.com/Stellogic/customer-agent/issues/14)
> Issue 状态：CLOSED
> 创建时间：2026-08-09T11:22:13Z
> 最后更新时间：2026-08-09T16:06:43Z
> 关闭时间：2026-08-09T16:06:43Z
> 同步日期：2026-08-24
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

- #11

## What to build

交付第一条真正完整的 Agent tracer bullet：客户创建一个延迟不足 24 小时的客服工单，Spring 异步启动当前 Agent 处理代次，LangGraph 通过受限工具收集结构化事实，Spring 确定性复核为无需补偿并发布公开结论，最终工单进入已解决。

## Acceptance criteria

- [ ] Spring 在同一事务创建当前 Agent 处理代次、稳定 thread 映射、可靠提交记录和审计事件，提交事务后才异步调用私有 Agent Server。
- [ ] 浏览器连接或 SSE 连接断开不取消调查；创建命令返回可查询的 accepted 结果。
- [ ] thread 创建或 run 提交响应未知时，Spring 使用稳定 threadId、submissionRequestId 和 metadata 查询对账，禁止创建第二个有效 thread 或盲目重复 run。
- [ ] 一个处理代次对应一个稳定 thread 并允许多个 framework run；thread、run 和 checkpoint 标识不被用作身份或授权。
- [ ] Agent 只能调用按当前客服工单、处理代次和 operation 限定的 Spring 工具，并取得最小结构化订单、物流、支付、政策及既有补偿事实。
- [ ] Spring 对延迟不足 24 小时的合成订单独立复核，无待执行动作时发布受控公开结论并将客服工单推进为 RESOLVED。
- [ ] Agent 写命令使用稳定幂等身份和关键参数摘要；相同身份不同参数、越界资源、旧处理代次和未授权 operation 均被拒绝并审计。
- [ ] 普通 CI 使用真实本地 Agent Server/LangGraph、真实 Spring 与 PostgreSQL、可控时钟、假模型和固定工具结果验证完整路径。

## Blocked by

- #13
