# Issue #174 真实验收环境阻塞记录

记录日期：2026-09-04。状态：`BLOCKED_ENVIRONMENT`，不是模型验收失败或通过。

- 运行标识：`issue174-live-20260903a`。
- 待验收提交：`e7e8939`；基线：`c28971eed633ba1128f299e6f6f964efd024be15`。
- 用户已明确授权真实调用及 PR 交付；冻结场景、模型和预算未变。
- 首次启动在 Docker Linux 引擎不可连接时停止，未进入镜像构建或模型场景。
- 启动本机已有 Docker Desktop 后，引擎版本查询返回 `28.3.2`，随后继续同一运行标识。
- 后续在 Agent runtime 镜像的 `chown -R agent:agent /app` 步骤出现连续 `Input/output error`，构建最终返回 `rpc error: code = Unavailable ... EOF`；清理查询返回 Docker API 500。
- Backend test、Agent test、Frontend test 和 Backend runtime 的本次镜像标签已生成。Agent runtime 构建未完成；不能声称本次镜像已全部清理。
- 五个真实浏览器场景均为 `NOT_RUN`，供应商调用尚未开始，本次新增模型费用为 0。
- 失败后的共享账本回读：累计已结算 `3810222 micro-CNY`，`PENDING=0`，本次预留及 phase 已由调用前失败分支撤回。
- 锁查询返回 `TEST_GATE_FREE`，但 Docker 连接故障导致资源清理未验证；此状态不能作为资源清理完成的证据。
- 最终完整门禁 `NOT_RUN`；PR 保持 Draft，Issue 保持 OPEN，main 未修改。

后续须先恢复 Docker 引擎并核对本次专属资源，再恢复冻结验收。不得通过删除共享缓存、卷或重置 Docker 来自动绕过环境故障，也不得把已有确定性检查结果替代真实验收。

## 环境恢复后的首次真实调用

用户恢复 Docker 并明确要求继续后，锁为 FREE，本次运行的专属容器、镜像标签、卷和网络均未查到，预算起点仍为 3810222 micro-CNY、PENDING=0。基线未变化。

在提交 `4ddca8a00c8909a2989c303cf090079162f6cfc6` 上复用原冻结运行标识，镜像构建、数据库迁移及服务健康检查均通过，包括此前发生 I/O 错误的 Agent runtime 构建步骤。这只证明本次环境可以运行，不证明物理磁盘或已有数据库已经完整验证。

L174-01 在 `frontend/e2e/issue173.full-stack.spec.ts:22` 失败：客户追加“是的，确实重复扣款”后，页面未在 5000 ms 内显示“请确认 2 个问题”。首次澄清页面断言已通过。L174-02 至 L174-05 均为 NOT_RUN，没有付费重跑，没有修改场景、模型或预算。

费用采集读到两条受理操作计数，未观察到调查 generation；报告中的调用及尝试数由持久化受理记录计数推算，并非完整供应商审计。受理 token 未记录，不能将 knownTotal=0 解读为实际 token 为零。40000 micro-CNY 是已记录操作的保守估算，不是整轮最终账单；共享账本继续保留本次 1000000 micro-CNY 的 PENDING 预留。

Playwright 控制台报告生成了 trace/error-context，但输出位于临时容器默认目录，没有进入 `/artifacts` 挂载卷，容器退出后未能导出。因此仅能确认页面断言失败，不能区分真实响应耗时、模型分类或产品契约问题。后续静态修正关闭 trace，避免收集未脱敏的会话凭据和完整响应。没有将原始页面上下文改为持久保存，因为其中也可能包含完整模型回复；安全取证缺口仍未补齐，必须在后续付费诊断前解决。此修正没有进行真实调用验证，也不能补回本次遗失的产物。

清理后的只读查询确认本次专属容器、卷、网络和镜像标签为空，锁为 TEST_GATE_FREE。最终完整门禁仍为 NOT_RUN，PR 保持 Draft，Issue #174 保持 OPEN。本次机器可读结果见 `issue-174-live-report.json`。预算核对和有针对性的失败诊断完成前，不得自动重跑或把预留金额重新用于其他调用。
