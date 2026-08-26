# Issue #129 Compose baseline 误删事故

## 事故状态

- 事故时间：2026-08-26 10:51:30–10:51:44（Asia/Shanghai）。
- 当前处置：用户明确授权后，已从干净且核验到当前 `origin/main` 的 detached worktree 重建 baseline；没有恢复旧运行时数据，也没有执行 VHDX 恢复、prune 或触碰 main-preview。
- Issue #129 已落盘的脱敏业务证据保持完整；事故后没有新增供应商调用。

## 影响

一次未隔离的完整规范门禁调用删除了以下 `customer-agent-baseline` 资源：

- 容器：`frontend-1`、`compensation-executor-1`、`backend-1`、`spring-migrate-1`、`agent-server-1`、`agent-migrate-1`、`postgres-1`。
- 网络：`data`、`provider-egress`、`edge`、`services`。
- 卷：`customer-agent-baseline_postgres-data`。

只读回读确认 baseline 容器、网络和卷均不存在。未发现 baseline 专用 dump 或卷备份；2026-08-17 的 Docker Desktop 整盘备份早于本轮 baseline，不能证明包含事故前数据，也没有在本任务中执行恢复。

## 根因

执行者在运行完整 `pwsh ./scripts/check.ps1` 前，没有先设置并读回唯一 Compose project、镜像 tag 与端口。调用链为：

1. `scripts/check.ps1` 调用 `scripts/smoke.ps1 -Reset`；
2. `scripts/smoke.ps1` 裸执行 `docker compose down --volumes --remove-orphans`；
3. `compose.yaml` 的默认 project 固定为 `customer-agent-baseline`；
4. 当时的规范入口既不要求显式 project，也不验证有效配置，现有网络策略测试不能阻止卷删除。

因此，工作树隔离没有转化为 Docker 资源隔离，破坏性 reset 直接命中了 baseline。

## 预防措施

- destructive gate 只接受显式 `customer-agent-gate-<唯一后缀>` project，以及匹配的 `gate-<同一后缀>` 镜像 tag；缺失、默认、`local`、main-preview 和所有 `customer-agent-baseline*` 名称均 fail closed。
- baseline 默认端口 `4180` 禁止用于 destructive gate；调用者必须显式提供独立前端端口。
- `scripts/confirm-compose-reset-isolation.ps1` 在任何 reset 前执行 `docker compose -p <project> config --format json`，并核对读回 project、卷、网络、端口和所有 `customer-agent/*` 镜像 tag。
- `scripts/check.ps1` 在完整门禁的首次 Docker 操作前预检；`scripts/smoke.ps1 -Reset` 再次独立预检，并为 `down --volumes` 显式传入已验证的 `-p` project。
- CI full-stack job 使用 `github.run_id` 与 `github.run_attempt` 形成独立 project/tag，并显式提供端口。
- 纯 PowerShell 契约测试覆盖缺失项目、baseline 名称、非法 namespace、配置读回不一致、越界卷/网络、越界镜像、端口复用及合法隔离配置。

## 恢复与验证结果

- 重建仅创建 `customer-agent-baseline` 的 7 个容器、4 个网络与 1 个全新 PostgreSQL 卷；两个迁移任务退出码为 0，5 个运行服务保持 healthy，系统状态为 `UP`，合成夹具可用。
- 重建后在唯一 `customer-agent-gate-*` project、匹配镜像 tag 与独立端口下运行完整 `pwsh ./scripts/check.ps1`，退出码为 0；主 Chromium 矩阵 25 项通过，会话矩阵 3 项通过、3 项按条件跳过。
- gate 与浏览器子项目清理后，容器、卷、网络均精确回读为 0；baseline 仍为 7 个容器、1 个卷、4 个网络，运行服务 healthy，系统状态 `UP`；main-preview 卷保持存在。
- 恢复与门禁的机器可读脱敏摘要见 `docs/delivery/issue-129-baseline-recovery.json`。事故前旧 baseline 数据不可恢复，本次只证明新建合成运行时可用。
