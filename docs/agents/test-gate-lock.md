# 测试门禁锁

运行 `pwsh ./scripts/check.ps1`、smoke、镜像构建、Docker/Compose 或浏览器验收时使用本文件。代码阅读、编辑、提交、Draft PR 与 Standards/Spec 双轴审查不占锁。

## 权威与展示

- Windows 会话级命名互斥量是唯一权威锁；状态 JSON 只展示占用者。
- 查询：`pwsh ./scripts/test-gate-lock.ps1 -Status`
- 机器标识：`TEST_GATE_FREE`、`TEST_GATE_BUSY`、`TEST_GATE_LOCK_REQUIRED`、`TEST_GATE_RECOVERY_REQUIRED`
- 退出码：75 占用，76 缺令牌，77 需要恢复。只读查询始终以 0 结束。

## 状态机

1. **FREE** — 互斥量不存在，且没有与旧记录精确匹配的残留容器/卷/网络/镜像。可以获取锁并运行规范化测试。
2. **BUSY** — 互斥量存在。立即停止并报告占用摘要，禁止排队、睡眠或循环重试。
3. **RECOVERY_REQUIRED** — 互斥量空闲，但旧运行留下精确匹配资源。升级给协调线程处理残留；脚本不删除资源，也不用删 JSON 的方式声称解锁。

崩溃后由操作系统释放互斥量。陈旧 JSON 单独不能造成死锁。没有强制释放仍被持有的互斥量的命令。

## 谁占锁

规范化入口 `scripts/check.ps1` 在任何 Docker、构建、测试服务或浏览器动作前获取锁，并把所有权令牌写入 `CUSTOMER_AGENT_TEST_GATE_TOKEN`。重资源子脚本只校验令牌，不再次抢锁。缺少有效令牌时返回 `TEST_GATE_LOCK_REQUIRED` 并在启动重资源前退出。

完整门禁使用 `-Issue <编号>`。缺少 Issue 的人工运行记为 `manual`，不能作为正式交付证据。完整门禁开始前同步 `origin/main`，并记录 base SHA 与 head SHA。

## 并行与交付

允许并行：实现、双轴审查、频繁提交、保存 Draft PR。未通过最终本地完整门禁前，不得声明可交付、合并 PR 或关闭 Issue。Draft PR 在验证完成前可标 `CODE_READY_NO_TESTS`。

锁只约束可交付状态，不约束普通提交。GitHub Actions 保持关闭；本地完整 `pwsh ./scripts/check.ps1` 是唯一自动化测试门槛。测试是合入前的必做门禁，不是可选项。

正式交付窗口：同步最新 `origin/main` → 运行完整门禁 → 立即合并或取消。通过后到该 PR 合入或本次交付取消前，不启动另一张票的完整门禁；聚焦测试仍按锁的空闲情况运行。门禁后任何受版本控制内容变化都使旧证据失效。
