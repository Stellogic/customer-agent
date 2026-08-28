# ADR 0004：以本地完整门禁替代 GitHub CI

## 状态

已接受；替代 [`0001-quality-guardrails.md`](./0001-quality-guardrails.md) 中关于 GitHub CI 的决定。

## 背景

仓库由单一维护者推进。原 GitHub Actions workflow 在 Pull Request 和 `main` push 上重复运行
三个组件检查与 full-stack smoke；本地 `pwsh ./scripts/check.ps1` 还会额外执行真实 Chromium、
Session、SSE 和 Compose 隔离验收，因此远端 workflow 不是本地完整门禁的等价替代。

2026-08-28，Actions 因仓库账户 Spending limit 未实际启动任务，外部服务状态开始阻塞已经通过
本地完整门禁的交付。用户在 [Issue #184](https://github.com/Stellogic/customer-agent/issues/184)
中确认关闭 GitHub CI，并要求后续实现只以更完整的本地门禁作为自动化测试依据。

## 决策

- 关闭仓库 GitHub Actions 权限并删除自动测试 workflow。
- GitHub CI 不再作为提交、合并或 Issue 完成条件；实现者不触发、不等待也不要求 CI。
- 最新 `origin/main` 独立工作树中的完整 `pwsh ./scripts/check.ps1` 是唯一自动化测试门槛。
- 聚焦组件检查只服务迭代，不能替代最终完整门禁。
- 正式完成仍要求既定 Standards/Spec 审查、PR 合入、Issue 关闭与 `origin/main` 回读。
- 外部 Codex PR 审查独立于 GitHub Actions，本决定不改变其使用策略。

## 被否决的方案

- 只运行 GitHub CI：原 workflow 缺少本地完整入口中的 Chromium 验收，覆盖较少。
- 同时强制本地门禁与自动 CI：增加重复等待，并把第三方账单或额度状态变成交付阻塞。
- 删除本地完整验收、只保留聚焦检查：会丢失真实 PostgreSQL、LangGraph、浏览器和隔离证据。

## 影响

自动 CI 不再提供托管干净环境的第二份证据。对应风险由最新 `origin/main` 的独立工作树、完整
Docker/Compose/Chromium 门禁、双轴审查和合入后回读承担。门禁失败时仍不得提交或合并；
GitHub 上缺少 check run 则不构成失败或阻塞。
