# 验证矩阵

> 对应：[验证 LangGraph 中断恢复与业务幂等方案](https://github.com/Stellogic/customer-agent/issues/6)。本矩阵记录原型证据，不是生产验收结果。

## 结果分层

- **PASS / core**：实际 `langgraph==1.2.10` + `SqliteSaver`，每个阶段由新的 Python 进程执行。
- **PASS / local Agent Server**：实际 `langgraph dev` API，同一 server 进程中的 thread/run/interrupt 行为。
- **NEGATIVE / local Agent Server crash**：实际强制终止 `langgraph dev` 后重启的结果。
- **DOC**：当前官方文档确认，但本机未运行 Standalone/PostgreSQL/Redis。

## 矩阵

| ID | 要验证的行为 | 预期不变量 | 结果 | 证据 |
|---|---|---|---|---|
| V01 | generation 与提交记录原子创建 | Spring 事务内同时产生 generation、预分配 threadId 与 outbox；不会出现“有 generation 无提交意图” | PASS / core | `evidence/matrix.json` 的 `GENERATION_CREATED`、`submission_outbox` |
| V02 | 创建 thread 的响应丢失后对账 | 使用同一客户端指定 UUID 和 `if_exists=do_nothing`，重试返回同一 thread；Spring 从 PENDING 变 CONFIRMED，thread 仍只有一个 | PASS / core + local Agent Server | `evidence/matrix.json`；`evidence/agent-server.json#bootstrap` |
| V03 | 创建初始 run 的响应丢失后对账 | run 携带稳定 `submission_request_id`；响应未知时先在该 thread 的 run metadata 中对账，不盲目再建 run | PASS / local Agent Server | `initial_run_reconciled_by_metadata=true`，且 `run_count=1` |
| V04 | 一个 generation 映射一个 thread、允许多个 run | 映射唯一；初始、resume、错误恢复都是同一 thread 上的不同 run | PASS / core + local Agent Server | core 目录 1 thread/2 runs；Agent Server 完整序列同 thread 5 runs |
| V05 | `interrupt/resume` | interrupt 保存下一节点；resume 后从等待点继续，不重跑已完成调查节点 | PASS / core + local Agent Server | `state_next=wait_for_confirmation`；最终 steps 仅各出现一次 |
| V06 | 进程重启后 checkpoint 恢复 | 新 Python 进程从 SQLite checkpoint 的 interrupt/失败节点继续 | PASS / core | `evidence/matrix.json` 中 4 个不同 `process_ids`，最终 `graph_completed=true` |
| V07 | 本地 Agent Server 强制终止后恢复 | 若把 `langgraph dev` 当耐久运行时，重启应恢复 interrupt checkpoint | **NEGATIVE** | thread/run 元数据仍在，但下一节点变为 `__start__`，resume 报 `NoneType`；见 `evidence/agent-server-crash-restart-negative.json` |
| V08 | 重复恢复请求 | 相同 `resumeRequestId` 与相同答案返回既有 run 映射，不再次调用 Agent Server；同 ID 不同答案拒绝 | PASS / core | `duplicate_resume_returned_same_run=true`，Agent run 未新增 |
| V09 | 工具提交成功但响应丢失 | Spring 已有一条 effect；Agent run 失败并停在工具节点，不把 UNKNOWN 当未执行 | PASS / core + local Agent Server | `effect_count_after_loss=1`，Agent Server run 状态为 error |
| V10 | 同幂等键重试 | 重放工具节点返回已有结果，effect 总数仍为 1，并追加 `EFFECT_REPLAYED` | PASS / core + local Agent Server | `effect_count_after_recovery=1`、`effect_replayed=true` |
| V11 | 旧 generation 迟到调用 | Spring 在每次副作用前重验当前 generation；提交拒绝审计后返回错误，不产生新 effect | PASS / core + local Agent Server | `StaleGenerationRejected`、`STALE_RESULT_REJECTED=1`、effect 不变 |
| V12 | Standalone 持久队列与 worker 崩溃恢复 | PostgreSQL 保存 thread/run/checkpoint/queue；Redis 只做信号、取消与 streaming pub/sub；worker lease 后可恢复 | DOC，尚未本机实测 | [Agent Server 架构](https://docs.langchain.com/langsmith/agent-server)、[Standalone](https://docs.langchain.com/langsmith/deploy-standalone-server) |
| V13 | Standalone 环境要求 | PostgreSQL、Redis、LangSmith API key、LangGraph Cloud license key、许可证校验 egress | DOC | [Standalone prerequisites](https://docs.langchain.com/langsmith/deploy-standalone-server#prerequisites) |
| V14 | 认证 | `langgraph dev` 未配置时实际为 noop；self-hosted 不应依赖默认认证，应配置 custom auth 或由内部代理终止认证 | DOC + local observation | `evidence/local-server-environment.json`；[Authentication](https://docs.langchain.com/langsmith/auth) |

## 覆盖结论

Issue 明列的可靠提交与对账、进程重启、interrupt/resume、重复恢复、响应丢失、同幂等键重试和旧 generation 拒绝均已有可运行覆盖。唯一不能由当前机器证明的是 **Standalone + PostgreSQL/Redis 的真实 worker/queue 崩溃恢复**：本地开发运行时的强制重启结果为负，不能外推到 Standalone。
