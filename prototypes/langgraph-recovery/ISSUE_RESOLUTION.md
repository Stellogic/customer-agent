## 决议

本项目定位为简历学习项目和本地面试演示。开发和演示阶段使用 `langgraph dev` 运行本地 Agent Server，验证 React → Spring Boot → LangGraph 的完整调用链，以及工单调查、工具调用、人工审批 `interrupt/resume`、状态流转和补偿幂等。

### 已验证

- 核心真实 LangGraph 跨进程矩阵 6/6 通过：可靠提交对账、一个 generation/thread 多 run、跨进程 interrupt/resume、重复恢复、工具响应丢失后的同幂等键重试、旧 generation 拒绝。
- 本地 Agent Server API 检查 8/8 通过：thread 与初始 run 对账、interrupt 持久化、工具提交后响应丢失、恢复后复用既有效果、同 thread 多 run、旧 generation 拒绝。
- 强制终止并重启 `langgraph dev` 的负面测试没有恢复原 interrupt checkpoint。该结果明确限定了本地开发服务器的证明范围，不作为 MVP 阻塞项。

### 责任边界

- Agent Server / LangGraph 负责 thread、run、checkpoint、interrupt/resume 和运行编排。
- Spring 负责 generation 与 thread 的稳定映射、可靠提交与未知响应对账、`submissionRequestId` / `resumeRequestId` 去重、业务幂等、逐次授权和 generation fencing。
- LangGraph checkpoint 不等于业务副作用 exactly-once；补偿执行必须由 Spring 的稳定幂等键、参数摘要、事务和唯一约束保护。

### 部署与表述边界

- 不购买 Standalone 许可证，也不把它作为 MVP 前置条件。
- `langgraph dev` 能证明本地业务流程和 Agent 编排可运行，不能据此宣称生产级高可用、水平扩容或正式环境故障恢复。
- 如需验证进程重启恢复，可另用 LangGraph 开源 Checkpointer + PostgreSQL 做专项测试。
- 简历表述固定为“完成可运行的全栈 Agent 原型及本地端到端验证”，避免“生产级 Agent 平台”。面试采用本地启动三项服务，并准备录屏备用。

本地一手证据位于分支 `codex/prototype-langgraph-recovery` 的 `prototypes/langgraph-recovery/`；主要索引为 `CONCLUSION.md`、`VALIDATION_MATRIX.md`、`EXECUTION_EVIDENCE.md` 和 `evidence/`。该 throwaway 原型分支不推送，后续规格只继承上述决议和责任边界，不继承原型实现。

该决议解除 #7 与 #8 对本票的依赖，无需新增决策票。
