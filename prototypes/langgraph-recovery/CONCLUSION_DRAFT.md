# 中文结论草稿：LangGraph 中断恢复与业务幂等边界

> **草稿，等待用户审阅。** 不应把本文当作 Issue resolution；目前不关闭 Issue、不更新 Wayfinder 地图。

## 建议结论

采用“Spring 业务可靠提交 + Agent Server 运行恢复 + Spring 副作用幂等/代次 fencing”的边界是可行的，但必须避免两种错误外推：

1. LangGraph checkpoint 能恢复节点执行，**不等于**业务副作用 exactly-once；节点可能重放，业务工具仍必须由 Spring 用稳定幂等键、参数摘要和唯一约束保护。
2. `langgraph dev` 适合本地功能验证，**不能**作为 Standalone 持久队列和崩溃恢复的证明。本次强制终止实测中，thread/run 元数据仍存在，但 interrupt checkpoint 未按预期恢复。

因此，当前原型足以确定跨服务协议和责任归属；只有在取得 Standalone 许可证/凭据并用 PostgreSQL、Redis 跑过同一故障矩阵后，才能声称“私有 Agent Server 崩溃恢复已验证”。

## 推荐的可靠提交协议

### 1. Spring 本地事务

Spring 在同一数据库事务中：

- 创建当前 `generation`；
- 预生成并保存稳定的 `threadId`（原型用 UUIDv5 便于重复演示；生产只需在事务中生成并持久化随机 UUID，不要求可推导）；
- 创建可靠提交记录，至少包含 `generationId`、`threadId`、`submissionRequestId`、阶段、尝试次数和最后一次未知结果；
- 追加 `GENERATION_CREATED` 审计事件。

提交后再异步访问 Agent Server，不跨服务共享事务。

### 2. Thread 创建与对账

- Spring 使用客户端指定的 `threadId` 调用 `POST /threads`，并设置 `if_exists=do_nothing`、`metadata.generation_id`。
- 响应丢失或超时时，使用同一 `threadId` 重试/读取并核对 metadata；禁止生成第二个随机 thread。
- 原型已在真实本地 Agent Server 验证两次创建返回同一 thread。

