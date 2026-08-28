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

- 提交：`a977ae1`。
- 条件：与基线一致，使用共享 Docker 层缓存（warm cache）和全新的唯一 project/tag/端口；运行 `pwsh ./scripts/check.ps1`，退出码 0。
- 运行：`issue182-24a8f20d4a9e`；源码指纹 `f9d92eaed9244cc770c5fa7a4521037856cd74d11069acdde13ab662b4e5a77b`。
- 镜像：8 个唯一构建目标，`buildTargets=8`、`reusedTargets=0`；本轮没有跨运行复用旧镜像，smoke 与浏览器阶段复用本轮已校验镜像。
- 浏览器：2 个 parallel-safe 文件以 `workers=2` 连续三轮，共 6 次成功执行；16 个常规串行文件共 35 个测试全部通过；另 1 个 Session 文件按重启准备、重启验证、到期三个阶段执行，每阶段 1 个目标测试通过、1 个非本阶段测试按设计跳过。
- 分阶段耗时：构建 18.614 秒，smoke 237.029 秒，浏览器 301.754 秒，总计 576.341 秒。
- 对比基线：总耗时减少 9.263 秒（1.58%）；更重要的是相同 runtime 不再跨 smoke/浏览器重复构建，构建次数由阶段隐式重复收敛为可审计的 8 个唯一目标。
- 清理：smoke 与浏览器两个 Compose project 的容器、网络、卷均在各自阶段结束后回读为空；门禁 8 个临时镜像在成功后删除并回读不存在。
