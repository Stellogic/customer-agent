# #170 客服辅助独立组件：静态预开发记录

当前状态：**CODE_READY_NO_TESTS（rag-layered-v2 新增静态内容）**，增量 Standards / Spec 双 CR 均 PASS，未完成整票。旧提交 `494dbff` 在已结束窗口内完成过 25 项聚焦测试及目标格式、ESLint、前端类型检查，原日志/源码哈希保留；这些证据不覆盖本轮修改。当前无运行或集成许可，#190 持窗口；不查询锁、不运行检查/模型、不合入或关票。CI 关闭。

2026-08-31 静态续办：已同步 `origin/main@c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`，保留首轮 `8bd3ef6`，assignment/请求绑定增量在 `1783b36` 完成完整 #170 差异双轴静态审查，Standards / Spec 均 PASS。该阶段全部运行验证为 NOT_RUN，随后聚焦验证见文末。

## 归属与基线

- 委派协调任务：`01a043aa-d724-7353-b6c5-9266277846d6`；本任务只处理 #170。
- 启动时远端 Issue #170 OPEN、无 assignee，无重复 #170 open PR；由协调任务明确本任务拥有独立客服辅助组件、草稿与权限边界。没有抢占其他任务文件。
- 起点：已 fetch 的 `origin/main@efbdb8348dc9c12f259c69d9e8c16de5e4d3994c`。
- 只读参考：PR #203 `3f3fb4c28676f846af65b1c59cb389359ed613d6`；PR #205 `04a522065ee00726e3c87515715d85b951687d9c`。
- #169 唯一拥有共用 Agent 检索适配；#190 拥有检索引擎、依赖和质量门；#193 拥有 InternalShell、非核心入口与自身 CSS；#165 拥有补偿存储。本票没有修改这些区域。

## 已实现的独立范围

首轮新增 `frontend/src/components/support-assistance/` 下的 React 组件、专属 CSS、自有纯状态、测试源码；本轮另增 #170 专用纯回答计数及测试源码，见文末。本组件未挂载到产品；无网络、模型、共享状态或存储调用，没有产品假检索。

- 按原型客服详情的 AI 摘要、建议、引用和 composer 信息层次布局，沿用森林绿、浅底与卡片边界；CSS 包含窄屏布局，尚无截图或视觉通过证据。
- 工单总结、知识检索、政策查询、回复草稿四个入口只提示开发中，不生成请求 ID、不发起 Agent 请求。纯状态接受调用方提供的稳定请求身份，实际请求记录/摘要/编排仍未实现。
- 只渲染显式展示字段；支持 idle/loading/检索无匹配 empty、生成资料不足 insufficient，以及知识冲突、索引/检索/格式/请求/模型错误（Embedding 与回复生成区分）；建议仅文本展示。引用只显示标题、版本、内部标识、更新时间、行号、片段和范围，不渲染原始载荷、prompt 或思维链对象。
- `AssistanceView` 是组件内部展示需求，不是 HTTP 或 #169 的接口，不得作为共享适配替代契约。其字段不表示原始模型文本已经过后端投影校验；未来宿主只能传经 Spring 授权裁剪后的展示内容。
- 续办将不透明 `projectionKey` 改为自有 `SupportAssignment(sessionKey,ticketId,assignmentId)`；`sessionKey` 仅为客户端主体代次，不是访问令牌。宿主仅在当前负责客服、HUMAN 且权威详情有效时授权；撤权、主体切换、断线或重同步撤销 assignment。组件卸载私有草稿，键变化重建状态。纯状态只接受当前 assignment、requestId、辅助类型匹配的结果，旧 assignment 的迟到拒绝不会清新领取；当前 assignment 的拒绝即使源自旧请求仍清屏。
- 辅助草稿不自动插入；替换已有编辑需要确认。编辑会撤销审阅勾选，超过现有人工回复 2000 字限制不截断插入。辅助失败保留当前人工编辑。
- `onReviewDraft` 仅作为 UI 文本移交回调：把审阅文本填入现有人工发送区，不能在回调里发送。没有回调时按钮不可用。工作台挂载与该回调接线均未实现。既有人工发送正在进行或结果未确认时，宿主必须传 null，避免覆盖其待确认请求。

## 依据与限制

读取了仓库 implement、code-review 技能、AGENTS、Issue 正文、ADR 0004，以及原型 `前端原型/stellogic-prototype-package/index.html` 的 `renderSupportTicket`。原型中建议的“执行/转审批”与 #170 无副作用要求冲突，本组件只保留建议文本，不开放业务动作。

