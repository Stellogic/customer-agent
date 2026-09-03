# Customer Support Agent

本仓库正在实现“客服工单调查与补偿审批 Agent”。当前代码已贯通客户创建工单、Agent 调查、无需补偿时自主解决、按物流延迟政策生成不可变补偿提案版本、审批人限时排他领取与最终决定，以及已批准补偿的异步执行。模拟部分退款即使在副作用发生后丢失首次响应，也会进入 `UNKNOWN`、保留额度预占并使用原执行身份自动对账；只有权威确认未发生时才会失败并释放预占。订单歧义可在同一处理代次和 thread 内暂停、澄清与恢复；Spring 还会按可控业务时钟形成首次响应和解决 SLA 的不可变预警/违约事实。

## 本地启动

前置条件为 Docker Desktop、Docker Compose、PowerShell 7，以及首次准备模型所需的 [uv](https://docs.astral.sh/uv/getting-started/installation/) 和 Hugging Face 网络访问。首次启动会构建 React、Spring Boot 和私有 Agent Server，并在同一 PostgreSQL 实例中创建相互隔离的业务数据库与 Agent checkpoint 数据库。

先准备固定 BGE 模型（此脚本自行持有共享锁，BUSY 时停止，不重试）：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
pwsh -File scripts/prepare-knowledge-model.ps1
```

脚本用 `uv run --frozen` 准备 Python 依赖，并下载、校验冻结 revision `7999e1d3359715c523056ef9478215996d62a620` 到 `.local/models/bge-small-zh-v1.5`。已经完成同一协议完整校验的目录可复用，不必重复下载。也可在 `.env` 中设置 `KNOWLEDGE_MODEL_HOST_PATH` 指向已准备目录。该目录不提交 Git；运行时只读本地文件，不下载、不换模型，缺失或校验失败会明确停止。模型准备不调用 DeepSeek。

随后在仓库根目录同一个 PowerShell 7 进程内启动：

```powershell
. ./scripts/test-gate-lock.ps1
$startupLock = Enter-TestGateLock -Issue manual -CommandType local-start
try {
    docker compose up --detach --wait postgres
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 启动失败' }
    docker compose exec -T postgres psql -U postgres -d customer_agent -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/002-knowledge-vector.sql
    if ($LASTEXITCODE -ne 0) { throw 'vector 扩展准备失败；保留数据并停止' }
    docker compose up --detach --build --wait
    if ($LASTEXITCODE -ne 0) { throw '应用启动失败' }
} finally {
    Exit-TestGateLock $startupLock
}
```

**从旧版本升级已有数据卷也使用以上顺序，不删除卷。** PostgreSQL 官方镜像只在空数据目录执行初始化脚本；换成 pgvector 镜像仅提供扩展文件，已有业务库仍需先以管理员运行上述幂等 `CREATE EXTENSION IF NOT EXISTS vector`，随后才启动 Flyway/应用。新库重复执行同样安全；没有提升 `spring_app`/`spring_migrator` 权限，也不修改已应用迁移。此步骤针对本项目既有 PostgreSQL 18 数据卷，不是跨主版本升级方案。依据：[PostgreSQL 镜像初始化约定](https://github.com/docker-library/docs/blob/master/postgres/README.md#initialization-scripts)、[pgvector 按数据库启用扩展](https://github.com/pgvector/pgvector#getting-started)。

打开 <http://127.0.0.1:4180>。客户从 `/help/login`、客服与审批人从 `/internal/login` 使用本地演示账号完成真实密码校验，浏览器人工身份只由 Spring Security `HttpOnly` Session 表达。客户页面读取 `CUSTOMER_PUBLIC` 权威快照并从同一视图的 `epoch:sequence` 游标请求 SSE 增量；客服与审批工作区分别使用独立的 `SUPPORT_WORKBENCH` 与 `APPROVAL_VIEW` 快照、游标和事件流。旧 `/support` 与 `/approver` 仅保留到正式内部路由的弃用重定向，不建立身份、不重新领取责任，也不包含第二套页面。浏览器只请求同源的 Spring `/api`；Agent Server 和 PostgreSQL 均未发布主机端口。

从空数据库重复验证全部基线：

```powershell
pwsh -File scripts/smoke.ps1 -Reset
```

该命令还会运行 Issue #29 的两条命名 React 全栈验收：正常执行，以及模拟部分退款已发生但响应丢失后进入 `UNKNOWN`、禁止普通重试并自动对账到同一结果。3–5 分钟现场演示与录屏后备见 `docs/demo/issue-29-demo.md`。

普通 CI 始终使用固定假模型和固定工具结果。少量真实模型 release smoke 必须显式执行，且不会读取 Compose 或浏览器身份：

```powershell
$env:OPENAI_API_KEY = '<仅在当前终端设置>'
pwsh -File scripts/real-model-smoke.ps1
```

它只评价固定合成场景的结构化正确性、最小证据和安全不变量，不评价逐字措辞；详细口径见 `docs/delivery/issue-29-verification.md`。

`-Reset` 只删除本 Compose 项目的本地合成数据卷，并运行 `FULL_RESET_GATE`：这是 `scripts/check.ps1` 与 CI 使用的正式全量门禁，包含要求空 fixture 的广域 `integration-smoke`。日常在同一专用数据卷上省略 `-Reset` 时，脚本明确运行 `PERSISTENT_RERUN_SUITE`：覆盖 Issue #29 两条链、本轮唯一 namespace 的持久化与唯一补偿断言、既有自动执行器成功结果的持久证据回读、React live 验收、前端产物和运行日志隐私扫描，以及冻结时钟下的稳定 attempt 排序。它不会为自动执行器创建一笔新的广域 fixture，也明确排除跨历史功能复用固定业务 fixture 的 `integration-smoke`，因为不应通过清库或改写既有业务证据来使其重跑；因此该模式不等价于正式全量门禁。停止服务：

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
- 客服共享队列使用独立 `support-workbench-v2` 快照和全局严格递增序号。数据库触发器把队列进入、摘要变化和移除写入白名单事件日志；重复或旧事件被忽略，缺口、裁剪、非法 payload 或不兼容游标要求整体重读快照。队列条目不包含客户、订单、问题描述、转人工理由详情或调查摘要；完整详情 API 只接受当前有效客服分配，并返回 `Cache-Control: no-store`。
- Spring→Agent、Agent→Spring 与补偿执行器探针使用三个不同的本地演示机器令牌；跨能力调用返回 `401/403`。
- 所有账号、令牌和探针数据均为本地合成数据，不可用于生产。

这是学习与演示环境，不声称生产高可用、水平扩展、灾难恢复或真实支付能力。
