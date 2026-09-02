# #193 内部壳与非核心入口：隔离静态预开发

## 第五阶段：前置完成后的正式集成（2026-09-03，当前状态）

状态为 **READY_FOR_FINAL_GATE**。已同步包含 #170 的 `origin/main@76e38ff11bbd7ae549cdc905a2b61443d37801ee`；唯一冲突是 `SupportWorkbench.tsx` 的 import，合并提交 `d8b76cc` 同时保留 #170 `SupportAssistance` 与 #193 `SupportContextEntries`，没有复制前置实现。本票无迁移，主线最新迁移为 #170 的 V44。

- HUMAN 且当前辅助权限有效时，“相似案例”“建议动作”现在定位同一工单的真实客服辅助区域；当前无人工辅助权限时保持不可用。入口本身不发请求，客服仍须在 #170 面板内选择知识检索、总结、政策或草稿操作。
- `SupportAssistance` 仅增加可选 `hostRef`，把既有根节点作为聚焦目标；不增加接口、请求或业务动作。真实辅助撤权时，若发送区内容仍是 AI 移交草稿，父组件以 state 在同次渲染中隐藏该内容；用户重新人工编辑会立即解除辅助草稿标记。
- #193 Chromium 文件已加入正式串行浏览器验收清单。它覆盖客服/审批身份、1440/360px、loading/error、Session 失效、键盘焦点、基础语义与截图；使用合成 Session 验证壳层，不冒充 Spring 资源授权验收。

聚焦运行均使用仓库权威锁并在 `finally` 释放：

| RunId | 结果 |
| --- | --- |
| `issue193-focused-20260903a` | 前端规范化检查中 225 PASS、1 FAIL、3 skipped；失败为 #170 既有“详情权限流断开时先清辅助草稿”断言，#193 接线测试 4/4 PASS。 |
| `issue193-recheck-20260903b` | 格式、目标 lint、全前端类型通过；7 项定向中 6 PASS，撤权草稿仍失败，证明移除外层 wrapper 不足。 |
| `issue193-recheck-20260903c` | Prettier 在测试前发现一处分行，未运行后续检查。 |
| `issue193-recheck-20260903d` | 格式通过；lint 在测试前禁止 render 读取 ref，未运行后续检查。 |
| `issue193-recheck-20260903e` | Node 24.19.0；格式、目标 lint、全前端类型、浏览器验收清单契约通过；3 文件定向 **7 PASS**、26 未选中。 |
| `issue193-final-20260903a` | 完整门禁前序检查、构建和全栈持久化通过；冻结 RAG 在 0/64 处因本 worktree 忽略目录缺少离线 BGE 模型而报 `ValueError`。证据记录 64 项未运行、付费模型成本 0。 |
| `issue193-final-20260903b` | 逐文件按当前协议校验并复用既有冻结模型后，RAG 检索层通过；真实 Chromium 为 46 PASS、8 FAIL。失败收敛为本票 CSS 的焦点色覆盖，以及窄屏列布局下 Ant 内层 Layout 保留 `width: 0`。 |
| `issue193-browser-recheck-20260903a` | 首次 CSS 聚焦复验 19 PASS、7 FAIL；统一焦点色修复已通过，初版窄屏宽度规则因选择器权重不足未生效。 |
| `issue193-browser-recheck-20260903b` | 高权重直接子选择器覆盖 Ant 布局约束；6 个受影响文件真实 Chromium **24/24 PASS**，隔离容器、网络、卷和镜像清理后锁为 FREE。 |

每次结束均已向协调任务发送 `LOCK_RELEASED` 并读回 `TEST_GATE_FREE`。日志保留在 worktree 忽略目录 `.local/issue193-*.log`。失败由有效工程证据逐步收窄；没有降低断言、增加超时或重复运行无关套件。

PR #205 已从 Draft 转 Ready 一次。集中安全审查因外部 Codex 额度不可用而未产出，集中 Code Review 长时间停留在 Running 且无发现；按本任务已确认边界，这类外部审查不可用不阻塞交付，也未手动触发第二轮。随后以 `origin/main@76e38ff11bbd7ae549cdc905a2b61443d37801ee` 为固定点，对当前非空差异完成独立 Standards / Spec 双轴审查：两轴均为 **PASS，0 项阻塞发现**，且都未运行测试或门禁。

