# #169 客户知识来源：隔离静态预开发

> 本文记录首轮 UI 阶段。后续在 main `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472` 上追加了纯引用结构校验/投影和[最小接入方案](issue-169-agent-retrieval-contract-proposal.md)；后文“没有服务端安全投影”描述首轮状态。新增纯模块仍不等于已完成授权、内容安全或真实检索接线。

## 范围与状态

本轮基线：`origin/main` = `efbdb8348dc9c12f259c69d9e8c16de5e4d3994c`（2026-08-31 获取）。
Issue #169 为 OPEN，启动时 assignees 为空，无已有 #169 开放 PR；协调任务
`01a043aa-d724-7353-b6c5-9266277846d6` 明确指定本任务唯一拥有客户来源 UI、客户回复投影及 #169/#170 共用 Agent 检索适配层。

本次只实现独立来源展示组件及测试源码，不接入 `App.tsx`、Agent 公共入口、Spring API 或 SSE。
没有检索适配层实现，没有自然回复编排，没有服务端安全投影。后面三项依赖未确定接缝，暂停。
#190 独占检索/编码/依赖/Compose/质量门；#165 独占补偿存储，#170 拥有客服辅助，#193 拥有内部壳，本轮不修改这些区域。

## PR203 固定只读契约（供 #170 共用）

