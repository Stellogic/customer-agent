# #190 显式范围权限错误修复

2026-09-01；Issue #190 / PR #203；base `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。

`issue190-final-20260901a` 在干净 HEAD `2a37d882d2f311f03e7a19b5a0e99182df25000f` 上完整 `check.ps1 -Issue 190` PASS：构建 15.654 秒、smoke 439.448 秒、浏览器 387.294 秒，主体总计 870.760 秒（不含前面的门禁脚本自检）。浏览器并行安全组 5 项×3、串行 48 项、会话分阶段 3 次各 1 通过/1 不适用跳过；64/64 检索 Recall@5 0.9444444444、MRR@5 0.8680555556、三项禁止命中率各 0。资源与镜像清理完成，释放自身锁后只读一次 FREE，已通知协调。原始报告与控制台见 [归档](evidence/issue190-final-20260901a/index.json)。

门禁收尾时读取 Ready 自动触发的审查，发现真实 P2：`support-demo` 显式请求 APPROVER，服务将权限集合取空，返回 200 空结果。虽没有片段泄露，却把权限拒绝伪装成正常空结果，与正式 [rag-layered-v2](../eval/rag-layered-v2.md) 冲突。先前接口文档只是错误现状，不能覆盖规格；此前双轴审查漏检，现明确修正。自动化 PASS 保留，但**不能作为修复后代码的交付证据**，必须重新完整门禁。外部安全审查额度不足不作为阻塞，也没有重复触发审查。

最小修复先验证 scope 格式，再在任何编码/检索前对合法但未授权的 scope 抛既有 403；无效范围仍 400，合法授权范围无匹配仍 200 空。页面显示权限错误。v2 评测入口只请求 INTERNAL/CUSTOMER_PUBLIC，显式将内部接口不授予的 CUSTOMER_PUBLIC 识别为预期 403，且错误 200 也失败；其他非预期 403 继续失败。v1 默认、旧指标、冻结题/标签/门槛及预算全部未改，不能用题型或任意 HTTP 错误取得通过。

新增独立 HTTP 解析回归 4 项，以及真实客服页面选择审批范围的浏览器用例。`issue190-scope-preflight-20260901a` 在提交前脏树完成聚焦 7 项、相关离线 50 项、Ruff/类型/Java/前端格式 PASS，63.6995 秒；不是干净最终 SHA 或真实浏览器证据。[原始预检与哈希](evidence/issue190-scope-preflight-20260901a/index.json)。此轮还回读此前 runtime-a/b 自有镜像标签均为空，不清理其他任务资源。结束释放自身锁，只读一次 FREE 并通知协调。

修复后增量 Standards PASS / Spec PASS（各 0 阻塞），未读冻结逐题结果或独立留出；真实组件/浏览器及新的最终门禁待运行。没有付费调用、费用 0，旧账本未重置。此记录是一次自动化门禁未覆盖、随后审查发现的工程缺陷，可作为学习项目的试错证据；不宣称生产事故或用户独立手写贡献。

## 后续真实复验与响应正文问题

上述“待运行”为提交时状态，后续三次真实运行均保留，未覆盖旧结果：

| RunId | HEAD | 结果 | 阶段秒 |
| --- | --- | --- | ---: |
| issue190-scope-runtime-20260901a | 0527552d250f6c2a819cff6365ad8870268f7761 | 三端组件 PASS；浏览器 5 通过、新增权限用例 30 秒超时 | 504.9397 |
| issue190-scope-trace-20260901a | 同上 | 不改源码/断言/超时，只跑该用例，重复超时；成功保存 trace | 116.7566 |
| issue190-scope-runtime-20260901b | eae2cc9772c1581b7f730c157343ef8b7828f905 | 组件 PASS；原 6 项浏览器全部 PASS（10.7 秒） | 191.7406 |

trace 中 HTTP 403 断言已完成，页面快照已经显示正确的权限 alert；卡住的是随后 Playwright `Response.body`，只有 before、没有 after。前端新增的 403 分支在读取错误正文之前抛出异常。`eae2cc9` 仅将它移到 `await response.json()` 之后：读取正常的 JSON 权限响应，再显示同一错误。全部原断言（403、错误码、权限提示及不能显示空结果）和 30 秒超时保持不变，原六例恢复通过。该修复增量 Standards / Spec 各 PASS；这是响应消费接缝问题，不是检索质量失败，没有据此改题、改权限或调参。

组件细节：runtime-a 后端 Gradle check 实际执行通过，Agent 312 项通过、前端 164 通过/3 个既有跳过；trace-a 使用相同源码构建缓存。runtime-b 后端/Agent 使用同源缓存，前端变更后重新运行规范检查。三轮均未执行冻结质量评测、没有付费调用，清理自有资源/镜像完成；各次释放后只读一次宿主 FREE 并通知协调，窗口保留用于后续完整门禁。

- [runtime-a 失败与组件输出](evidence/issue190-scope-runtime-20260901a/index.json)
- [trace-a 失败、页面快照与脱敏诊断](evidence/issue190-scope-trace-20260901a/index.json)
- [runtime-b 通过、桌面/窄屏截图与原始日志](evidence/issue190-scope-runtime-20260901b/index.json)

runtime-a 因旧临时脚本复制了空 `/artifacts`，未保存失败 trace；trace-a 改为复制真实 `/app/test-results`，不修改产品。原 zip 可能含临时会话头，仅留在本地 `.local/gate-evidence/issue190-scope-trace-20260901a/browser`，其 SHA256 与不含头/凭据的诊断摘要归档；不把敏感 raw zip 提交 Git。runtime-b 成功保存两张真实截图。后续仅文档归档不改变已复验源码；仍须新的最终完整门禁后合入关票，不复用旧 final-a 的交付证据。

本次三轮归档再次经 Standards PASS / Spec PASS（各 0 阻塞）；Standards 核对 18 个归档文件哈希及未提交 raw trace，Spec 核对失败/成功和质量未运行的边界。没有新增运行或变更源码。
