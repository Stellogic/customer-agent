# 已确认结论：LangGraph 中断恢复与业务幂等边界

## 项目定位与运行方式

本项目是简历学习项目和本地面试演示，不要求真正的生产部署。开发与演示阶段使用 `langgraph dev` 运行本地 Agent Server，优先完成 React、Spring Boot、LangGraph 的完整调用链，以及工单调查、工具调用、人工审批 `interrupt/resume`、状态流转和补偿幂等的可运行闭环。

当前不购买 Standalone 许可证，也不把它作为 MVP 前置条件。面试时本地启动 React、Spring Boot 和 LangGraph 服务，并准备录屏作为备用。

推荐的简历表述是：**“完成可运行的全栈 Agent 原型及本地端到端验证”**。不得据此声称建成“生产级 Agent 平台”。

## 原型结论

采用“Spring 业务可靠提交 + Agent Server 运行编排 + Spring 副作用幂等与 generation fencing”的边界可行，但必须避免两种错误外推：

1. LangGraph checkpoint 能恢复节点执行，**不等于**业务副作用 exactly-once；节点可能重放，业务工具仍必须由 Spring 用稳定幂等键、参数摘要、事务和唯一约束保护。
2. `langgraph dev` 可以证明业务流程和 Agent 编排在本地可运行，**不能**证明生产级高可用、水平扩容或正式环境故障恢复。本次强制终止实测中，thread/run 元数据仍存在，但 interrupt checkpoint 未按预期恢复；这是验证边界，不是需要购买 Standalone 才能解除的 MVP 阻塞项。

核心跨进程矩阵 6/6 通过，本地 Agent Server API 检查 8/8 通过。结果覆盖：可靠提交响应丢失后的对账、一个 generation 对应一个 thread 且允许多个 run、跨进程 `interrupt/resume`、重复恢复、工具响应丢失后的同幂等键重试，以及旧 generation 的迟到调用拒绝。

如果以后需要验证进程重启后的状态恢复，可单独使用 LangGraph 开源 Checkpointer + PostgreSQL 执行专项故障测试；该专项不改变当前 MVP 的本地演示定位。

## 可靠提交与恢复协议

### Spring 本地事务

Spring 在同一数据库事务中创建当前 `generation`、预生成并保存稳定 `threadId`、创建可靠提交记录，并追加审计事件。事务提交后再异步访问 Agent Server，不跨服务共享事务。

### Thread 与初始 run 对账

- Spring 使用客户端指定的 `threadId` 创建 thread，并设置 `if_exists=do_nothing` 和 `metadata.generation_id`。
- thread 创建响应丢失时，用同一 `threadId` 重试或读取并核对 metadata，禁止生成第二个有效 thread。
- 每次提交初始 run 前生成稳定 `submissionRequestId` 并写入 run metadata。
- run 创建响应未知时，列出该 thread 的 runs 并按 `submissionRequestId` 对账；找到后记录原 `runId`，不盲目再建。
- 一个 generation 只对应一个 thread，但允许初始、resume 和恢复形成多个 run；`runId` 不是业务代次身份。

### Resume 去重

Spring 为恢复命令生成 `resumeRequestId`，以唯一约束记录答案摘要和映射的 run。重复的同 ID、同答案返回既有映射；同 ID、不同答案作为冲突拒绝。不能依赖 `Command(resume=...)` 自身承担业务请求幂等。

## 业务工具与 generation fencing

每个可能产生业务写入的 Agent → Spring 命令必须携带 `generationId`、业务对象 ID、`operation`、稳定 `idempotencyKey`、关键参数摘要和运行关联信息。关联信息只用于追踪，不能作为授权凭据。

Spring 在同一业务事务内重新校验当前处理模式、当前 generation、对象关系和命令权限，再按幂等键读取或创建结果。相同键不同参数必须拒绝；相同键相同参数返回既有结果。旧 generation 的迟到调用必须被 fencing 拒绝且留下追加式审计。

## 责任边界

| 保证 | Agent Server / LangGraph | Spring Boot |
|---|---|---|
| thread、run、checkpoint 与本地运行编排 | 负责 | 保存业务映射与提交状态 |
| generation 是否仍有业务权限 | 不可信 | 每次工具调用重新判定 |
| 提交响应未知后的 thread/run 查询 | 提供可查询资源 | 驱动对账状态机并决定是否重试 |
| interrupt 与节点恢复 | LangGraph checkpoint | 管理业务输入和恢复请求去重 |
| 业务副作用幂等 | 不能单独保证 | 幂等键、摘要、事务与唯一约束 |
| 旧 generation 迟到输出拒绝 | 不负责 | generation fencing 与审计 |
| 补偿审批和执行授权 | 不负责 | 唯一业务权威 |

## 明确的验证边界

- `langgraph dev` 定位为开发与测试服务器；本机同一 server 进程内的 thread、run、interrupt 和恢复行为已通过。
- 未配置自定义认证时本机日志为 `auth type=noop`，只应绑定 localhost 或可信开发网络；浏览器仍只访问 Spring。
- 本原型没有验证生产级高可用、水平扩容、worker lease 转移或正式环境灾难恢复。
- 开源 `langgraph` 包与 Standalone Agent Server 的许可证边界不同；当前决议是不获取 Standalone 许可证，而不是把 Standalone 误认为免费或已验证。
- 原始通过与负面证据分别保存在 `evidence/`、`VALIDATION_MATRIX.md` 和 `EXECUTION_EVIDENCE.md`。
