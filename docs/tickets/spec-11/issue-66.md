# [B-4] 为 smoke 日志扫描定义 Compose 元数据与应用正文边界

> 父规格：[#11 规格 客服工单调查与补偿审批 Agent MVP 首个纵向切片](../../specs/issue-11.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/66](https://github.com/Stellogic/customer-agent/issues/66)
> Issue 状态：CLOSED
> 创建时间：2026-08-12T18:52:55Z
> 最后更新时间：2026-08-12T19:34:28Z
> 关闭时间：2026-08-12T19:34:28Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

Part of #11

## 问题

`scripts/smoke.ps1` 当前运行日志扫描没有覆盖 `internalAddressPatterns`。若直接对完整 `docker compose logs` 文本扫描，服务名前缀中的 `agent-server` 会稳定误报；若继续不扫描，又可能让内部 Agent 地址、镜像标签或 PostgreSQL 连接串进入产品日志或浏览器投影而不被发现。

## 目标

为 Compose 日志定义明确边界：先剥离或结构化处理 Compose 元数据，只扫描受保护的应用日志正文。基础设施层允许的服务名、容器名等标签不能因为包含内部标识而误报，但同样文本一旦进入应用正文就必须被拒绝。

## 验收标准

- [ ] `scripts/smoke.ps1` 的运行日志扫描同时覆盖既有 `contentPatterns` 与 `internalAddressPatterns`。
- [ ] Compose 服务名前缀中的 `agent-server` 不误报。
- [ ] 应用日志正文中的 `agent-server`、`agent:2024`、`local-*`、`postgresql://` 均可检出。
- [ ] 既有 `contentPatterns` 仍可检出。
- [ ] 合法 Compose 日志和合法应用正文通过。
- [ ] 脚本测试通过公开脚本入口覆盖以上行为，并保留 red→green 证据。
- [ ] 真实 smoke 使用唯一 Compose project/资源验证，结束后只清理并确认自有资源为空。
- [ ] 中文验证文档同步记录边界、命令、结果和未验证范围。
- [ ] 从最新 `origin/main` 开始，完成完整 `pwsh ./scripts/check.ps1`、独立 Standards/Spec 双审与 CI 四项检查。

## 非目标

- 不把 Docker Compose 的服务名、容器名、镜像名等基础设施元数据作为产品日志内容。
- 不改变浏览器投影或 Spring/Agent 的业务权限边界。
- 不创建后继任务。