Agent Server 的 Create Thread API 明确支持客户端 UUID 与 `if_exists=do_nothing`：[官方 API](https://docs.langchain.com/langsmith/agent-server-api/threads/create-thread)。

### 3. 初始 run 创建与对账

- 每次提交初始 run 前，Spring 生成稳定 `submissionRequestId` 并放入 run metadata。
- 若创建 run 的响应未知，先列出该 thread 的 runs 并按 `submissionRequestId` 对账；找到后记录 `runId`，不盲目再建。
- 一个 generation 仍只对应一个 thread，但允许初始、resume、失败恢复形成多个 run；`runId` 不是业务代次身份。

真实 Agent Server 原型已故意忽略 create-run 响应，再从 metadata 找回唯一 run，观察到 `run_count=1`。

### 4. Resume 去重

- Spring 为用户/系统恢复命令生成 `resumeRequestId`，以唯一约束记录答案摘要和映射的 run。
- 重复的同 ID、同答案直接返回既有映射，不再次调用 Agent Server；同 ID、不同答案作为冲突拒绝。
- 不依赖 `Command(resume=...)` 自身提供业务请求幂等。官方文档也要求副作用可重放并自行幂等：[Durable execution](https://docs.langchain.com/oss/python/langgraph/durable-execution)、[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)。

## 业务工具与 generation fencing

每个可能产生业务写入的 Agent → Spring 命令都必须携带：

- `generationId`、`ticketId`、`operation`；
- 稳定 `idempotencyKey`；
- 关键参数摘要；
- 运行关联信息，如 `threadId`、`runId`、`traceId`（只用于关联，不用于授权）。

Spring 在同一业务事务内先校验当前处理模式、当前 generation、工单/订单关系与命令权限，再按幂等键读取或创建结果。相同键不同参数必须拒绝；相同键相同参数返回既有结果。

原型证明：工具已提交但响应丢失后，LangGraph 会在新 run/新进程重放工具节点；Spring 最终只有一个 effect，并记录 `EFFECT_REPLAYED`。旧 generation 调用被拒且无新 effect。实现时拒绝审计必须先提交，再把错误返回调用方；若在同一事务中先写审计再抛异常并整体回滚，拒绝证据会丢失——首轮原型确实捕获了这个错误。

## 哪些保证属于谁

| 保证 | Agent Server / LangGraph | Spring Boot |
|---|---|---|
| thread、run、checkpoint、运行队列 | 负责 | 只保存业务映射与提交状态 |
| 同一 thread 同时最多一个 run 执行 | Agent Server 队列保证 | 不替代该调度器 |
| generation 是否仍有业务权限 | 不可信 | 每次工具调用重新判定 |
| 提交响应未知后的 thread/run 对账 | 提供可查询资源 | 驱动状态机并决定是否重试 |
| interrupt 与节点恢复 | LangGraph checkpoint | 只管理业务输入和恢复请求去重 |
| 业务副作用最多一次结果 | 不能单独保证 | 幂等键、参数摘要、事务与唯一约束 |
| 旧 generation 迟到输出拒绝 | 不负责 | fencing + 追加式业务审计 |
| 补偿审批和执行授权 | 不负责 | 唯一业务权威 |

Agent Server 官方架构说明：PostgreSQL 保存 assistants、threads、runs 和 checkpoints；Redis 用于 API/worker 间信号、取消和 streaming pub/sub，不保存用户或 run 数据；队列 worker 取得 lease 后执行，同一 thread 一次最多执行一个 run。[Agent Server 架构](https://docs.langchain.com/langsmith/agent-server)

## Local 与 Standalone 的核实结论

### 本地开发服务器

- `langgraph dev` 无需 Docker，适合开发测试；本机在没有 LangSmith key、关闭 tracing 的情况下成功启动，健康检查返回 `{"ok":true}`。
- 未配置 auth 时实际日志为 `auth type=noop`，因此只能绑定 localhost 或可信开发网络，不能暴露给浏览器或外部网络。
- 同一 server 进程内的 thread/run/interrupt/恢复行为通过。
- 强制终止后的 interrupt 恢复失败，所以不能把 local dev 的磁盘 flush 当作崩溃耐久承诺。官方也把它定位为 development/testing：[LangGraph CLI](https://docs.langchain.com/langsmith/cli)、[Local development](https://docs.langchain.com/langsmith/local-dev-testing)。

### Standalone Agent Server

当前官方要求如下：

- 自带 Agent Server 运行时，部署方自管 PostgreSQL 与 Redis；不能放在 scale-to-zero/serverless 环境。
- `DATABASE_URI`：PostgreSQL 保存核心资源、thread state、long-term memory，并管理后台 task queue。
- `REDIS_URI`：实时 streaming 的 pub/sub 信号；不是 run 数据真值。
- `LANGSMITH_API_KEY` 与 `LANGGRAPH_CLOUD_LICENSE_KEY`；启动时进行许可证认证。
- 非 air-gapped 模式需要访问 `https://beacon.langchain.com` 做许可证校验与用量上报。
- Docker/Compose 只适合开发或小规模；官方生产推荐 Kubernetes/Helm。

来源：[Deployment 形态](https://docs.langchain.com/langsmith/deployment)、[Standalone Server](https://docs.langchain.com/langsmith/deploy-standalone-server)、[最低依赖版本](https://docs.langchain.com/langsmith/self-host-dependency-versions)。

许可证边界必须区分：开源 `langgraph` Python 包是 MIT；Standalone Agent Server 属于 LangSmith Deployment，需要单独的 license key。不能从 LangGraph 的 MIT 许可证推导 Standalone 免费可部署。[LangGraph LICENSE](https://github.com/langchain-ai/langgraph/blob/main/LICENSE)

### 认证建议

- 浏览器仍只访问 Spring；用户 Cookie/JWT 不转发给 Agent Server。
- Spring → Agent Server 配置 private network + 独立机器 Bearer secret，并在 Agent Server 配置 `auth.path` 的 custom authentication；不要依赖 noop 默认值。
- Agent Server → Spring 使用另一份用途不同的机器凭据；Spring 仍按 generation 和业务对象逐次授权。
- Secret 不进入 graph state、checkpoint、prompt、trace 或 run metadata。

官方 custom auth 同时适用于 cloud 与 self-hosted；self-hosted 没有可依赖的默认终端用户认证：[Authentication](https://docs.langchain.com/langsmith/auth)、[Custom auth](https://docs.langchain.com/langsmith/custom-auth)。

## 尚未越过的验证门槛

本机当前没有可用的 `LANGGRAPH_CLOUD_LICENSE_KEY` / `LANGSMITH_API_KEY`，沙箱也无法确认 Docker daemon 的主机状态，因此没有运行 Standalone + PostgreSQL + Redis。后续如继续采用私有 Agent Server，应把以下命令级场景作为实施前门槛：

1. 提交 pending run 后杀死 worker，重启后只执行一次并释放/转移 lease；
2. interrupt 后杀死 API/worker，重启后 `Command(resume)` 从原 checkpoint 继续；
3. 工具已提交、响应丢失、worker 重启后，同幂等键只返回原 effect；
4. 重复 resume 与初始 run 提交响应丢失的对账；
5. 旧 generation 在重启前后都被 Spring 拒绝；
6. custom auth 拒绝无 secret、错误 secret 和用户 token 直连。

## 需要用户最终反馈的关键取舍

当前证据把路线压缩为三种：

1. **取得可用 Standalone 许可证并继续（推荐，若个人项目能获得）**：保留已决定的 Agent Server 架构，再跑 PostgreSQL/Redis 故障矩阵。
2. **若无法获得许可证，回到 Wayfinder 重审“私有 Agent Server”决议**：可改成自建 Python 服务 + 开源 LangGraph/PostgresSaver，但必须重新决定队列、worker lease、run API 和恢复职责，不能悄悄把它当等价替换。
3. **只用 `langgraph dev` 演示**：可用于界面/流程演示，但本次负面结果表明不能声称私有 Agent Server 的崩溃恢复已验证；不建议作为最终架构结论。

在用户确认上述取舍前，本草稿不应发布为 Issue resolution。
