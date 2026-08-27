# Issue #151：最小公开沟通 v2 接缝验证

## 交付结论

本票以 additive expand 方式保留既有 `/api/customer/tickets` v1，并新增
`/api/customer/v2/tickets` 产品接缝。v2 使用独立的
`view=PUBLIC_CONVERSATION`、`schema=public-conversation-v2` 和
`public-conversation-v2:<sequence>` 游标；当前客户 React 页面已经通过 v2 创建工单、读取权威快照并消费
SSE。既有澄清、转人工与关闭等待期动作仍沿用原 Spring 业务命令，不在本票提前设计后续多问题、RAG
或工作台协议。

v1 与 v2 只是在 Spring 产品边界上形成两种兼容投影，不复制 PostgreSQL 业务状态，也不建立第二条
Agent 工作流。两者读取同一张客服工单、公开消息、Agent 处理代次和追加式公开事件，因此 LangGraph
产生的新公开结果可同时被既有 v1 消费者和 v2 客户页面恢复。v2 只暴露当前迁移需要的工单身份、
生命周期、处理模式、公开代次、公开消息、当前澄清与游标字段。

## 协议与安全证据

- v2 创建请求必须显式声明 `public-conversation-v2`，只接受 `schema`、`orderReference` 和
  `description` 三个字段；未知字段、错误类型和空值返回稳定的无效请求错误，不兼容版本返回
  `INCOMPATIBLE_SCHEMA`。
- v2 快照与事件流拒绝 v1、未来版本、负数或非法游标；事件适配只允许既有客户公开事件白名单，
  未知事件要求客户端重新读取权威快照。
- v1 与 v2 共享现有 Session Principal、资源所有权、CSRF、幂等请求身份、消息序号和 Agent
  generation fencing；伪造客户请求头不能替换当前登录主体。
- 浏览器继续只访问同源 Spring API。生产 bundle、API、请求体和 SSE 的既有扫描继续拒绝 Agent
  地址、模型密钥、prompt、reasoning、checkpoint、原始工具载荷和内部 trace。
- 本票不需要真实模型调用；规范化验收使用既有 fixed-fake/deterministic 配置，没有消耗真实模型预算，
  也没有发生假模型回退声明。

## 规范化验证与资源清理

2026-08-28 从仓库根目录使用以下独立配置运行完整门禁：

- Compose project：`customer-agent-gate-issue151-final-f236`
- 镜像 tag：`gate-issue151-final-f236`
- 前端端口：`45152`

执行前通过 `docker compose -p customer-agent-gate-issue151-final-f236 config --format json` 读回确认项目名、
`customer-agent/*:gate-issue151-final-f236` 镜像、`customer-agent-gate-issue151-final-f236_postgres-data`
数据卷、专用网络和 `45152` 端口均属于本轮，且不指向 `customer-agent-baseline`。随后运行：

```powershell
pwsh ./scripts/check.ps1
```

结果为退出码 0：Backend、Agent、Frontend 组件检查，`FULL_RESET_GATE`、两条 Issue #29 全栈链、
React/Spring/PostgreSQL/LangGraph 集成验收、运行日志与 bundle 敏感内容扫描均通过；前端单元测试为
88 passed、3 conditional skipped，HTTPS Chromium 主矩阵为 24/24，Session 重启与加速到期检查通过。

门禁结束后仅对 `customer-agent-gate-issue151-final-f236` 执行
`down --volumes --remove-orphans` 并删除本轮专用镜像标签；回读本轮容器、卷、网络和镜像均为 0。