当前 #193 真实 Chromium、客服/知识窄屏回归与跨角色焦点一致性均已取得通过证据；完整门禁尚未最终通过。下一步在本次证据与 CSS 修复提交后完成增量 Standards / Spec 双轴确认，不再修改跟踪文件，再回读最新 `origin/main` 并持权威锁运行 `pwsh ./scripts/check.ps1 -Issue 193`。CI 关闭。

## 第四阶段：定向复验通过（2026-08-31，历史记录）

状态为 **FOCUSED_VALIDATED**，仅本阶段授权范围通过聚焦验证，不代表完整前端套件、浏览器或整票交付通过。第三阶段的待复验结论保留为历史记录。

- 协调任务重新明确分配窗口后，使用默认权威锁运行 `issue193-20260831-focus4`。验证基线 `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`，验证 HEAD `280d3b1c7ec2d5efca327018640eff5c2232b7c8`；运行期间无源码修改，本次格式命令也未产生改动。
- Node **24.19.0**；限定 12 个本票相关文件 Prettier 通过且全部 unchanged；全前端 `tsc --noEmit` 通过。
- 本票三个文件 **20/20 PASS**：InternalShell 6 项、ContextEntries 10 项、WorkbenchContextEntries.integration 4 项。最新参数化修复已完成运行复验，未删减名称、关闭、无请求与撤权断言。
- 此前失败的客户路由单项 **1/1 PASS**，同文件另外 32 项为未选中，不计作通过。没有改动路由/Session 源码或提高超时；首次加载超时原因仍未证实，本次只表明失败未在定向复验中重现。
- 三文件运行耗时 42.83 秒；路由单项运行耗时 18.72 秒。原始日志在本 worktree 忽略目录 `.local/issue193-focus4.log`。执行入口 `.local/issue193-recheck.ps1` 在 finally 释放锁；日志末尾为 `LOCK_RELEASED ... result=PASS`、`TEST_GATE_FREE`，已成功通知协调任务并归还窗口，不等待静态收尾占锁。
- 仅执行所授权的必要格式、类型和聚焦测试。没有运行 lint、构建、浏览器、Docker、模型/评测或完整门禁，也没有重跑 focus2 已通过的客服/审批套件。CI 保持关闭。

三文件命令：`node node_modules/vitest/vitest.mjs run src/shells/InternalShell.test.tsx src/components/internal/ContextEntries.test.tsx src/WorkbenchContextEntries.integration.test.tsx --maxWorkers=1`。

路由单项命令：`node node_modules/vitest/vitest.mjs run src/Routing.test.tsx -t '客户路由使用 CustomerShell，且不出现内部导航' --maxWorkers=1`。以上均从 frontend 目录执行，并在整个运行期间持有仓库锁。

本次无源码增量，原实现/测试修复 `df2da9e` 的 Standards PASS / Spec PASS 仍对应相同源码。本次第四阶段证据文档另经独立 Standards PASS / Spec PASS，各 0 项有效问题，两轴均只读核对日志与执行脚本。此次只更新运行证据，不把聚焦结果当成最终完整门禁；后续文档提交不会冒称在新 HEAD 重新跑过门禁。

剩余事项：#170 前置与真实辅助功能接线；真实浏览器下连续弹窗、宽窄屏、Session/SSE 撤权、键盘和视觉证据；最新 main 同步、迁移/共享文件核对、增量 CR；明确放行后运行完整本地门禁。PR 继续 Draft，Issue 继续 OPEN，不转 Ready、不合并、不关票。


## 第三阶段：前端聚焦验证与修复（2026-08-31，历史记录）

当前为 **FOCUSED_VALIDATION_PENDING**：已有运行证据，但聚焦验证尚未全部通过；不能继续笼统称为“从未测试”，也不能称整票完成。第二阶段的禁测和 CODE_READY_NO_TESTS 是历史窗口记录，已由本次明确授权取代。

