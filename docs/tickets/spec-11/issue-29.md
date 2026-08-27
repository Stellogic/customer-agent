# 固化两条全栈验收、真实模型烟测与诚实交付说明

> 父规格：[#11 规格 客服工单调查与补偿审批 Agent MVP 首个纵向切片](../../specs/issue-11.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/29](https://github.com/Stellogic/customer-agent/issues/29)
> Issue 状态：CLOSED
> 创建时间：2026-08-09T11:24:49Z
> 最后更新时间：2026-08-11T11:26:52Z
> 关闭时间：2026-08-11T11:26:52Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

- #11

## What to build

把前序切片固化为可重复运行、可在 3–5 分钟内说明的本地全栈 Agent MVP。最终验收必须跨越真实 React 界面、Spring 应用、从空库迁移的 PostgreSQL、真实本地 Agent Server/LangGraph 和模拟补偿执行器；普通 CI 继续使用假模型与固定工具保持确定性。

## Acceptance criteria

- [ ] 第一条端到端验收覆盖：创建客服工单 → Agent 调查 → 生成提案 → 领取并批准 → 正常执行 → 确认唯一成功补偿 → 客服工单已解决。
- [ ] 第二条端到端验收覆盖：模拟部分退款已记录但补偿执行响应丢失 → UNKNOWN → 禁止普通重试 → 自动对账发现同一结果 → 确认只有一笔补偿和相同客户结果。
- [ ] 两条验收使用真实 React、Spring、真实迁移后的 Spring/Agent PostgreSQL 数据库、真实本地 Agent Server/LangGraph 和模拟执行器；不得用 stub adapter 替换 LangGraph。
- [ ] 普通验收使用可控时钟、确定性 ID、假模型和固定工具结果；断言外部行为、业务状态、持久约束、授权和产品契约，不绑定私有方法或 graph node 数量。
- [ ] 另设少量真实模型 smoke/evaluation，不进入普通 CI；固定合成场景只评价结构化正确性、最小证据和安全不变量，不评价逐字措辞。
- [ ] 生产构建、浏览器网络和日志检查确认不含模型密钥、Agent 内部地址、真实业务数据、prompt、reasoning、原始工具 payload、checkpoint、thread/run/trace 或支付凭据。
- [ ] 完成前端安装、类型检查、单元测试、生产构建、路由级产物检查、键盘/焦点、窄屏和基础屏幕阅读器烟测，并记录验证结果。
- [ ] 提供可从空环境执行的本地启动、迁移、测试和 3–5 分钟演示说明；演示主路径突出补偿执行响应丢失与自动对账，并准备录屏作为后备。
- [ ] 所有演示身份和业务记录均为合成业务数据；清理或重置流程不会触及用户真实数据。
- [ ] 项目文档与简历建议表述为“可运行的全栈 Agent MVP 及本地端到端验证”，明确未验证生产高可用、水平扩展、灾难恢复、真实支付或强制进程重启后的 checkpoint 生存。

## Blocked by

- #16
- #19
- #21
- #24
- #25
- #26
- #27
- #28
