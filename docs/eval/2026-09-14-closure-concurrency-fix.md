# 关闭边界并发门禁：诊断与修复

## 问题与证据

上一轮完整门禁在 `agent/smoke.py` 的关闭边界场景失败：期望至少两个 advisory lock 等待者，实际为 1。没有将该结果当作偶发成功，也没有放宽断言。

本轮最小独立场景能看到两个 advisory 等待者；释放锁后 HTTP 201，旧工单 CLOSED，且新工单的 follow_up_of 指向旧工单。这说明基本关闭/续接路径能够成立，但不能替代广域场景复现。

广域诊断首次缺少原 smoke 开启的 `AGENT_INVESTIGATION_SHADOW_MODE=offline`，在 shadow_comparison 检查退出，未到目标场景；补齐配置后第二轮准确复现原失败，锁观测如下：

| 进程 | 等待 | 当前操作 | 阻塞者 |
| --- | --- | --- | --- |
| 944 | 持锁，不是等待者 | 测试持有目标工单 BUSINESS_AUTHORITY | — |
| 181 | advisory | pg_advisory_xact_lock | 944 |
| 183 | transactionid | 读取工单 SLA 快照的 SELECT … FOR UPDATE | 181 |

释放测试锁后，客户续接请求返回 HTTP 201。失败发生在“制造出两个 advisory 等待者”的前置观测断言，不能把它说成已证明工单重复创建。

代码核对显示第二条 SQL 来自 `SlaService.evaluateTicket`。客户续接路径在等待业务权威锁时已持有工单行级锁，SLA 定时任务因此等待该请求；在项目默认调度配置下，关闭任务无法按测试假设继续进入 advisory 等待。旧测试只统计整个数据库的 advisory 等待数，看不到这条行锁等待链，也没有确保调度任务先到位。

Spring 的默认线程池调度器只有一个线程，见[官方调度文档](https://docs.spring.io/spring-framework/reference/integration/scheduling.html)。本项目没有额外配置调度线程池。该机制与本次锁观测和局部/广域差异一致；没有为让测试通过而调整运行时线程池。

## 最小修复

仅修改广域 smoke 的并发准备步骤：

1. 测试仍持有目标工单业务权威锁，并将工单设置为精确关闭边界。
2. 先等待至少一名调度侧参与者被该测试锁阻塞，然后才启动客户续接请求，避免客户先持有工单行锁而挡住 SLA 调度。
3. 后续仍要求至少两名 advisory 等待者，再释放锁。
4. 观测限定为被测试持锁进程阻塞的 advisory 等待者，不计其他工单的锁竞争。使用 PostgreSQL 原生 `pg_blocking_pids`；它包含真实持锁者及队列前方阻塞者，见[PostgreSQL 18 文档](https://www.postgresql.org/docs/18/functions-info.html)。

没有改业务关闭、权限、事务或幂等逻辑，没有增加重试或延长原有观测窗口。原有关闭一次、一次创建加七次重放、唯一关联工单、请求落库以及 SSE 队列移除断言全部保留。

## 验证记录

| 阶段 | 结果 | 本地证据 |
| --- | --- | --- |
| 最小独立诊断 | 两个 advisory 等待者，释放后关闭/续接正确 | `.local/audit-20260914/closure-probe-result.json` |
| 广域诊断第一次 | 配置缺漏，未到目标场景，不计通过 | `closure-integration.log` |
| 广域诊断第二次 | 复现单 advisory + 单 transactionid 等待链，断言失败 | `closure-integration2.log` 的 CLOSURE_DIAG |
| 修复后广域回归 | 全部断言通过，退出 0，返回 status=UP | `closure-integration-green.log` |
| 静态检查 | Ruff 通过，Pyright 0 errors / 0 warnings | `closure-static.log` |

上表日志均在 `.local/audit-20260914/`。临时诊断副本放在该目录，正式源码没有遗留诊断打印。所有运行使用固定模型或离线 shadow，外部模型调用为 0；各轮资源使用独立 Compose 项目并在结束后清理。此前真实模型评测和未结账本不变。

诊断观测和修复后集成摘要已保存为[结构化数据](2026-09-14-closure-concurrency-data.json)。

### 双轴复核

- Standards：只改 smoke 准备顺序和锁观测范围，复用 PostgreSQL 原生等待关系；无运行时线程池变更、额外依赖、业务重试或权限扩大。
- Spec：仍必须观察到至少两个目标业务锁等待者；保留所有关闭边界、幂等及队列移除断言，并已由原广域测试验证通过。不是将原来的 2 改成 1。

### 最终完整门禁

冻结本轮四个代码/测试文件后运行 `pwsh ./scripts/check.ps1 -RunId manual-payment-closure-final-20260914`；结果完成后补充。上一轮失败记录保留，不覆盖成通过。

## 断电前保存检查点

用户要求电脑低电量时优先保存提交。本次完整门禁 `manual-payment-closure-final-20260914` 已通过 Agent 测试（611 passed、3 skipped）与广域集成测试；保存时后续浏览器验收尚未全部结束，因此完整门禁仍未确认通过，不作为合并或正式交付依据。修复代码、已有评测数据与诊断文档一并提交，后续从此检查点继续。