只读参考 [PR203](https://github.com/Stellogic/customer-agent/pull/203)，固定提交
`3f3fb4c28676f846af65b1c59cb389359ed613d6`。未复制其实现，未修改该分支。
下列路径均相对于仓库根目录，且只描述该 SHA 的代码，不构成新批准的 Agent 接口。

| 固定 SHA 内路径 | 已明确的内容 |
| --- | --- |
| `backend/src/main/java/com/stellogic/customeragent/knowledge/KnowledgeRetrievalController.java` | 只有内部 `GET /api/internal/knowledge/search`，参数 `q` 和可选 `scope`，principal 来自 Authentication。 |
| `backend/src/main/java/com/stellogic/customeragent/knowledge/KnowledgeRetrievalModels.java` | `knowledge-hybrid-v1` 响应含 query/generation/revision/policy、两路候选和 results；hit 含 articleId/version/title/applicability/chunkId/sourceFile/startLine/endLine/snippet/score/lexicalScore/vectorScore，**无 updatedAt**。 |
| `backend/src/main/java/com/stellogic/customeragent/knowledge/KnowledgeRetrievalService.java` | 问题 1–200 字符；权限、发布状态、当前版本、范围、索引代次过滤；低于门槛或无向量候选时 results 为空。不能用 lexicalCandidates/vectorCandidates 绕过 results 拒答。 |
| `backend/src/main/java/com/stellogic/customeragent/knowledge/KnowledgeAccessPolicy.java` | 必须 INTERNAL 身份且具备 KNOWLEDGE_READ_ACCESS；返回 INTERNAL 及按角色允许的 SUPPORT/APPROVER，**不返回 CUSTOMER_PUBLIC**。向内部检索传 CUSTOMER_PUBLIC 不会授予客户范围。 |
| `backend/src/main/java/com/stellogic/customeragent/knowledge/KnowledgeCatalogExceptionHandler.java` | 检索不可用返回 503 + code/message，访问拒绝 403，非法请求 400；不能把内部错误详情直接展示给客户。 |

服务代码可见 INDEX_STALE、RETRIEVAL_UNAVAILABLE、FUSION_UNAVAILABLE；PR203 明确尚待校准并使用 CALIBRATION_REQUIRED。
这些是内部检索行为证据，**不是**已批准的客户失败协议。PR203 仍为 Draft，冻结质量未 PASS。

需协调明确后才能继续的接缝：

1. Agent 的服务身份、工单/运行代次授权及最小 query/scope 传递入口，不能冒用内部员工身份或直接放开内部 API。
2. 与命中 articleId/version 对应的可信 updatedAt、客户可见标题和 CUSTOMER_PUBLIC 范围。现有目录模型虽有 updatedAt，不能另调内部目录拼接来绕过权限。
3. 回复发送时版本/权限/范围复核、知识引用与结论对应关系、注入内容处置和业务事实冲突的受控记录。不能用前端过滤或关键词黑名单宣称完成这些校验。
4. 回复快照/SSE 中安全来源的归属与恢复方式；等待权威快照才能恢复展示，不能把旧缓存当作新的授权结果。

## 本轮可独立审阅的实现

- `frontend/src/components/CustomerKnowledgeSources.tsx`：输入是本地展示 props，仅有 title/updatedAt；状态为 ready/loading/empty/conflict/error/recovering。它不是网络 DTO，不决定检索，不接收或生成业务事实。
- 显式构造 Sources 的 title 内容（标题和时间），不转发对象额外属性、URL、片段、路径、内部 ID 或分数。标题和时间是纯文本。**不负责检查标题字符串本身的敏感性/注入，也不负责批准来源；未来调用方必须只传经过服务端引用校验的元数据。**
- 非 ready 状态不展示旧来源；ready 空数组展示无来源说明。组件无缓存、请求、计时器或本地伪造检索。recovering 只是外部驱动的展示状态，不实现断线重连。
- 配套 CSS 继承既有森林绿、浅色背景、细边框和字号变量；窄屏减少内边距、长标题允许换行。
- 测试源码仅含明确标注的合成展示 fixture，涵盖字段不转发、各状态撤下旧来源、恢复后新来源替换及空结果。

复用决策依据：项目已依赖 `@ant-design/x` 2.9.0，`App.tsx` 已使用 Sources。
[Sources 官方文档](https://x.ant.design/components/sources/) 支持 ReactNode title 且 url 可省略，不新增组件库或通用框架。
进一步只读核对 [固定 2.9.0 源码](https://github.com/ant-design/x/blob/2.9.0/packages/x/components/sources/Sources.tsx)，发现默认列表不渲染 description，因此把更新时间放在 title 节点中直接显示；标题区用原生按钮支持键盘展开/收起，复用 Sources 的 onExpand。
视觉参照 `前端原型/stellogic-prototype-package/index.html` 与现有 `frontend/src/styles.css` 的配色/卡片层级；原型中未发现完整客户知识引用状态设计，因此不宣称像素一致或已通过视觉验收。

## 验证与真实贡献边界

本轮只允许阅读、编辑、静态双轴 CR、提交和推送。**未运行**测试、格式检查/格式化、lint、类型检查、构建、Docker/Compose、模型、评测、浏览器验收或 check.ps1；未申请或占用测试门禁锁，未触发 CI。
测试源码不等于测试通过，响应式 CSS 不等于窄屏实测，DOM 字段映射不等于服务端安全保证。

本轮贡献可表述为：依据固定检索契约识别客户授权和来源元数据缺口，编写不接线的客户来源展示及状态切换测试源码，并保留集成阻塞记录。
不得表述为真实 RAG 已上线、质量门通过、已防住 prompt injection、回复已经有知识依据或独立实现检索引擎。

真实接入及正式交付仍需 #190 冻结质量 PASS、完整本地门禁 PASS、合入并关票，再由协调明确放行。
届时同步最新 main/已合入接口、补齐安全投影和回复编排，按交付窗口完成运行验证及增量双轴确认。
本轮即使静态双轴 PASS，也只报告限定范围的 `CODE_READY_NO_TESTS`，不合入、不关闭 #169。

## 本轮静态审查记录

2026-08-31，依仓库 code-review 技能启动相互独立的 Standards 与 Spec 子审查。
用户要求审查完成后提交，因此固定比较为 `git diff --cached efbdb8348dc9c12f259c69d9e8c16de5e4d3994c`，而不是先创建实现提交。
第一轮双轴 PASS 后，只读核对组件库固定版本源码发现默认列表不渲染 description，修复时间显示并补上键盘展开按钮；不沿用前轮结论。
第二轮重新审查全部四文件（当时 272 新增行）：Standards **PASS，0 项发现**；Spec **PASS，0 项发现**。
本段仅补记审查结果，未改变被审阅实现。两轮均为静态源码审查，没有执行测试或工具检查。
