# 支付失败终态用量保留：修复与验证

## 修复范围

针对[失败分析](2026-09-14-payment-failure-diagnosis.md)中已离线证实的代码缺陷修复，不声称已找到原真实流的唯一触发原因。

- 回复读取器统一返回 completed / incomplete / failed 终态及其载荷，上层先保留载荷供审计，再决定业务成功与否。
- incomplete / failed 仍然拒绝为有效回复；记录 `PROVIDER_TERMINAL` 诊断和具体终态类型。既有发布拒绝原因仍优先保留。
- 已返回 usage 时结算，未返回 usage 时保持 PENDING；不增加请求，不改 token 上限，不重置旧账本。
- 核心浏览器矩阵在 HANDED_OFF / SUPERSEDED 时立即断言失败，不再继续等满 120 秒；COMPLETED 才通过。

本轮没有新增真实模型调用。先前真实评测的 4 PASS / 1 FAIL / 5 NOT_RUN、费用未知预留和所有原始记录保持原样。

## 回归证据

新增普通支付输入的四个用例：incomplete / failed × 有 usage / 无 usage。

1. 修改实现前：4 failed / 44 deselected，0.83 秒，失败点为响应 ID 丢失。
2. 修改实现后：整个回复适配器文件 48 passed，2.10 秒。确认业务仍失败、没有公开发布、每例仅一次调用、终态和已知 token 保留；有 usage 为 SETTLED，无 usage 为 PENDING。
3. Ruff 格式/静态检查通过。首次手动类型检查没有指定项目 Python，产生依赖无法解析的环境错误；显式使用 `/app/.venv/bin/python` 后为 0 errors / 0 warnings。
4. 浏览器文件 Prettier、ESLint 和前端类型检查通过。

本地日志保存在 `.local/audit-20260914/fix-red.log`、`fix-green.log`、`fix-static.log`、`fix-types.log`、`fix-frontend-static.log`。

## 双轴复核

- Standards：只调整既有终态返回和错误处理，没有新增依赖、额外重试、正文语义阻断或业务权限；保持未知 usage 为未知，历史账本不变。检查范围为本轮三个代码/测试文件。
- Spec：新回归直接覆盖普通支付失败终态的已知用量保留，同时验证缺失用量和禁止发布；原有发布拒绝回归全部通过。等待器仍只接受 COMPLETED，没有将转人工算成功。

以上为本任务的本地双轴复核，不冒充远端集中 AI 审查或正式 PR 交付。

## 集成验证

### 核心浏览器矩阵

运行 `issue230-core-payment-fix-20260914`，10/10 通过，Playwright 汇总耗时约 2.5 分钟。结果文件确认 `outcome=PASS`、`metricsCollected=true`、`cleanupPassed=true`。

受控供应商请求 54 次、逻辑调用 54 次、合成 usage 8370 token，按夹具计算的模拟费用 40500 微元；这些是离线夹具数据，**不是实际供应商费用**，外部付费调用为 0。未知 usage、缺失证据来源、PENDING 及 IN_FLIGHT 预留均为 0。

证据目录：`.local/gate-evidence/issue230-core-payment-fix-20260914/`；日志：`.local/audit-20260914/fix-core-browser.log`。

### 最终完整门禁

命令为仓库根目录 `pwsh ./scripts/check.ps1 -RunId manual-payment-terminal-fix-20260914`。进程显式将四角色设置为固定/确定性模型并使用合成凭据，避免本机 `.env` 的真实模式影响普通门禁。

**完整门禁结果：FAIL，进程退出 1。**

- Agent 全量 611 passed / 3 skipped（28.80 秒），格式、静态及类型检查通过。
- Issue #29 正常和对账路径的 React 全栈测试均通过。
- 随后的广域 integration-smoke 在 `agent/smoke.py:5753` 失败：`assert blocked_authority_writers >= 2`，实际为 1。
- 该测试持有工单业务权威 advisory lock，发起关闭边界客户回复，并在约 10 秒观察窗口内要求至少两个 advisory 等待者。观察条件未满足；后续关闭、重放等断言未执行，最终完整浏览器阶段也未执行。
- 本次没有修改 `agent/smoke.py`，但没有在修复前版本重放该失败，故不将其定性为“已证明无关”或“纯偶发”。没有放宽断言，也没有第二次运行完整门禁。

本次修改通过聚焦回归与核心浏览器矩阵，但**尚未通过完整交付门禁，未提交、合并 PR 或关闭 Issue**。本轮完整门禁日志为 `.local/audit-20260914/fix-full-check.log`。

失败门禁的容器、卷和网络已只读确认不存在；随后按精确 Run ID 清理本轮镜像，不触及其他资源。历史真实账本保留不变。