### 授权、基线与源码

- 协调任务明确给出必要前端格式、类型、聚焦组件测试及合理复验窗口。仍不授权构建、浏览器、Docker、模型、评测或完整门禁，不修改 App、Session/route、公共验收注册、业务核心或 #170 区域。
- 基线保持 `origin/main@c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。本轮没有再次改变集成范围，无迁移；#170 仍阻塞整票最终集成与交付。
- `a853cf90ad4d79519a8a30dddf90a8d48d98c8d3`：去掉 Testing Library getByRole 不支持的五处 exact 选项（字符串 name 本身仍为严格匹配），格式化本票相关文件。Playwright 的 exact 保留。业务源码仅 SupportWorkbench 的等价格式调整。
- 当前实现/测试修复提交 `df2da9e8e34d0e50b19b93088252bf9200c0a132`：三个专属测试通过局部 ConfigProvider 禁用 motion，保留真实 Modal；将多弹窗循环拆成独立参数化用例，保留严格可访问名称、关闭、无请求与撤权断言。未修改生产弹窗、全局测试配置或超时。

### 实际运行证据

所有运行通过仓库 Enter-TestGateLock / Exit-TestGateLock 获取和释放默认权威锁；每次 finally 后读回 TEST_GATE_FREE，并向协调任务发送 LOCK_RELEASED。没有绕锁、轮询或运行完整 check.ps1。

| RunId | 范围与结果 | 证据边界 |
| --- | --- | --- |
| issue193-20260831-focus1 | 离线缓存安装依赖（ignore-scripts）；限定 12 个文件格式化完成；类型检查因 5 个 exact 选项失败；测试未启动 | 默认 Node 22.15.0 与仓库要求不符，本次不是合格运行环境证据；随后改用 bundled Node 24.19.0 |
| issue193-20260831-focus2 | Node 24.19.0；限定格式、全前端 tsc --noEmit 通过；6 文件 88 项：83 PASS、5 FAIL | 客服/审批既有套件通过。4 项新增用例停在关闭动画；Routing 客户页用例等待 CustomerShell 超时，DOM 仍为加载态，原因未证实 |
| issue193-20260831-focus3 | Node 24.19.0；限定格式、类型通过；本票 3 文件 16 项：14 PASS、2 FAIL | 局部禁 motion 后 InternalShell 6/6 通过，关闭断言已通过；另 2 项在打开第二弹窗时名称查询失败。后续客户路由单项复验因前一步失败未执行 |

运行使用本地 Prettier 3.9.6、TypeScript 6.0.3、Vitest 4.1.0，单 worker、文件串行。原始日志保留在当前 worktree 的忽略目录 `.local/issue193-focus1.log`、`issue193-focus2.log`、`issue193-focus3.log`，不作为最终完整门禁证据。

focus2 调用：`node node_modules/vitest/vitest.mjs run src/shells/InternalShell.test.tsx src/components/internal/ContextEntries.test.tsx src/WorkbenchContextEntries.integration.test.tsx src/SupportWorkbench.test.tsx src/ApprovalWorkbench.test.tsx src/Routing.test.tsx --maxWorkers=1`。focus3 仅复验前三个本票文件，没有重跑已通过的客服/审批套件。

### 失败定位、已修复与仍待复验

- 动画：focus2 日志显示 ant-zoom-leave-active；测试局部关闭 motion 后，focus3 的关闭断言通过。不改生产动画，不能据此证明浏览器动画与焦点效果。
- 标题 ID：focus3 日志显示隐藏旧弹层和可见新弹层都引用 `test-id`。锁定依赖 `@rc-component/util/es/hooks/useId.js` 在 NODE_ENV=test 下固定返回该 ID，生产使用 React useId。独立参数化用例避免这种测试模式的跨实例 ID 冲突，不放宽名称断言，也不通过新增生产销毁行为掩盖问题。同次挂载连续打开不同弹窗的覆盖转为待浏览器验证，不声称参数化用例覆盖该序列。
- 最后的参数化调整发生在 focus3 释放锁之后，**尚未运行格式、类型或测试复验**。不能把前一版本的类型/格式结果算到最终 HEAD，也不能把 14/16 推断为最终全部通过。
- 客户路由首次失败仍保留，未改 RootApplication/App/Session；没有证据将其定性为产品缺陷或单纯环境抖动。下一次窗口先做必要定向复验，若仍失败再报告证据。
- 后续仍需真实浏览器宽窄屏、Session/SSE 撤权联动、键盘和视觉证据，以及前置正式交付后的 main 同步、迁移核对、增量 CR 与明确放行的完整门禁。CI 关闭，PR 保持 Draft，Issue 保持 OPEN。

### 窗口与静态审查

`issue193-20260831-focus3` 已释放锁，运行窗口已正式归还协调任务，优先供 #190 下游验证。进入纯静态收尾，**等待重新分配前不再查询锁或运行验证**。

本轮类型选项/格式修复与测试环境修复分别经过独立 Standards / Spec 增量审查；最终修复范围 `a853cf9..df2da9e`：**Standards PASS / Spec PASS**，各 0 项有效问题。两轴均只读源码与证据，确认未修改生产行为、未放宽断言，并明确最后修复和 Routing 失败尚未复验。此静态结论不替代尚未通过的运行验证；后续仅更新交接记录的提交不改变该源码审查范围。


## 第二阶段：现有授权内容接线（2026-08-31，历史静态记录）

协调任务已明确允许修改 SupportWorkbench / ApprovalWorkbench 中本票入口挂载与定位现有内容的最小区域。#163/#164/#166 已交付；#170 只继续阻塞其辅助 composer、建议动作实际行为与检索接线，不再阻塞本轮普通入口。

- 已将最新 `origin/main@c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472` 合入原分支，无冲突，保留第一阶段提交。当前依据是主线实现，PR202 固定 SHA 仅为历史参考。
- 客服详情已挂载 SupportContextEntries：查看订单定位现有订单引用；查看物流定位当前调查事实并说明字段范围；联系客户仅在 HUMAN 模式下定位既有人工公开回复区，不自动填充或发送。转派/更多操作继续无请求“开发中”；相似案例/建议动作禁用并明确尚未接入，未挂载 #170 面板。
- 审批队列已挂载更多筛选/导出无副作用入口；取得当前审批投影后挂载详情入口，政策详情定位政策信息，提案日志定位责任链，资格明细定位既有资格与金额区，物流轨迹定位既有延迟事实并说明完整轨迹未接入。完整对话仍禁用，不访问客服 API。
- 仅添加 refs、可聚焦目标与入口 props，不改领取、回复、标准补偿或审批业务流程。客服宿主清除 details、审批宿主清除 snapshot 时入口一同卸载，不建立第二份数据缓存或授权机制。SessionGate 仍负责主体失效卸载；本票没有修改 Session 契约。
- 客服投影键使用现有 ticketId / assignedSupportId / handlingMode（没有新造版本字段）；同步与撤权依赖宿主卸载。审批投影键使用 proposalRevisionId / leaseVersion / cursor。普通字段更新沿用宿主当前数据，入口回调只聚焦当前 DOM。
- 专属测试源码 `frontend/src/WorkbenchContextEntries.integration.test.tsx` 覆盖真实宿主组件的恢复挂载、内容焦点、点击不增加请求、客服同步/撤权移除弹层、非 HUMAN 禁止联系、审批撤权清屏；标准补偿子面板在该入口测试中隔离，不替代 #164 测试。
- 迁移只读核对：主线已包含 V34 客服、V35 知识、V36/V37 补偿以及 V39–V41 后续功能；本票无新增或修改迁移，不复制前置迁移。
- 本轮仍禁止测试、格式、lint、类型检查、构建、浏览器、Docker、模型/评测和锁查询。未运行任何上述命令，未查询或占用测试锁；运行窗口属于 #190。无新增截图或可运行性证据。
- 待验证：源码格式/类型/测试、真实 Session 与 SSE 撤权联动、浏览器宽窄屏/焦点/视觉证据、审批租约失效和全门禁。#170 接线仍未完成，最终集成需再次同步 main、迁移核对和增量 CR，且须获得明确验证放行；不合并、不关票。
- 本轮静态双轴 CR：独立 Standards **PASS** / Spec **PASS**，均为 0 项有效问题；范围 `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472...3191f5415490903c06ecd8976130c139d11674c9`，重点增量 `669ced0..3191f54`。两轴确认仅定位现有授权 DOM、没有新增请求/核心行为，宿主清屏同时卸载入口。第一阶段 PASS 仅是历史记录，没有直接沿用到新接线。
- 阶段状态仍为 `CODE_READY_NO_TESTS`。GitHub 只读回核 #163/#164/#166 均 CLOSED、PR202 MERGED（合入提交 `932fd194b4d8d232bafb5154ec8bb4c56cf20536`）；这不代表本票验证或交付完成。后续仅更新本记录的提交不改变上述实现源码。

以下为第一阶段历史记录；其中“尚未挂载”“不修改工作台”等范围描述已由上面的第二阶段授权与实施记录替代。

## 范围与基线

- 规格来源：[Issue #193](https://github.com/Stellogic/customer-agent/issues/193)，2026-08-30 读取正文与评论（当时无评论）。仅覆盖协调任务明确授权的可提前范围，整票仍为 OPEN。
- 起点：最新 `origin/main` / `2ca9d097da1f93d4cdf3eeef347c62cf51f0e058`；分支 `codex/issue-193-internal-shell`。
- 前置只读参考：[PR #202](https://github.com/Stellogic/customer-agent/pull/202)，固定 `8ed21c9a026fab7806a952df002a228269a57ec3`。仅核对其文件归属、客服补偿面板集成区域；未复制实现或修改前置分支。
- 只修改 `InternalShell.tsx` 非业务壳，新增专属组件、CSS、独立测试及视觉验收源码和此记录。未修改 App、SupportWorkbench、ApprovalWorkbench、共享 styles.css、Session/route 契约和公共验收注册。

## 实现映射

| 入口 | 本阶段行为 | 依据 / 限制 |
| --- | --- | --- |
| 我的工单 | 真导航到既有客服工作区 | 主线从快照恢复 assignedTicketIds 与当前已领取详情；不编造 `/ticket` 路由或筛选 query |
| SLA 监控 | 真导航到既有客服工作区 | 页面已有 SLA 违约升级队列；入口注明“违约升级队列”，不冒充独立 SLA 仪表盘 |
| 知识库 | 有 KNOWLEDGE_READ_ACCESS 时真导航到知识目录 | 复用现有 workspaceRegistry；#190 拥有知识检索页面演进 |
| 模板中心、通知中心 | 可关闭的开发中弹窗 | 不请求业务 API，不显示虚假未读数量、通知列表或成功结果 |
| 侧栏 | 显式收起 / 展开、窄屏自动收起 | 隐藏导航不进入键盘焦点序列，底部收起后焦点回到顶部展开按钮 |
| 重新同步 | 当前路径整页重载 | 明示未提交输入丢失，由现有 SessionGate 和工作区读取恢复；不制造队列已同步信号 |
| 客服详情入口 | 独立 SupportContextEntries，尚未挂载 | 转派、更多操作、订单、物流、联系客户、相似案例、建议动作；每项由宿主显式传入 available / developing / unavailable |
| 审批详情入口 | 独立 ApprovalContextEntries，尚未挂载 | 政策、日志、物流、资格明细只消费宿主查看回调；完整对话明确不可用，无跳转/请求扩权 |
| 审批队列辅助入口 | 独立 ApprovalQueueEntries，尚未挂载 | 更多筛选 / 导出为开发中，不改变真实筛选或生成导出文件 |

## 组件接线约定（不是新增后端权限契约）

`ContextEntry.available.onOpen` 只定位、打开当前授权投影内的既有内容；不得提交补偿、发送回复、执行建议动作或读取其他工单。开发中只表示确无能力；暂未接线不等于确无能力。

`projectionKey` 由宿主从当前主体、责任、投影版本导出，不在界面显示。取得可信投影前、重新同步中、Session 失效或撤权时必须传 `null`，旧入口及其弹层随之卸载；责任或投影替换时传新键，避免继承旧弹层。组件不自行查询 Session、判断角色、缓存业务投影或构造 API 路径。这只是组件层的卸载行为，不能代替 Spring 授权或宿主撤权处理。

已存在的能力不能在最终接线时降级占位：

- 客服 `HUMAN` 模式公开回复已存在；“联系客户”应定位既有 composer，非 HUMAN / 无责任时按真实状态禁用，不新增发送实现。
- 客服订单引用和公开沟通已有投影；订单 / 物流的展示范围以实际字段为准，不能由引用推导额外详情权限。
- 审批政策信息、资格校验、责任链、证据引用已存在；应定位/展示当前 APPROVAL_VIEW 内已有字段，不能一律标开发中，也不能读取完整客服对话。
- #164 拥有标准补偿；#170 拥有客服辅助 composer、建议动作和真实检索接入；本阶段不接线、不重写它们。

## 原型与复用证据

遵循 ADR 0004 的 `前端原型/stellogic-prototype-package/index.html` 中 `internalSidebar`、`internalTopbar`、客服详情和审批详情入口。保留深绿侧栏、浅色顶部工具区、分组快捷入口与紧凑操作；不搬入原型的虚假计数、假成功和未经授权的客户信息。

沿用 ADR 0002 的 Ant Design / React Router 栈，不增加依赖。参考 [Ant Design Layout](https://ant.design/components/layout/) 的受控 Sider、breakpoint、collapsedWidth 与自定义 trigger，以及 [Modal](https://ant.design/components/modal/) 的弹层关闭与焦点恢复。以显式原生链接/按钮保留清晰的导航和操作语义。

## 未运行的验证与剩余依赖

用户当前明确禁止所有测试、格式命令、类型检查、lint、构建、浏览器验收、Docker、模型下载/评测及完整门禁。本阶段只写源码、静态审查；没有申请/占用测试锁，不因 FREE 或依赖关闭自动运行。

- 单元源码：InternalShell.test.tsx；ContextEntries.test.tsx。覆盖授权菜单、真实路由、无请求开发中反馈、侧栏焦点、显式回调、projectionKey 清屏与审批完整对话不可用。
- Chromium 源码：`frontend/e2e/issue193.internal-shell.spec.ts`。合成 Session 下覆盖客服/审批身份、1440/360px、loading/error、键盘和读屏语义、重新同步后 Session 失效，并预留截图输出。没有执行，尚无截图或视觉通过证据；它不是后端真实授权验收。
- 未加入公共验收注册。实际已领取客服/有效审批租约、SSE 撤权、Session 更换、同步后新投影、#164/#170 接线后的增量验收与最终视觉核验待前置正式交付。
- 原始 blocked_by #163/#164/#166/#170 与全部验收标准仍保留。正式集成前重新同步 main，核对共享文件与迁移编号（本阶段没有迁移），完成增量双轴 CR，再等协调任务明确放行并按锁规则执行完整本地门禁。
- CI 关闭，不触发或等待 CI；不转 Ready、不合并、不关票。未来获准持锁验证结束须向协调任务发送 LOCK_RELEASED。

## 静态审查记录

- 状态：`CODE_READY_NO_TESTS`，仅本记录列明的隔离已实现范围。
- 对照：`git diff 2ca9d097da1f93d4cdf3eeef347c62cf51f0e058...c453352b1eb9a461fea0dfa01e8f2cfa8fd07f7c`。
- Standards：独立审查明确 **PASS**，0 项有效问题；复用既有路由与组件栈，符合文件归属，未发现有证据的规范或行为缺陷。
- Spec：独立审查明确 **PASS**，0 项有效问题；既有授权路由、无副作用占位、显式 props 入口和投影卸载符合本阶段范围。
- 静态阅读中修正了 loading 验收源码：既有 SystemState 的 `aria-busy` 位于 `main`，不是子级 status。该修正已包含在上述双轴审查范围。
- 两轴均未运行验证；后续提交若只更新本审查记录，不改变上述代码审查范围。不得将 PASS 解释为整票验收、真实权限集成或可合入状态。
