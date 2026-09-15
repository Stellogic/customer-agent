# Issue #242：项目重大问题检查与修复记录

## 结论与范围

本次从远端 `main` 基线 `adacdd74f0492ad10f49a064170c2039c85b0b7c` 检查现有业务链路，确认并修复两项普通业务输入或操作即可触发的问题：**合法的非整小时物流延迟被 Agent 误判为事实冲突；审批人刷新页面后失去尚未到期的审批入口。** 两项均先由聚焦回归复现失败，再完成源码修复并取得对应绿测。

此前支付终态计量与关闭并发修复已由 [PR #241](https://github.com/Stellogic/customer-agent/pull/241) 合入，上述基线包含该交付。本次单独跟踪于 [Issue #242](https://github.com/Stellogic/customer-agent/issues/242)。按用户要求，#149 尚未完成的范围不作为本次缺陷；本次不关闭 #149、#174 或 #227。

审查按学习和演示项目的尺度进行，覆盖 React 客户/客服/审批关键流程、Agent 事实与行动合同、后端租约、订单补偿额度、执行结果未知后的对账，以及关闭与处理代次仲裁。在后端上述抽查范围内，没有额外发现已得到代码或复现证据支持的重大问题。该结论不等于全仓无缺陷，也不包含生产负载或外部供应商稳定性保证。

## 1. 合法秒级物流事实被误判为冲突

### 复现场景与原因

订单延迟 `86,399` 秒时，展示小时数为 `23`；延迟 `259,201` 秒时，展示小时数为 `72`。数据库允许这两组事实，但旧 Agent 要求秒数恰好等于小时数乘以 `3,600`，导致普通的非整小时延迟进入 `FACT_CONFLICT` 转人工，兼容行动路径也拒绝正常终止动作。

权威合同来自 [V21 数据库约束](../../backend/src/main/resources/db/migration/V21__proposal_delay_fact_and_amount_guards.sql)：订单、提案和审批证据均要求 `delay_hours = delay_seconds / 3600`，其中整数除法产生展示小时数。Spring 的 [调查服务](../../backend/src/main/java/com/stellogic/customeragent/investigation/JdbcAgentInvestigationService.java) 与 [审批服务](../../backend/src/main/java/com/stellogic/customeragent/approval/JdbcApprovalService.java) 使用精确秒数计算补偿档位。

### 最小修复

- [graph.py](../../agent/src/baseline_agent/graph.py) 与 [DeepSeek 行动适配器](../../agent/src/baseline_agent/deepseek_investigation_action_model.py) 统一检查 `delayHours == delaySeconds // 3600`。
- 精确秒数仍传入结论、提案及审批证据，金额规则保持原样：`23:59:59` 不到补偿门槛；`72:00:01` 已进入超过 72 小时的部分退款档。
- 确实不一致的字段仍失败，例如 `259,201` 秒与 `71` 小时仍应按事实冲突处理。

聚焦覆盖位于 [图测试](../../agent/tests/test_graph.py) 和 [行动适配器测试](../../agent/tests/test_deepseek_investigation_action_model.py)。真实浏览器回归复用 [Issue #173 全栈场景](../../frontend/e2e/issue173.full-stack.spec.ts)，把既有低风险与补偿流程分别改为上述两个秒级边界，并核对数据库中实际生成的事实、提案及审批快照。夹具只准备独有合成订单，工单、调查和回复仍由页面经 Spring/LangGraph 产生。

### 与历史评测的关系

[9 月 15 日首轮报告](../eval/2026-09-15-e2e/首轮设计问题与原始结果.md) 曾把两个秒级样本失败解释为评测输入不符合 Graph 整小时合同，随后使用 23/73 整小时执行纠正轮。本次继续对照数据库与 Spring 后确认：**Graph 的该限制本身与权威数据合同不一致，属于产品缺陷。** 这修正了此前对这两例失败原因的解释；首轮和纠正轮输入、结果、费用与原始记录均保留，不把历史失败重算为通过，也不把整小时样本通过当作秒级问题已经修复。

## 2. 刷新审批页后无法继续处理本人租约

### 复现场景与原因

审批人领取提案后刷新页面，或切换内部页面再返回。旧 [ApprovalWorkbench](../../frontend/src/ApprovalWorkbench.tsx) 仅在组件内存中保存租约，重新挂载后只加载待领取队列。后端队列排除所有尚未到期的有效租约，包含该审批人自己的租约；新的领取请求也会因为已有租约返回冲突。因此提案从本人页面消失，在原 900 秒租约结束前无法继续审批或释放。

### 最小修复与依据

[ApprovalWorkspace](../../frontend/src/workspaces/ApprovalWorkspace.tsx) 从现有 Session 取得主体 ID，传入审批工作台。[approvalClaimStorage.ts](../../frontend/src/approvalClaimStorage.ts) 在该主体作用域保存三项数据：提案 ID、原领取请求 ID、原请求租期。`sessionStorage` 能保留同一标签页刷新前的数据，适用于这个恢复范围；没有新增依赖。[MDN sessionStorage 文档](https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage)

刷新后重放原幂等领取请求，取得原租约，再读取权威审批视图；只有视图校验成功才显示证据与操作。后端原有领取回执不会因此创建新租约或延长期限，审批视图继续检查当前提案版本、租约状态、期限与禁止自审条件。

- 浏览器不持久化审批证据、租约 token 或授权结论。
- 网络结果未知或服务端 5xx 时保留恢复标识；明确请求失败、租约失效、审批决定或释放成功时清除。
- [既有 Session 失效处理](../../frontend/src/humanSessionLifecycle.ts) 同时清除审批恢复记录；记录按主体隔离。
- 组件卸载使当前请求序号及租约引用失效；迟到响应在渲染或清除记录前核对当前请求，避免旧页面影响新页面恢复。

回归位于 [审批组件测试](../../frontend/src/ApprovalWorkbench.test.tsx)、[Session 生命周期测试](../../frontend/src/humanSessionLifecycle.test.ts) 和 [审批浏览器测试](../../frontend/e2e/issue100.approval-workbench.spec.ts)。主场景为“领取 → 刷新/重挂载 → 恢复有效租约 → 释放后重新出现在队列”。旧 URL 本身仍不会自动领取新租约。

## 3. 已完成的聚焦验证

以下为文档冻结前已读取的原始日志结果。离线运行均为 `paidCalls=0`，不使用外部模型；运行元数据中的 `sourceHead` 为上述基线，实际挂载当时工作区的测试或修复代码，不能把它表述为基线提交原样通过。

| 阶段 | 结果 | 测试进程耗时 | 原始证据 |
| --- | --- | ---: | --- |
| Agent 修复前聚焦复现 | 4 FAIL / 3 PASS / 76 deselected | 1.74 秒 | `.local/project-audit-20260915/agent-red.log`、`agent-red.json` |
| Agent 修复后两文件相关回归 | 83 PASS | 1.80 秒 | `.local/project-audit-20260915/agent-green.log`、`agent-green.json` |
| 前端修复前审批组件回归 | 1 FAIL / 13 PASS，合计 14 例 | 9.06 秒 | `.local/project-audit-20260915/frontend-red.log`、`frontend-red.json` |
| 前端修复后审批组件回归 | 14 PASS | 6.42 秒 | `.local/project-audit-20260915/frontend-green.log`、`frontend-green.json` |
| 前端扩展回归（审批、会话、工作台、演示组件） | 25 PASS / 1 SKIP（需要运行中服务） | 15.99 秒 | `.local/project-audit-20260915/frontend-regression.log` |
| 10元账本创建/停止兼容复现 | 1 FAIL / 9 deselected | 0.32 秒 | `.local/project-audit-20260915/budget-red.log` |
| 用户授权10元上限后全部账本回归 | 10 PASS | 0.36 秒 | `.local/project-audit-20260915/budget-green.log` |
| 真实 Chromium 聚焦业务回归 | 7 PASS / 0 FAIL | 55.1 秒（浏览器阶段） | `.local/gate-evidence/issue242-browser-focused-20260915/result.json` |

Agent 的四次失败均对应两组合法秒级事实在图和行动适配器中的错误拒绝；前端失败为重挂载后无法找到订单标题、队列为空。Agent 红测中的 `deselected` 表示该次按名称筛选而未执行的测试，不能计为通过；后续 83 例回归单独记录。前端耗时含测试环境加载与断言等待，Agent 耗时为 pytest 输出，均不代表模型延迟、用户响应时间或吞吐量。

### 静态检查中的实际失败

1. 首次 `static` 未为 Pyright 指定镜像已有的虚拟环境 Python，产生 68 项缺少导入等诊断。这是检查入口配置问题，不据此认定产品依赖丢失；修正入口为 `--pythonpath /app/.venv/bin/python`，该步未修改产品代码。证据为 `.local/project-audit-20260915/static.log`、`static.json`。
2. `static-v2` 中 Agent 格式与 Ruff 检查通过，Pyright 为 `0 errors, 0 warnings`；前端 Prettier 对 12 个文件报告格式问题，整体退出码仍为 1。文档冻结时该结果保持失败，后续修正和重检应使用独立阶段记录。证据为同目录 `static-v2.log`、`static-v2.json`。

后续仅格式化新增审批存储模块；11个既有浏览器文件的格式报告不引入无关改动。按当前仓库配置检查全部前端源码与本次三个浏览器文件后，发现测试助手的默认参数推断错误 TS7022；补充参数类型后，格式、ESLint 和 TypeScript 均通过，见 `.local/project-audit-20260915/frontend-static.log`。Agent 全部格式、Ruff、Pyright 也已通过。

真实浏览器覆盖审批领取刷新释放，以及 #173 的自然语言建单、86399秒低风险回复、259201秒提案、追加消息与旧代次隔离、跨角色审批等7例，全部通过。该轮独立容器、网络、卷及门禁镜像已清理，`cleanupPassed=true`。浏览器运行时源码为当前工作区修复版本，元数据仍记录提交前基线，不能将该基线误当作包含修复的受测提交。

这些检查失败不计入 Agent 业务正确率。最终完整门禁以独立后续结果为准，不由已有绿测代替。

## 4. Agent 能力评测与未测边界

用户追加要求重点评价 Agent 能力，并将新的真实 DeepSeek Pro 轮次费用上限从1.5元提高至 **10 元**，最多 **80 次供应商请求**、**160,000 token** 不变。账本创建器的旧3元硬上限相应改为10元，原账本、预留、停止及未知用量逻辑不变。场景、提示/schema、受测 SHA、45 分钟期限、停止条件及结果独立记录在 `docs/eval/2026-09-15-agent-capabilities/`；该授权不使历史 PENDING 费用消失。

本次能力评测区分自然语言受理、澄清与否定、跨订单/工单上下文、多轮追加、自主行动与知识使用、事实依据和合理转人工。程序规定的必读工具不能算作模型自主选择，结构化合同通过率不能等同正文回答正确率。业务断言、正文语义、延迟、实际调用、token、程序估算与未知费用分别统计，失败和 NOT_RUN 保留完整计划分母。

本文已有的离线红绿结果证明两项修复的行为，不证明真实模型语义能力、外部服务稳定性、生产准确率或并发负载指标。真实浏览器、真实模型与正式交付分别保留自己的证据，不能相互替代。

真实能力轮次现已按预定未知用量停止，实际 **2 PASS / 1 FAIL / 9 NOT_RUN**，共11次请求；已知12601 token、估算0.144171元，另保留0.169686元PENDING预留。两例业务通过同时证明了秒级修复；两条正文均有直接回答不足，不能宣称Agent全面达标。完整场景、原文评分、时延、逐请求CSV及启动失败见[本轮能力报告](../eval/2026-09-15-agent-capabilities/README.md)。按ADR0011诚实记录语义表现，没有增加正文拦截或重跑刷分。原始离线验证的可发布副本也保存在该目录的`verification/`。

## 5. 正式门禁与远端交付关联

本文在最终门禁之前冻结，**此处不预写完整门禁通过、PR 合入或 Issue 关闭结果**。聚焦浏览器入口为 `.local/project-audit-20260915/browser-focused.ps1`，其计划证据目录为 `.local/gate-evidence/issue242-browser-focused-20260915/`，实际结果以该目录的 `result.json` 和 `run.log` 为准。

按仓库流程完成一次集中风险审查及 Standards / Spec 双轴确认后，从仓库根目录执行：

```powershell
pwsh ./scripts/check.ps1 -Issue 242
```

完整门禁自动生成独立 RunId；正式记录需关联 `baseSha`、受测 `headSha`、RunId、构建/回归/浏览器耗时、清理结果与 `.local/gate-evidence/<实际 RunId>/` 的证据。最终 PR 结果应引用本文件及这次门禁记录，写明合并提交，并从 `origin/main` 回读实际提交和修复内容。只有该证据完整通过后才能合入并关闭 #242；GitHub Actions 保持关闭，不作为交付门槛。

聚焦日志中的基线 SHA、文档冻结后的交付 SHA 和远端合并 SHA 表示不同阶段，不能混称同一份受测版本。若后续结果与本文冻结时状态不同，应通过独立阶段日志和 PR 交付记录说明，保留已发生的失败及其原因。
