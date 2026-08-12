# Issue #66：Smoke 应用日志正文边界验证

## 边界

`docker compose logs --no-color` 的每行可能包含 Compose 添加的 `<service> |` 前缀。该前缀属于基础设施元数据，不是产品应用日志；扫描器先识别并剥离这个前缀，再对应用正文同时应用 `contentPatterns` 与 `internalAddressPatterns`。没有 Compose 前缀的行按完整应用正文处理，不能借此绕过扫描。

因此，基础设施服务标签 `agent-server`、`local-agent` 可以出现在前缀中；相同字符串一旦出现在应用正文、前端产物或浏览器投影中，仍会被拒绝。Agent Server 继续使用 `logging.driver: none`，本变更没有把私有编排运行时日志纳入产品日志面。

## TDD 与脚本回归

公开脚本入口 `pwsh ./scripts/test-runtime-log-policy.ps1` 覆盖：

- `agent-server` Compose 服务名前缀不误报；
- 正文中的 `agent-server`、`agent:2024`、`local-spring`、`local-agent`、`local-executor`、`local-postgres` 与 `postgresql://` 被拒绝；
- 既有 `contentPatterns` 示例 `rawPrompt` 仍被拒绝；
- 合法 Compose 日志、合法应用正文和无 Compose 前缀的合法日志通过。

首个 red 由缺少扫描入口产生；加入 Compose 元数据剥离后转绿。第二个 red 证明仅扫描 `contentPatterns` 会漏过正文 `agent-server`；合并 `internalAddressPatterns` 后转绿。真实 smoke 的第三个 red 进一步检出 `spring-migrate` 的 Flyway INFO 正文包含 PostgreSQL URI；将该迁移容器的 `org.flywaydb` 日志收敛到 `WARN` 后，单服务 URI 扫描与完整门禁均转绿。脚本测试现已接入 `scripts/check.ps1`，避免只在真实 smoke 末尾才发现策略回归。

## 规范化验证

验证日期：2026-08-13（Asia/Shanghai）。

- 聚焦脚本回归：`pwsh ./scripts/test-runtime-log-policy.ps1`，10 项策略行为通过。
- 真实隔离 smoke：固定 Compose project `customer-agent-issue66-a704`、镜像 tag `issue66-a704`，运行 `pwsh ./scripts/smoke.ps1 -Reset`，退出码 0；包含空卷 V1→V19、真实 PostgreSQL/LangGraph/Spring、两条 Issue #29 React 端到端链、广域 integration smoke、React live 与最终运行日志正文扫描。
- 规范化门禁：在同一隔离 project 中字面运行 `pwsh ./scripts/check.ps1`，退出码 0；脚本策略、backend、agent、frontend 与全栈 reset gate 全部通过。
- 宿主 `127.0.0.1:4180` 已由协调中的 baseline 占用，因此验证使用未提交的 Compose override `127.0.0.1:42866 -> frontend:8080`，没有停止 baseline。完整验证后已恢复 `smoke.ps1` 原状态请求并删除 override。
- 只清理自有 project，`down --volumes --remove-orphans` 后回读 `ps_count=0 volume_count=0 network_count=0`。
- 固定 `origin/main@03aec35f53067e34abdf30203ecaa70335cfa824` 的独立 Standards/Spec 双审均为 clean；文档状态更新后再复审最终提交。
- GitHub 四项检查：ready PR 后等待并记录。

验证范围只证明本仓库 Compose 日志输入、前端产物与既有浏览器验收所覆盖的敏感内容边界；不声称采集或审计宿主机、Docker daemon、第三方平台或被明确禁用采集的 Agent Server 原始日志。
