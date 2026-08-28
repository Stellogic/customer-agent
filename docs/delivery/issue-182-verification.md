# Issue #182 门禁镜像复用与浏览器安全并行验证

## 范围与不变量

- 完整门禁仍以 `pwsh ./scripts/check.ps1` 为唯一入口，不删除组件、smoke 或真实 Chromium 覆盖。
- 一次门禁生成唯一 `RunId`、`gate-*` 镜像标签与源码指纹；backend、agent、frontend 的 test/runtime 目标及两个浏览器目标各构建一次。
- smoke 与浏览器验收只复用经 label 校验的不可变镜像，不复用容器、网络、卷、端口或数据库状态；两个阶段结束后分别回读自有资源为空。
- 源码指纹覆盖三个 Docker 构建上下文；源码、Dockerfile、锁文件或上下文文件变化后，`SkipBuild` 会因指纹失配而失败。

## 浏览器分组

- `scripts/browser-acceptance-plan.psd1` 是显式清单；所有 `frontend/e2e/*.spec.ts` 必须属于 `ParallelSafe`、`Serial` 或带理由的 `Excluded`，遗漏、重复和不存在的文件均 fail closed。
- `ParallelSafe` 当前仅含两个匿名静态 UI 文件，不创建 Session、不读写共享数据库，使用 `workers=2` 连续运行三次。
- Session、SSE、数据库写入、审批/竞态、恢复和其他状态型文件全部保留在 `Serial`，使用 `workers=1`；真实模型文件仍由其独立授权验收运行。

## 优化前基线

- 提交：`454ca0c60a5c6808f052aad5cc7208fa10a7578e`（当时最新 `origin/main`）。
- 条件：共享 Docker 层缓存（warm cache）、全新的唯一 project/tag/端口；完整门禁退出码 0。
- 总耗时：585.604 秒。
- 构建路径：3 个组件 test 镜像；smoke 再构建 test/runtime；Issue #80 再构建 backend、agent、frontend、browser-test、browser-server。相同 runtime 目标在不同标签下重复构建。

## 优化后证据

最终完整门禁完成后，在本节记录同一 warm-cache 条件下的分阶段耗时、8 个唯一构建目标、浏览器文件/场景数和资源清理回读。
