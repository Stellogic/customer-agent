# 历史 Codex 自动 Review 审查台账（不含 PR #51）

## 1. 文档目的

本文记录 `Stellogic/customer-agent` 历史 Pull Request 中 Codex 自动 Review 提出的具体问题，并逐条核对：

- 原评论在被审查提交上是否成立；
- 严重度是否合理；
- 后续提交是否已经消除问题；
- 以 PR #51 当前 head `d32faa97903957e700befdb6f895838d8ab7ac57` 为基线，当前是否仍需处理；
- 推荐修复方向与应补充的验证。

本文**不包含 PR #51 自身的 Review 意见**，也不把 GitHub 线程的 `unresolved` 状态直接等同于当前代码仍有缺陷。历史线程即使没有手动 resolve，也可能已经被后续 PR 的实现消除。

## 2. 审查范围与方法

- 历史 PR 范围：[#30](https://github.com/Stellogic/customer-agent/pull/30) 至 [#50](https://github.com/Stellogic/customer-agent/pull/50)。
- 有具体 Codex inline Review 意见的 PR：#31、#34、#35、#39、#42、#47、#48。
- 具体 Review 意见总数：15 条。
- 验证方法：
  1. 读取 Review 标注的 reviewed commit；
  2. 检查评论指向的代码、SQL、迁移和调用链；
  3. 对照后续 PR 与当前实现；
  4. 区分“原评论成立”和“当前仍需修复”；
  5. 仅在证据足够时判定问题已消除。

本轮为静态代码与契约审查，没有声称已经为这些历史问题执行新的全栈测试。

## 3. 汇总结论

| 当前处置分类 | 数量 | 含义 |
| --- | ---: | --- |
| A：建议优先处理 | 8 | 当前仍存在，会破坏可靠性、业务不变量、队列正确性或验收可重复性 |
| B：建议后续加固 | 4 | 当前仍存在，但主要属于边界一致性、低概率并发或验收覆盖缺口 |
| C：当前无需改代码 | 3 | 原评论成立或基本成立，但后续实现已经消除触发路径 |

准确性汇总：

- 14 条评论的核心诊断准确；
- 1 条评论部分准确：确有覆盖缺口，但原建议的直接修法会产生稳定误报；
- 未发现完全虚构、与代码无关的评论。

## 4. A 类：建议优先处理

### A-1 PR #31：Agent 可用性探测没有显式超时

- 来源：[PR #31](https://github.com/Stellogic/customer-agent/pull/31)
- Reviewed commit：`94f62c26dc`
- 原位置：`backend/src/main/java/com/stellogic/customeragent/status/StatusConfiguration.java`
- Codex 严重度：P2
- 审查结论：**准确，P2 合理**
- 当前状态：**仍需处理**

#### 证据

状态探测仍直接创建：

```java
new SimpleClientHttpRequestFactory()
```

没有设置连接超时和读取超时。Agent 接受连接后不返回响应时，`/api/system/status` 可能长期占用请求线程，无法及时把 Agent 投影为 `DOWN`。

虽然最初的状态展示页面已经变化，但状态接口仍被 smoke 和运维探针调用，因此后续 UI 变化没有消除该风险。

#### 推荐处理

- 为专用 request factory 配置较短的 connect/read timeout；
- 将超时视为 Agent `DOWN`，不要让异常泄露成未控制的 5xx；
- 添加“TCP 可连接但响应不完成”的探测测试；
- 验证重复状态请求不会无限占用 servlet 线程。

---

### A-2 PR #34：审批证据快照保存了净额度而不是总额度

- 来源：[PR #34](https://github.com/Stellogic/customer-agent/pull/34)
- Reviewed commit：`5504a46421`
- 原位置：`backend/src/main/java/com/stellogic/customeragent/investigation/JdbcAgentInvestigationService.java`
- Codex 严重度：P2
- 审查结论：**准确**
- 当前状态：**仍需处理**

#### 证据

当前实现先计算：

```java
available = availableCompensationAmount - activeReservationAmount
```

随后把 `available` 写入审批快照的 `available_compensation_amount`，同时又单独写入 `active_reservation_amount`。

这与字段语义不一致。审批阶段会把快照额度与订单权威总额度比较，并独立核对活跃预占。当存在活跃预占时，快照中的净额度可能被当作总额度，造成事实漂移误判或重复扣减语义。

#### 推荐处理

- 资格判断继续使用净额度；
- 审批快照保存原始总额度和原始活跃预占额；
- 明确命名 `totalAvailableAmount`、`activeReservationAmount` 和 `remainingAmount`，避免再次混用；
- 增加“总额度 268、已有预占 10、当前提案仍可批准”的测试；
- 审批时再次读取权威数据并验证 `activeReservations + proposedAmount <= totalAvailableAmount`。

---

### A-3 PR #35：确定性澄清拒绝被误当作响应丢失

- 来源：[PR #35](https://github.com/Stellogic/customer-agent/pull/35)
- Reviewed commit：`b4ada054e6`
- 原位置：`frontend/src/App.tsx`
- Codex 严重度：P2
- 审查结论：**准确**
- 当前状态：**仍需处理**

#### 证据

当前前端对所有非 2xx 响应统一抛出异常，然后进入“响应可能丢失”的恢复查询。

这会把以下确定性业务拒绝错误归入不确定状态：

- 非 A/B 的回答返回 422；
- 澄清请求已经过期或失效返回 409；
- 其他明确的客户端输入错误。

恢复状态接口通常找不到对应的成功提交记录，于是 UI 显示“回复状态暂时未知，请重试”，错误鼓励用户重试一个确定不会成功的请求。

#### 推荐处理

- 网络异常、5xx、连接中断：进入幂等对账；
- 409：刷新权威快照并说明澄清已失效或状态已变化；
- 422：显示字段级校验错误，不进入对账；
- 401/403/404：按授权或资源状态分别处理；
- 添加 409、422、响应丢失三类前端测试，确保文案和后续动作不同。

---

### A-4 PR #42：终态成功重放未校验调用方 attempt

- 来源：[PR #42](https://github.com/Stellogic/customer-agent/pull/42)
- Reviewed commit：`b50f504796`
- 原位置：`backend/src/main/java/com/stellogic/customeragent/execution/JdbcCompensationExecutionService.java`
- Codex 严重度：P2
- 审查结论：**准确**
- 当前状态：**仍需处理**

#### 证据

执行已经是 `SUCCEEDED` 时，新请求可以提交一个无关的 `attemptId`。当前逻辑校验执行意图参数和 provider 成功事实，但没有要求调用方 attempt 与持久化结果 attempt 一致。

随后：

- 请求摘要包含调用方提供的无关 attempt；
- `compensation_success_request` 记录的却是实际结果 attempt；
- API 返回成功重放。

这会让请求身份、请求摘要、结果 attempt 与审计记录之间不一致。它不会直接制造第二笔补偿，但破坏执行器协议和审计可解释性。

#### 推荐处理

- 进入 `SUCCEEDED` 重放分支前读取结果 attempt；
- 要求调用方 attempt 与结果 attempt 一致，否则返回 409；
- 或者定义明确的“按 execution 查询结果”独立接口，不让新 success command 冒充历史 attempt；
- 添加“正确 attempt 重放成功、错误 attempt 被拒绝、同 requestId 参数冲突”的测试。

---

### A-5 PR #42：补偿成功解决工单前没有同步固化 SLA 事实

- 来源：[PR #42](https://github.com/Stellogic/customer-agent/pull/42)
- Reviewed commit：`b50f504796`
- 原位置：`backend/src/main/java/com/stellogic/customeragent/execution/JdbcCompensationExecutionService.java`
- Codex 严重度：P2
- 审查结论：**准确**
- 当前状态：**仍需处理**

#### 证据

无补偿的 Agent 终态路径会先调用 `SlaService.evaluateTicket(ticketId, now)`，补偿成功路径却直接调用 `afterCompensationExecution()` 停止解决时钟并转为 `RESOLVED`。

如果工单在等待补偿期间刚跨过 warning 或 breach 边界，成功事务完成后可能暂时缺少：

- 不可变 SLA fact；
- 对应审计事件；
- 通知；
- SLA breach 共享队列记录。

周期调度器可能事后补齐，但这不满足关键业务事实与终态转换同步提交的设计目标。

#### 推荐处理

- 在补偿成功事务中、停止时钟前调用 `evaluateTicket(ticketId, now)`；
- 保持评估、成功结果、工单解决和审计处于同一事务；
- 添加“补偿完成瞬间跨过 warning/breach 阈值”的测试；
- 验证重复成功回放不会重复插入 SLA fact 或队列记录。

---

### A-6 PR #47：关闭后的工单仍留在客服共享队列

- 来源：[PR #47](https://github.com/Stellogic/customer-agent/pull/47)
- Reviewed commit：`b52c85228b`
- 原位置：`backend/src/main/java/com/stellogic/customeragent/closure/JdbcClosureService.java`
- Codex 严重度：P2
- 审查结论：**准确**
- 当前状态：**仍需处理**

#### 证据

`closeLocked()` 把工单更新为 `CLOSED`，但没有删除 `shared_support_queue_entry`。

同时 `SupportWorkbenchProjectionService.queueItems()`：

- join 到 `support_ticket`；
- 不过滤 `CLOSED`；
- 因此仍会把关闭工单返回给客服工作台。

结果是已经终止的工单可能永久显示为“需要处理”。

#### 推荐处理

- 在关闭事务中删除该工单的共享队列记录；
- 确保删除操作产生对应的 queue removal 投影事件；
- 查询层也可增加 `CLOSED` 防御性过滤，但不能代替权威队列清理；
- 添加“已有 SLA_BREACH/handoff 队列记录的工单关闭后立即消失”的快照与 SSE 测试。

---

### A-7 PR #48：固定 E2E 场景无法无重置重复运行

- 来源：[PR #48](https://github.com/Stellogic/customer-agent/pull/48)
- Reviewed commit：`eb394bdf24`
- 原位置：`scripts/smoke.ps1`
- Codex 严重度：P2
- 审查结论：**准确**
- 当前状态：**仍需处理**

#### 证据

Issue #29 的两个 E2E 场景使用固定订单：

- `ORDER-DELAY-E2E-NORMAL`
- `ORDER-DELAY-E2E-RECONCILIATION`

首次成功后，订单会保留 `existing_compensation = true`，并残留 execution、result 和 provider operation。下一次不带 `-Reset` 运行时：

- Agent 不能再生成预期提案；
- 精确数量断言也会受到旧记录影响；
- 文档所称的日常重复 smoke 路径失效。

#### 推荐处理

优先选择场景级隔离，而不是危险的全库清理：

- 每次运行生成新的合成订单/场景 namespace；或
- 在 smoke 开始前调用严格限定到两条 E2E fixture 的数据库清理过程；
- 清理顺序必须覆盖依赖表，并验证目标只包含合成 fixture；
- 测试连续运行两次 `smoke.ps1`（第二次不使用 `-Reset`）均成功。

---

### A-8 PR #48：固定时钟下对账尝试顺序不确定

- 来源：[PR #48](https://github.com/Stellogic/customer-agent/pull/48)
- Reviewed commit：`eb394bdf24`
- 原位置：`scripts/smoke.ps1`
- Codex 严重度：P2
- 审查结论：**准确**
- 当前状态：**仍需处理**

#### 证据

验收 SQL 使用：

```sql
string_agg(a.outcome, ',' order by a.started_at)
```

默认 Compose 使用固定时钟时，初次执行 attempt 和 reconciliation attempt 可能拥有相同 `started_at`。PostgreSQL 对相同排序键的返回顺序没有保证，因此预期的 `UNKNOWN,FOUND` 可能变成 `FOUND,UNKNOWN`。

这属于确定性验收中的真实 flaky 风险。

#### 推荐处理

- 添加有业务语义的稳定次级排序键；
- 例如按 `started_at` 后再按 attempt 类型顺序排列 EXECUTION、RECONCILIATION；
- 不建议仅依赖随机 UUID 排序表达业务先后；
- 增加固定时钟下多次运行的稳定性验证。

## 5. B 类：建议后续加固

### B-1 PR #34：`delayHours` 没有进入提案内容摘要

- 来源：[PR #34](https://github.com/Stellogic/customer-agent/pull/34)
- Reviewed commit：`5504a46421`
- 原位置：`backend/src/main/java/com/stellogic/customeragent/investigation/JdbcCompensationProposalStore.java`
- Codex 严重度：P2
- 审查结论：**准确**
- 当前状态：**仍需处理，优先级中等**

#### 证据

不可变提案和审批快照同时保存 `delayHours`、`delaySeconds`，内容摘要却只包含 `delaySeconds`。

数据库只分别约束二者非负，没有约束：

```text
delaySeconds = delayHours × 3600
```

fixture 角色还可以分别更新这两个字段。因此在秒数字段不变、小时字段被修正时，系统可能复用旧 revision。

#### 推荐处理

- 将 `delayHours` 纳入摘要；
- 更重要的是增加数据库一致性约束，或删除冗余字段并从秒数确定性派生小时数；
- 添加“只修改 hours”和“只修改 seconds”的 revision 测试。

---

### B-2 PR #34：零支付金额会生成零金额退款并最终返回 500

- 来源：[PR #34](https://github.com/Stellogic/customer-agent/pull/34)
- Reviewed commit：`5504a46421`
- 原位置：`backend/src/main/java/com/stellogic/customeragent/compensation/DelayCompensationPolicy.java`
- Codex 严重度：P2
- 审查结论：**准确**
- 当前状态：**仍需处理，触发条件较窄**

#### 证据

数据库允许 `paid_amount >= 0`。当记录满足：

- `paid = true`；
- `paid_amount = 0`；
- 延迟超过 72 小时；

政策返回 eligible 的 `SIMULATED_PARTIAL_REFUND 0.00`。随后 proposal 插入违反 `amount > 0` 约束，形成 500，而不是可解释的确定性业务拒绝。

#### 推荐处理

- 在政策层或服务层拒绝非正数原支付金额的部分退款；
- 明确返回 ineligible decision 或受控 422；
- 添加零金额、负金额数据库防御和极小金额舍入到 0.00 的测试。

---

### B-3 PR #39：审批队列在可能等待锁之前采样时间

- 来源：[PR #39](https://github.com/Stellogic/customer-agent/pull/39)
- Reviewed commit：`0d986e2f0c`
- 原位置：`backend/src/main/java/com/stellogic/customeragent/approval/JdbcApprovalService.java`
- Codex 严重度：P2
- 审查结论：**准确，但实际严重度更接近低优先级一致性问题**
- 当前状态：**仍需处理，可后置**

#### 证据

`queue()` 先执行：

```java
Instant serverNow = clock.instant();
proposalExpiry.expireDue(serverNow);
```

如果 `expireDue` 或相关数据库操作等待并发事务，并在等待期间跨过 proposal/lease 到期边界，后续查询仍使用等待前的时间参数。

一次响应可能：

- 返回实际上已经过期的提案；
- 暂时隐藏实际上已经到期释放的租约。

下一次请求通常可以恢复，因此没有评论所暗示的长期破坏性。

#### 推荐处理

- 完成可能阻塞的过期处理后重新采样时钟；
- 或尽量使用数据库 `CURRENT_TIMESTAMP` 保持锁后判断一致；
- 添加可控时钟与阻塞事务跨越租约边界的测试。

---

### B-4 PR #48：运行日志没有真正覆盖 Agent 内部地址规则

- 来源：[PR #48](https://github.com/Stellogic/customer-agent/pull/48)
- Reviewed commit：`eb394bdf24`
- 原位置：`scripts/smoke.ps1`
- Codex 严重度：P2
- 审查结论：**部分准确**
- 当前状态：**验收缺口仍存在，但不能直接采用原建议**

#### 准确部分

当前变量：

- `sensitiveContentPattern` 只包含 `contentPatterns`；
- `internalAddressPatterns` 只加入前端产物扫描；
- runtime log 扫描继续使用 `sensitiveContentPattern`。

因此 Issue #29 所要求的“日志不包含 Agent 内部地址”没有被当前脚本完整验证。

#### 原建议的问题

如果把两组规则直接合并后扫描完整 `docker compose logs`，Compose 自己会在日志行前添加服务名。规则中的 `agent-server` 很可能直接匹配日志前缀，从而让 smoke 稳定误报。

#### 推荐处理

- 先区分基础设施元数据与应用日志正文；
- 剥离 Compose 日志前缀后再检查应用消息；
- 或按容器读取结构化应用日志，只扫描受保护字段；
- 明确允许的内部运维日志与禁止进入产品日志/浏览器投影的内容；
- 不要简单把 `frontendSensitivePattern` 原样应用到完整 Compose 输出。

## 6. C 类：当前无需修改代码

### C-1 PR #31：`DEGRADED` 被渲染成一直加载

- 来源：[PR #31](https://github.com/Stellogic/customer-agent/pull/31)
- Reviewed commit：`94f62c26dc`
- 原位置：`frontend/src/App.tsx`
- Codex 严重度：P2
- 审查结论：**在当时准确**
- 当前状态：**无需处理**

当时页面仅在 `failed=true` 或 `status=UP` 时进入完成态；后端成功返回 `DEGRADED` 会继续显示“正在确认服务状态”。

后续前端已经替换为完整客服工单 UI，原状态卡渲染逻辑不存在。不要为了关闭历史线程重新引入无用分支。

---

### C-2 PR #34：不合格提案会导致 generation 无限失败重投

- 来源：[PR #34](https://github.com/Stellogic/customer-agent/pull/34)
- Reviewed commit：`5504a46421`
- 原位置：`backend/src/main/java/com/stellogic/customeragent/investigation/JdbcAgentInvestigationService.java`
- Codex 严重度：P1
- 审查结论：**在当时准确，P1 有依据**
- 当前状态：**已被后续安全转人工实现消除**

当时固定 Agent 会向未支付、已取消、已退款或已有补偿的订单提交普通物流延迟提案；Spring 返回 422，但没有终止 generation/submission，可能被 dispatcher 周期性重新领取并持续创建失败 run。

后续实现已经：

- 在 Agent 侧识别不安全/不支持的订单事实；
- 调用受限 human-handoff；
- 对 conclusion 422 转入受控 `FACT_CONFLICT` handoff；
- 在 Spring 转人工事务中结束 active generation、submission 和 resume request。

当前无需再次修改该拒绝分支。

建议在 GitHub 线程中说明由后续 handoff PR 修复并 resolve，而不是提交重复补丁。

---

### C-3 PR #35：恢复调查期间未重新检查客户人工偏好

- 来源：[PR #35](https://github.com/Stellogic/customer-agent/pull/35)
- Reviewed commit：`b4ada054e6`
- 原位置：`agent/src/baseline_agent/graph.py`
- Codex 严重度：P1
- 审查结论：**风险判断基本准确，但在当时功能阶段 P1 略显超前**
- 当前状态：**已被后续客户转人工实现消除**

PR #35 时已经存在 `customer_human_preference` 字段，但完整客户转人工命令尚未交付。后续实现的转人工事务会同时：

- 设置 `customer_human_preference = true`；
- 设置 `handling_mode = HUMAN`；
- 将 active generation 改为 `HANDED_OFF`；
- 将 submission 和 resume request 改为 `COMPLETED`。

迟到的 Agent 工具调用会因 generation 或 handling mode 不再满足权威作用域而被拒绝。

因此当前不需要在 LangGraph edge 上再增加一个非权威的本地偏好判断。真正的授权检查应继续由 Spring 完成。

## 7. 推荐实施顺序

建议不要把全部历史业务修复塞进质量门禁 PR #51。

### 第一批：可靠性与业务不变量

1. A-2 审批快照总额度语义；
2. A-4 终态成功 attempt 重放；
3. A-5 解决前固化 SLA；
4. A-6 CLOSED 工单退出共享队列。

### 第二批：接口与验收可靠性

1. A-1 Agent 探测超时；
2. A-3 澄清 4xx 分类；
3. A-7 smoke 场景重复运行；
4. A-8 attempt 稳定排序。

### 第三批：边界加固

1. B-1 延迟字段摘要与数据库一致性；
2. B-2 零金额政策；
3. B-3 锁等待后的时间重采样；
4. B-4 运行日志检查边界。

## 8. 完成标准

每条问题完成时至少应记录：

- 修复提交或 PR；
- 对应回归测试；
- 当前 CI/全栈验收结果；
- 是否可以 resolve 原 GitHub Review thread；
- 若不修复，明确接受风险与原因。

只有“后续代码已经消除触发路径”或“回归测试验证修复”才应标记为完成；不能仅因为 GitHub 线程过旧而关闭。
