# Issue #29：3–5 分钟现场演示与录屏后备

> 当前口径：数据库迁移 V1→V21；客户、客服、审批人使用彼此隔离的浏览器上下文和 Spring Security Session。旧 `/support`、`/approver` 只用于兼容重定向，不作为演示入口。

## 演示前准备

1. 首次执行 `pwsh -File scripts/smoke.ps1 -Reset`，确认终端显示 `smoke suite: FULL_RESET_GATE`，Flyway V1→V21、Issue #29 正常执行/响应丢失后对账两条链、React live、产物与运行日志隐私扫描均通过。日常复测可执行 `pwsh -File scripts/smoke.ps1`，但 `PERSISTENT_RERUN_SUITE` 会保留既有数据并跳过要求空 fixture 的广域 `integration-smoke`，不能替代正式全量门禁。
2. 如需单独验证新版身份与页面，执行 `pwsh -File scripts/issue80-acceptance.ps1`；当前套件包含客户帮助中心、客服共享队列、审批工作台和跨身份真实 Chromium 验收，并在结束后回读隔离容器、数据卷、网络与镜像为空。
3. 打开三个相互隔离的 BrowserContext、浏览器配置文件或隐私窗口；同一上下文只有一个当前主体，不能靠普通标签页同时保留三种身份：
   - 客户：`http://127.0.0.1:4180/help/login`，选择“使用客户演示账号填充”后登录（账号 `customer-demo`）。
   - 客服：`http://127.0.0.1:4180/internal/login`，选择“使用客服演示账号填充”后登录（账号 `support-demo`），进入 `/internal/support`。
   - 审批人：另一个内部上下文打开 `/internal/login`，选择“使用审批演示账号填充”后登录（账号 `approver-demo`），进入 `/internal/approvals`。
   演示按钮只负责填充表单，仍需点击“登录”；本地演示密码为 `local-demo-password`。
4. 客户窗口预填 80 小时物流延迟的合成订单；客服窗口停在“客服共享队列”；审批窗口停在“待审批补偿”。浏览器始终只访问 Spring 同源 `/api`，不要直接打开 Agent Server 或数据库。
5. 录屏只包含产品页面和终端最终摘要，不录制 `.env`、容器环境、请求头、数据库控制台或真实模型密钥。

## 3–5 分钟讲解顺序

1. **0:00–0:45｜客户帮助中心**  
   在 `/help` 提交 80 小时物流延迟工单。指出客户壳只显示客户可见状态、处理模式和公开沟通；页面先读取 Spring 的 `CUSTOMER_PUBLIC` 权威快照，再从同一授权视图消费 SSE。真实本地 Agent Server/LangGraph 使用固定假模型与受限 Spring 工具调查，Spring 独立复核出 `26.80 CNY` 模拟部分退款，客户只看到“等待人工审批”，看不到内部推理、工具 payload 或审批证据。

2. **0:45–1:25｜客服共享队列与职责边界**  
   切到独立的 `support-demo` 窗口。先展示共享队列只含最小摘要，完整客户、订单、问题描述和调查事实不会在领取前预读；点击“领取工单”，在“确认领取工单”对话框中确认后，才出现“授权工单详情”、公开沟通、调查事实与业务时间线。说明分配撤销后详情会在最长 60 秒内清屏并重新同步 Spring 权威状态。此段用于展示客服职责，不要把客服身份当成审批人，也不要在同一 Session 中切换账号。

3. **1:25–2:20｜审批工作台**  
   切到另一个独立的 `approver-demo` 窗口。在 `/internal/approvals` 的最小队列中点击“领取审批”；领取前不读取 `APPROVAL_VIEW`，领取后才显示 `ORDER-DELAY-001`、权威金额、政策信息、证据引用与责任链。点击“批准补偿”，在“确认批准补偿”对话框中确认。强调这是 15 分钟排他租约下的一次最终决定：审批不等于执行；决定、释放、过期或租约撤销后，旧审批视图和操作立即失权并清屏。

4. **2:20–3:30｜执行不确定与安全对账**  
   回到客户窗口。模拟执行器已经记录退款，但首次响应丢失，Spring 将执行置为 `UNKNOWN`，客户看到“自动确认中”。普通重试被禁止，执行器只用原 `executionId` 与 `idempotencyKey` 查询 provider 持久事实；对账发现同一退款后，客户最终只看到一条 `26.80 CNY`、尾号 `4242` 的成功结果，工单进入 `RESOLVED`。强调这条路径证明“副作用不确定时不重复赔付”，而不是演示页面轮询碰巧成功。

5. **3:30–4:20｜自动化验证口径**  
   展示 `pwsh -File scripts/smoke.ps1 -Reset` 的最终摘要：`FULL_RESET_GATE`、Flyway V1→V21、正常执行与 `AFTER_EFFECT_RESPONSE_LOST` 两条 Issue #29 链均通过；每条链持久化断言都是一笔执行、一笔 provider operation、一笔执行结果、一笔退款和一条公开成功消息。再指出 `scripts/issue80-acceptance.ps1` 以真实 Chromium 覆盖双登录/双壳、客户帮助中心、客服共享队列、审批工作台、跨身份视觉与授权撤销，并在 finally 后回读隔离资源为空。不要把无 `-Reset` 的 `PERSISTENT_RERUN_SUITE` 描述成全量门禁。

6. **4:20–5:00｜边界**  
   这是可运行的本地全栈 Agent MVP：浏览器只连 Spring，Agent Server 与 PostgreSQL 不发布主机端口；演示账号、订单和支付均为合成数据。已验证的是身份隔离、最小授权视图、快照/SSE 恢复、审批租约和幂等对账；未验证真实支付、生产高可用、水平扩展、灾难恢复，或强制进程重启后的 checkpoint 生存。

## 现场操作速查

| 角色 | 正式入口 | 演示账号 | 现场只做什么 | 必须说清的验证点 |
|---|---|---|---|---|
| 客户 | `/help/login` → `/help` | `customer-demo` | 提交延迟工单；观察等待审批、自动确认和唯一成功结果 | 只见 `CUSTOMER_PUBLIC`；不见内部证据 |
| 客服 | `/internal/login` → `/internal/support` | `support-demo` | 看最小共享队列；确认领取；看授权详情 | 领取前不预读详情；撤权后清屏 |
| 审批人 | `/internal/login` → `/internal/approvals` | `approver-demo` | 领取审批；核对证据；确认批准 | 租约内才有 `APPROVAL_VIEW`；审批不等于执行 |

若从 `/internal` 进入，内部首页只展示当前身份有 capability 的静态工作区卡片，不会预读客服或审批业务数据。不要使用旧 `/support`、`/approver` 作为讲解路径；它们只重定向到正式内部路由。

## 录屏后备检查表

- 目标文件名：`customer-agent-issue29-local-mvp.mp4`，建议 1080p、5 分钟以内。
- 开头显示仓库提交号、V21 与“仅合成数据”；结尾显示 `FULL_RESET_GATE` 成功摘要、跨身份 Chromium 验收口径和上述边界。
- 三个角色必须来自隔离浏览器上下文；录屏中若展示账号填充按钮，要保留“仍需点击登录”的动作。
- 剪辑后逐帧检查：无密钥、Authorization、Agent 内部地址、PostgreSQL URI、prompt、reasoning、原始工具 payload、checkpoint、thread/run/trace 或真实业务数据。
- 录屏是现场演示后备，不替代自动化验收；仓库不提交含本机用户名、令牌或环境细节的视频二进制。
