# Issue #152：自然语言单问题受理验证

## 交付结论

本票在既有公开沟通 v2 前增加独立的 `customer-intake-v1` 受理阶段。客户可以直接描述物流问题；
Spring 只把当前登录客户可见订单的引用与摘要交给 `intake_agent`，Agent 返回候选订单、单一问题理解
或自然语言澄清。客户明确确认前不会创建客服工单，也不会启动既有工单 SLO。

快捷确认与自然语言确认统一调用 `/api/customer/v2/intakes/{intakeId}/messages`，共享稳定请求身份、
持久化消息身份和同一确认事务。确认时 Spring 重新按当前客户读取并锁定订单事实，校验受理时版本；
只有事实仍有效时才调用既有 `CustomerTicketService` 创建唯一工单并启动独立 Agent generation。

## 协议、安全与失败边界

- 新受理入口只接受显式 `customer-intake-v1`、自然语言消息和 `Idempotency-Key`；未知字段、错误版本、
  空消息及请求身份冲突均返回稳定且不泄露内部信息的错误。
- Agent 只能从 Spring 提供的可见订单摘要中建议候选；Spring 对候选引用、问题类型和输出状态再次做
  白名单校验，不接受越权或畸形模型输出。客户可见受理文案由 Spring 根据已验证类型字段生成，不直接展示
  模型自由文本；只有有限的明确确认表达可进入建票事务。
- 低置信度结果停留在自然语言澄清阶段；确认前数据库约束禁止绑定工单，确认后的 intake 与工单是一对一。
- 正式模型模式只选择 DeepSeek 严格 JSON Schema 受理模型；凭据、网络、余额或输出失败均封闭为服务不可用，
  不会回退 fixed-fake。本票规范化验收不需要真实模型调用，真实模型支出为 0 元。
- 前端提供初始、加载、澄清、确认、错误与已创建工单状态，并在窄屏下保持单列可操作布局；候选订单只显示
  引用与摘要，不暴露内部订单事实、prompt、reasoning、checkpoint 或 Agent 地址。

## 规范化验证

2026-08-28 从仓库根目录使用以下独立配置运行完整门禁：

- Compose project：`customer-agent-gate-i152-6261a`
- 镜像 tag：`gate-i152-6261a`
- 前端端口：`42521`

执行前通过 `docker compose -p customer-agent-gate-i152-6261a config --format json` 读回确认项目名、
专属镜像标签、数据卷、网络和端口均属于本轮且不指向 baseline。随后执行：

```powershell
pwsh ./scripts/check.ps1
```

完整门禁退出码为 0：Backend、Agent、Frontend 组件检查、V23 迁移、`FULL_RESET_GATE`、两条 Issue #29
全栈链、React/Spring/PostgreSQL/LangGraph 集成验收、运行日志与 bundle 敏感内容扫描全部通过。
Agent 单元测试为 203 passed；前端单元测试为 89 passed、3 conditional skipped。
真实 Chromium 主矩阵另含 #152 的确认前无票、候选仅摘要、窄屏、加载、错误与确认后建票验收。
