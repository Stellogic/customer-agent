# [基础] Additive 扩展最小工单会话 v2 接缝

> 父规格：[#149 规格 重塑自然语言多工单客服 Agent 与知识工作台](../../specs/issue-149.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/151](https://github.com/Stellogic/customer-agent/issues/151)
> Issue 状态：OPEN
> 创建时间：2026-08-27T17:24:36Z
> 最后更新时间：2026-08-27T17:32:59Z
> 关闭时间：—
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

Part of #149

## What to build

以 expand 方式在既有 v1 旁增加最小的工单会话 v2 产品接缝，并让当前单物流工单通过真实 React、Spring、PostgreSQL、LangGraph 与 SSE 完整运行。v2 只表达当前迁移所需字段，不提前设计后续全部受理、多问题、RAG 或工作台能力。

## Acceptance criteria

- [ ] v1 契约和既有正式场景继续工作，新增 v2 不要求同一 PR 大规模迁移所有消费者。
- [ ] v2 拥有独立、可识别的 schema/view 版本，并拒绝未知字段、非法事件和不兼容版本。
- [ ] 当前单物流工单可以通过 v2 创建、读取权威快照、消费 SSE 并恢复断线。
- [ ] v2 只包含当前单工单迁移需要的身份、状态、消息和游标字段；未来字段由后续纵切片增量增加。
- [ ] 浏览器仍只访问 Spring，同源网络和 bundle 中不出现 Agent 地址、模型密钥、prompt、原始工具载荷或 checkpoint。
- [ ] PostgreSQL、Spring 和前端的兼容测试证明 v1/v2 并存期间重试、权限和消息顺序不漂移。
- [ ] 对应客户页面同时具备桌面、窄屏、loading、empty 和 error 状态，不以静态 mock 替代真实 v2 数据。

## Blocked by

- #150
