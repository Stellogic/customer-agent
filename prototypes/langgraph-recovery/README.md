# PROTOTYPE — LangGraph 中断恢复与业务幂等

> 对应决策票：[验证 LangGraph 中断恢复与业务幂等方案](https://github.com/Stellogic/customer-agent/issues/6)。这是可丢弃的验证代码，不是生产业务实现。

## 要回答的问题

这个原型验证：在 Spring Boot 持有 generation、可靠提交记录、业务授权和幂等真值，而 LangGraph/Agent Server 持有 thread、run 与 checkpoint 的边界下，提交响应丢失、进程重启、`interrupt/resume`、重复恢复、业务工具响应丢失、同幂等键重试，以及旧 generation 的迟到调用能否保持已接受的不变量。

原型使用三个互不共享事务的 SQLite 文件来显式表示 Spring 业务库、Agent 运行时目录和 LangGraph checkpoint。SQLite 只为快速故障注入；它不替代最终 Spring Boot/PostgreSQL 或 Standalone Agent Server 验证。

## 一条命令运行

在仓库根目录执行：

```powershell
python prototypes/langgraph-recovery/run_prototype.py matrix
```

首次运行前安装隔离依赖：

```powershell
python -m venv prototypes/langgraph-recovery/.venv
prototypes/langgraph-recovery/.venv/Scripts/python.exe -m pip install -r prototypes/langgraph-recovery/requirements.txt
prototypes/langgraph-recovery/.venv/Scripts/python.exe prototypes/langgraph-recovery/run_prototype.py matrix
```

不带 `matrix` 参数会进入手动 TUI；每次动作后都会完整显示当前状态。

## 验证层次

- `matrix`：真实 LangGraph + SQLite checkpointer，跨多个 Python 子进程验证重启与重放；Spring/Agent Server 的 HTTP 边界用两个独立 SQLite 目录模拟。
- `agent_app.py` + `langgraph.json`：供 `langgraph dev` 的真实 Agent Server API 二次验证。它需要 `requirements-agent-server.txt`，且是否需要 LangSmith API key 以当前官方 CLI 行为为准。
- Standalone：本原型不会伪造 Standalone 的 PostgreSQL/Redis/许可证结果；部署要求和未实测项记录在 `CONCLUSION_DRAFT.md`。

## 目录

- `prototype/model.py`：纯状态/标识规则与异常类型。
- `prototype/stores.py`：Spring 权威库和 Agent 目录的最小适配器。
- `prototype/graph_app.py`：LangGraph 图及 checkpoint 装配。
- `prototype/scenarios.py`：故障矩阵与跨进程阶段。
- `evidence/`：每次矩阵运行覆盖生成的 JSON 与文本证据。
