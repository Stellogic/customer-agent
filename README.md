# Customer Support Agent

本仓库正在实现“客服工单调查与补偿审批 Agent”。当前代码已贯通客户创建工单、Agent 调查、无需补偿时自主解决、按物流延迟政策生成不可变补偿提案版本、审批人限时排他领取与最终决定，以及已批准补偿的异步执行。模拟部分退款即使在副作用发生后丢失首次响应，也会进入 `UNKNOWN`、保留额度预占并使用原执行身份自动对账；只有权威确认未发生时才会失败并释放预占。订单歧义可在同一处理代次和 thread 内暂停、澄清与恢复；Spring 还会按可控业务时钟形成首次响应和解决 SLA 的不可变预警/违约事实。

## 本地启动

前置条件只有 Docker Desktop 与 Docker Compose。首次启动会构建 React、Spring Boot 和私有 Agent Server，并在同一 PostgreSQL 实例中创建相互隔离的业务数据库与 Agent checkpoint 数据库：

```powershell
Copy-Item .env.example .env
docker compose up --detach --build --wait
```

打开 <http://127.0.0.1:4180>。客户使用合成身份提交物流延迟问题，页面先读取完整 `CUSTOMER_PUBLIC` 权威快照，再从同一视图的 `epoch:sequence` 游标请求 SSE 增量。客服从 <http://127.0.0.1:4180/api/demo/enter/support> 建立服务端 `HttpOnly` 合成会话后进入 `/support`，只显示共享队列与 SLA 违约升级队列的最小摘要；直接访问 `/support` 不会自动提升角色。审批人从 <http://127.0.0.1:4180/api/demo/enter/approver/approver-demo> 进入 `/approver`；审批证据只在当前租约存续时显示，旧 URL 不会自动重新领取责任。两个工作台分别使用独立的 `SUPPORT_WORKBENCH` 与 `APPROVAL_VIEW` 快照、游标和事件流，不提供自由角色切换或越权详情入口。浏览器只请求同源的 Spring `/api`；Agent Server 和 PostgreSQL 均未发布主机端口。

从空数据库重复验证全部基线：

```powershell
pwsh -File scripts/smoke.ps1 -Reset
```

`-Reset` 只删除本 Compose 项目的本地合成数据卷。日常复测可省略该参数。停止服务：

```powershell
docker compose down
```

## 已锁定版本

| 组件 | 精确版本或镜像 |
|---|---|
| React / React DOM | `19.2.7` |
| Node.js | `24.19.0` |
| TypeScript | `6.0.3` |
| Vite | `8.2.1` |
| Spring Boot | `4.1.0` |
| Gradle | `9.3.1` |
| Java | Temurin `25.0.3+9` |
| Python | `3.13.14` |
| LangGraph | `1.2.10` |
| langgraph-checkpoint | `4.2.0` |
| langgraph-checkpoint-postgres | `3.1.2` |
| PostgreSQL | `18.4` |

前端、后端和 Agent 依赖分别由 `package-lock.json`、`gradle.lockfile` 和 `uv.lock` 固定。早期调研中的 Java `25.0.4`、Python `3.13.15` 是候选值；实现时官方容器仓库尚无对应标签，因此没有把它们误写为已运行验证版本。实际验证证据见 `docs/baseline/verification.md`。

## 边界说明

- Spring 业务运行账号与迁移账号分离；Agent runtime 与 checkpoint 迁移账号也分离。
- Spring 业务库与 Agent checkpoint 库没有共享 ORM、跨库外键或跨服务事务。
- `local-demo` profile 提供客户、客服、审批人、Agent、补偿执行器五个合成身份入口；正式 React 页面没有自由角色切换器。
- 客户创建请求使用稳定 `Idempotency-Key`；相同参数重放返回既有工单，不同参数冲突。Spring 在同一事务中写入客服工单、两条公开消息、首次响应事实、审计事件和客户公开事件。
- 客户工单读取按合成客户身份授权；他人访问返回与不存在相同的 `404`。客户投影与 SSE 只包含公开状态、处理模式和公开消息。
- Agent 只提交结构化调查结论与非权威补偿建议；Spring 重新读取业务事实，以十进制定点规则独立判断资格、方式和金额。提案版本与审批证据快照不可修改，客户只能看到等待审批的公开说明。
- 审批人共享队列只暴露提案编号、方式、金额和有效期；领取使用稳定请求身份与限时排他租约。只有当前 `leaseToken/leaseVersion` 持有人能读取按提案版本裁剪的 `APPROVAL_VIEW` 并提交一次最终决定，释放、过期、提案替换或决定完成会立即撤销审批权限。
- 补偿执行器只处理已批准、已预占额度的不可变执行意图。模拟器可确定性注入副作用前失败、响应丢失、确认未发生及持续不确定；`UNKNOWN` 禁止普通重试，对账只接受持久化的 provider query，并始终复用原 `executionId` 与 `idempotencyKey`。对账预算耗尽会保留预占并写入域外运维告警，不会伪装成业务失败。
- 客户澄清是当前唯一使用 LangGraph `interrupt/resume` 的业务路径。Spring 保存当前澄清请求、暂停并续接解决计时，以稳定客户消息身份和 `resumeRequestId` 幂等恢复同一 generation/thread；重复、并发、失效、转人工或客户人工偏好下的回复不能启动错误工作流。
- 首次响应目标按 15 个连续自然分钟计算且从不暂停；解决目标按累计 24 个连续自然小时计算，仅 `WAITING_FOR_CUSTOMER` 暂停。80% 预警和 100% 违约以唯一 SLA 事实与审计事件原子提交，重复调度不会重复通知或投影；共享升级队列不改变生命周期、处理模式或补偿权限，也不授予完整工单读取权。
- 客服共享队列使用独立 `support-workbench-v1` 快照和全局严格递增序号。数据库触发器把队列进入、摘要变化和移除写入白名单事件日志；重复或旧事件被忽略，缺口、裁剪、非法 payload 或不兼容游标要求整体重读快照。队列条目不包含客户、订单、问题描述、转人工理由详情或调查摘要；完整详情 API 只接受当前有效客服分配，并返回 `Cache-Control: no-store`。
- Spring→Agent、Agent→Spring 与补偿执行器探针使用三个不同的本地演示机器令牌；跨能力调用返回 `401/403`。
- 所有账号、令牌和探针数据均为本地合成数据，不可用于生产。

这是学习与演示环境，不声称生产高可用、水平扩展、灾难恢复或真实支付能力。
