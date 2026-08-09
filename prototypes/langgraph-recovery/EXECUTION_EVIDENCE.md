# 执行证据索引

## 已执行命令

核心矩阵（最终退出码 0）：

```powershell
$env:LANGGRAPH_STRICT_MSGPACK='true'
$env:LANGSMITH_TRACING='false'
.\.venv\Scripts\python.exe .\run_prototype.py matrix
```

输出为 6 项 PASS：可靠提交对账、单 generation/thread 多 run、跨进程 interrupt/resume、重复恢复、响应丢失后的同键重试、旧 generation 拒绝。

本地 Agent Server：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\langgraph.exe dev --no-browser --no-reload --port 2024

.\.venv\Scripts\python.exe .\server_probe.py bootstrap
.\.venv\Scripts\python.exe .\server_probe.py resume-loss
.\.venv\Scripts\python.exe .\server_probe.py recover
.\.venv\Scripts\python.exe .\server_probe.py stale
.\.venv\Scripts\python.exe .\server_probe.py report
```

最终 `agent-server.json` 的 8 项检查全部为 true。服务器健康检查实际返回 `{"ok":true}`。

## 固定版本

- Python：3.12.13（本机实际原型运行时；候选 3.13 基线未在本机复现）
- `langgraph==1.2.10`
- `langgraph-checkpoint==4.2.0`
- `langgraph-checkpoint-sqlite==3.1.0`
- `langgraph-sdk==0.4.2`
- `langgraph-cli==0.4.31`
- `langgraph-api==0.12.1`
- `langgraph-runtime-inmem==0.32.1`

## 原始证据

- `evidence/matrix.json`：核心跨进程矩阵、完整 Spring/Agent 快照、包版本。
- `evidence/matrix.txt`：适合人工快速检查的一行一场景结果。
- `evidence/agent-server.json`：真实本地 Agent Server API 的最终汇总。
- `evidence/agent-server-*.json`：每个 Agent Server 阶段的原始返回。
- `evidence/agent-server-crash-restart-negative.json`：强制终止本地 dev server 后 checkpoint 未按预期恢复的负面证据。
- `evidence/local-server-environment.json`：健康检查、noop auth、许可证 metadata loop 与 Windows UTF-8 启动观察。

## 环境偏差与可复现提示

1. 首次用 MSYS Python 创建虚拟环境时，PyPI TLS 证书链校验失败；改用 Codex bundled Windows Python 后安装成功，不能解释成包不存在。
2. Windows 中文默认编码下，CLI 读取自带 OpenAPI 文本触发 GBK `UnicodeDecodeError`；仅给 server 进程设置 `PYTHONUTF8=1` 后启动成功。
3. 当前会话未检测到 `LANGSMITH_API_KEY` 或 `LANGGRAPH_CLOUD_LICENSE_KEY`。`langgraph dev` 在关闭 tracing 时仍成功启动，并记录 noop auth；这不代表 Standalone 不需要许可证。
4. 沙箱内 Docker 客户端存在但看不到 daemon；未做主机 Docker Desktop 状态断言，也未运行 Standalone。
