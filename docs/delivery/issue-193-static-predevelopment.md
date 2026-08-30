# #193 内部壳与非核心入口：隔离静态预开发

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

待独立 Standards / Spec 双轴审查；两轴均只评价本记录列明的已实现范围，不能将其 PASS 解释为整票验收完成。