复用现有 React/Testing Library，无新依赖。状态隔离依据 [React 官方状态保留与重置文档](https://react.dev/learn/preserving-and-resetting-state)：授权键用于重建组件状态；无需另造缓存、全局状态机或通用编排框架。

PR #203 的内部检索模型包含候选分数、源文件等，不是 Agent 授权投影；不调用其内部 principal API。PR #205 的 ContextEntries 由宿主提供 projectionKey，只读参考组件边界，不复制其实现。

现有 `SupportWorkbench.tsx` 的人工回复限制为 2000 字，现有请求/结果查询负责回复幂等与不确定状态。本轮不复制这一链路，也不宣称本组件已实现后端鉴权、撤权竞态或发送幂等。客户端隐藏内容不等于服务端撤销访问权。

## 测试源码与待集成清单

组件测试包含：无网络请求、字段展示/纯文本、手动插入与审阅、替换确认、新结果不覆盖编辑、撤权后迟到结果、身份/工单/责任切换清屏、失败不影响人工编辑、移交不可用及空白/超长草稿。旧版与纯状态合计 25 项曾在 Node24 下通过；本轮新增/修改测试均 NOT_RUN，旧结果不是当前版本、浏览器视觉或真实后端授权证据。

尚待：依已收敛最小契约实现独立编排与后端 assignment 授权（HUMAN 不使用或复活 Agent generation）；限制输入为当前工单授权投影、近期公开消息、可重建摘要、调查事实及允许知识范围；建立稳定请求记录、参数摘要、结果访问/引用复核；接入真实检索；挂载工作台并复用人工发送权限与幂等路径；运行后端/组件/桌面及窄屏验收。消费者约定见 [HUMAN 辅助最小消费者契约](../implementation/issue-170-human-assistance-consumer-contract.md)。

#190 rag-layered-v2 检索层质量实测 PASS、完整门禁 PASS、PR 合入 main 且 Issue 关闭之前不能真实消费或正式交付。#170 自身承担回答层拒答 precision≥.90/recall≥.85 和结构/引用/语义分项报告；之后仍需协调明确放行、同步最新 main、增量双 CR 和本票完整门禁。锁 FREE 不自动放行，回答层不反向阻塞 #190。

## 贡献证据口径

本轮贡献为独立 UI、草稿编辑、客户端投影隔离、测试源码及限定模块聚焦验证；不称已完成 Agent 检索、完整后端授权或生产能力。合成 fixture 仅在测试源码，不是检索质量数据。实际模型调用为零，测试执行时长不是产品性能指标。

## 首轮双轴静态审查（8bd3ef6）

2026-08-31，按仓库 code-review 技能使用两位独立子代理并行审查。用户要求 PASS 后再提交，所以固定比较对象为 `git diff --cached efbdb8348dc9c12f259c69d9e8c16de5e4d3994c` 的四个新增文件，而非提前创建提交；HEAD 当时仍为基线。

- Standards：PASS，0 项问题。符合中文产物、依赖复用、不过度设计、原型及“开发中不伪造成功”要求，没有需要阻塞的代码异味。
- Spec：PASS，0 项有效阻塞发现。独立草稿交互、客户端投影隔离及失效状态在当前授权范围内；无替代适配、检索/HTTP 编排、业务副作用或共享文件修改。
- 两轴均明确仅限静态预开发范围，未运行任何检查，不能据此认定服务端授权、检索质量、视觉或整票验收通过。无修复项；审查后的增量仅为本段记录及顶部状态。

## 续办双轴静态审查

2026-08-31，两位独立代理完整审查 `git diff --cached c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`：七个自有文件，含首轮组件和本轮纯状态、测试源码、消费者说明。Standards PASS / Spec PASS，各 0 项有效发现，没有需要修复的代码问题。确认当前 assignment 拒绝与普通失败分开、旧请求结果/旧 assignment 拒绝隔离、引用展示和两类模型失败符合本轮限定范围。

只读参考 #169 共用纯解析固定提交 `a248aca70405c53592c4df6e624bd84d60337806`；不复制适配、DTO 或 HTTP 解析，不把其字段校验当浏览器授权。审查后仅追加本段、顶部状态和固定引用 SHA，文档增量另交两轴补充复核。未运行任何测试或检查；不修改 #190 冻结 c5、不抢独立验证窗口、不合入或关票。

## 获准后的独立模块聚焦验证（2026-08-31）

以下是 `494dbff` 之前的历史运行记录，不是 rag-layered-v2 新增代码的验证结果。

协调明确转述用户解除早期测试禁令，并把共享窗口分配给 #170；仅允许自有测试和必要检查、普通修复与双 CR，不允许 HTTP/LLM、工作台挂载、全栈、完整门禁或合入。先完整读取锁规则和脚本，宿主正常审批通过、只读状态 FREE 后通过现有 `Enter-TestGateLock` 获取同一仓库共享互斥量，未改锁身份或令牌规则。

| 运行 | 真实结果 |
| --- | --- |
| `issue170-focused-20260831-a` | PATH 为 Node 22.15.0/npm 10.9.2；`npm ci --ignore-scripts --no-audit --no-fund` 安装锁文件依赖，有项目 engine 警告。25 测试、ESLint、tsc 通过，但目标 Prettier 检查 5 文件失败。版本不符，**不作为最终规范环境证据**。 |
| `issue170-focused-20260831-b` | 改当前进程 PATH 使用现有 bundled Node **24.19.0**，与 #169 核对同一路径；没有修改全局配置/共享缓存。Prettier 只格式化自有 5 文件后检查 PASS；Vitest **2 文件、25 测试 PASS**；目标 ESLint PASS；前端 `tsc --noEmit` PASS，四项退出码均 0。 |

原始 transcript：[首轮退出码/锁记录](../evidence/issue-170-focused-a.txt)、[Node24 聚焦退出码与源码 SHA256](../evidence/issue-170-focused-b.txt)。PowerShell transcript 未捕获原生命令 stdout，实际终端工具返回中的 engine 警告、格式失败、Vitest 25 项结果另存为[原生输出摘录](../evidence/issue-170-native-output.txt)，明确来源而非补造报告。日志 base 为 `c19a7eb`，HEAD 为 `1783b36`；第二轮验证对象是该 HEAD **加五文件格式修订后的工作树**，不是声称未修改的旧提交通过。日志保存五个最终源码的 SHA256，之后仅更新文档/日志不改变被验证源码。

实际命令在 `frontend` 下：`prettier --write/--check src/components/support-assistance`（write 仅第二轮）、`vitest run src/components/support-assistance/SupportAssistancePanel.test.tsx src/components/support-assistance/supportAssistanceState.test.ts`、`eslint src/components/support-assistance --max-warnings 0`、`tsc --noEmit`。使用现有 node_modules 的 `.cmd` 工具，Node 由该进程 PATH 指向 `C:\Users\lizhuo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe`；安装步骤使用 Node22 的事实保留，不把它改写成 Node24 安装。

两次运行均在 finally 调用 `Exit-TestGateLock` 并主动报告 **LOCK_RELEASED**；第二轮释放后只读状态为 FREE。进入格式差异审查/文档阶段不持锁。仅有格式修复，没有业务逻辑修复、依赖文件变更或新增共用 DTO。

聚焦验证后增量双轴审查：两位独立代理完整阅读 `git diff --cached 1783b36b71de6c8785f517d7c6b1b276c012b5e8` 的十个文件（五个格式修订源码、两份文档、三份证据），**Standards PASS / Spec PASS，均 0 项有效发现**。源码 SHA256 只读回核与 B 轮记录一致；审查不重复运行检查或持锁。后续仅补记本段结果，不改变被测源码。

仍未运行/未完成：浏览器窄屏视觉、构建、全栈、后端鉴权竞态、真实检索/LLM、#190 质量门及本票完整门禁。#190 冻结 c5 和其他票文件不变；PR #209 保持 Draft，Issue #170 保持 OPEN，不能以聚焦通过替代整票交付。

## rag-layered-v2 静态修订（2026-08-31）

读取正式 #149/#170/#190 新正文并与 #169 直接确认：检索只表达 `CANDIDATES_AVAILABLE`/`NO_MATCH`，非充分性判断；HUMAN 同次 DeepSeek 判断并生成，不默认独立判断调用、不设单条引文 24 字符限制。细节见 [本路径协议](../implementation/issue-170-rag-layered-v2.md)。

本轮仅改自有 UI/纯状态和测试源码，新增 #170 专用的纯回答计数函数及测试；没有 HTTP/LLM/模型 prompt 接线、共享适配、工作台挂载、依赖改动或通用评测框架。计数保留全样本分母和故障/未评估，结构/引用/语义分项，不输出整体验收 PASS。新内容均 NOT_RUN，真实执行协议与预算仍待冻结，不读取验收错题调参，历史失败/旧模型合同/资产不改。

本轮双 CR 固定比较 `git diff --cached 494dbff899f220b6235b4a8be3ab1c0e1143afea` 的九个自有文件。Standards 首轮 PASS；Spec 首轮发现一项 P2：无答案标签会把语义失败或尚未复核的不足输出误计为正确拒答。已修复为正确分子同时要求独立语义校验通过，错误/未复核不足仍保留 precision 分母，完整无答案集合仍保留 recall 分母；新增 False/None 两种合成测试源码，未运行。修复后 **Standards PASS / Spec PASS，剩余各 0 项有效发现**。本段仅记录真实审查过程，不改变源码；未用静态复核代替测试或实际模型质量。

只读新契约引用为 #169 `4337d89fc01d4f993395a2cf2c09b05cdb49768d`、#190 `802a34310d4c01991ea480082a6025372da016a8`；均非已获集成许可。旧证据文件原样保留。
