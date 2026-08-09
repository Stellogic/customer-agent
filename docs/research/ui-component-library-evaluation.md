# 首个纵向切片的 React UI 组件库选型

> 调研日期：2026-08-09
> 对应决策票：[GitHub Issue #10](https://github.com/Stellogic/customer-agent/issues/10)
> 既有版本决议：[GitHub Issue #9](https://github.com/Stellogic/customer-agent/issues/9) / [`core-version-compatibility.md`](./core-version-compatibility.md)
> 证据范围：仅使用 Ant Design、Ant Design X 官方文档与官方 GitHub 仓库；版本兼容结论另引用本仓库已关闭的 Issue #9。
> 结论边界：本文只回答 UI 组件复用和引入边界，没有创建 React 工程、安装依赖或做运行验证。

## 结论

采用 **`antd` + `@ant-design/x` 的受限组合**，但让两个界面壳保持明确分离：

1. `CUSTOMER_PUBLIC` 使用帮助中心式客户界面，以 `@ant-design/x` 的 `Bubble`、`Sender`、`Welcome`、`Prompts`、`Actions` 等**呈现组件**降低聊天 UI 开发量；页面外壳、工单公开进度和结果卡片使用 `antd`。
2. `SUPPORT_WORKBENCH` 与 `APPROVAL_VIEW` 共用 C 风格内部工作台外壳，使用 `antd` 的布局、导航、表格、详情、表单、状态和反馈组件；根据服务端返回的权限装配路由和菜单。
3. 首版**不引入 `@ant-design/x-sdk`，不使用 `Think` / `ThoughtChain`，不让浏览器直连模型或 LangGraph**。浏览器只调用项目后端公开的客户/内部 API，并只渲染该角色允许看到的投影。
4. 候选依赖基线为 `antd@6.5.4`、`@ant-design/x@2.9.0`，与 Issue #9 的 React `19.2.7` 候选基线在声明的 peer dependency 上相容；仍须通过真实安装、类型检查和生产构建后才能升级为“已验证基线”。

这不是把客户和内部人员塞进同一个后台，而是**共用设计系统与基础组件，不共用页面信息架构**。

## 1. 为什么是两个界面壳

| 界面壳 | 面向角色 | 首个纵向切片的核心页面 | 适合的组件来源 |
|---|---|---|---|
| 客户帮助中心 | `CUSTOMER_PUBLIC` | 帮助入口、对话、补充信息、公开进度、最终结果 | `@ant-design/x` 聊天呈现组件 + 少量 `antd` |
| 内部工作台 | `SUPPORT_WORKBENCH`、`APPROVAL_VIEW` | 工单队列、工单详情、补偿提案核对、批准/拒绝 | `antd` |

客户的目标是“描述问题并知道下一步”，内部人员的目标是“从队列中定位任务、核对证据并执行受控动作”。即使复用颜色、按钮、表单和状态标签，也不应复用同一套侧栏和信息密度。

实现时可保留一个 React 应用和一个依赖树，但至少分成两个 route shell，例如：

```text
/help/**            -> CustomerShell
/workbench/support  -> InternalShell + SUPPORT 权限
/workbench/approval -> InternalShell + APPROVAL 权限
```

路由和菜单裁剪只改善用户体验，**不是授权边界**；Spring 仍必须在每个查询和命令上校验身份、角色、资源范围和动作权限。组件库本身不提供业务授权。

## 2. 客户帮助中心：只复用 Ant Design X 的 UI 层

### 2.1 可直接降低成本的组件

Ant Design X 官方把 `@ant-design/x` 定位为 React 的 AI 界面组件库，并列出聊天场景所需的原子组件：[Introduction](https://x.ant.design/components/introduce/) / [Components Overview](https://x.ant.design/components/overview/)。对本项目首个切片，建议只采用：

| 客户能力 | 建议组件 | 使用方式 |
|---|---|---|
| 客户与客服 Agent 的消息流 | `Bubble.List`、`Bubble` | 渲染客户消息、公开回复、系统状态消息；官方说明 `Bubble` 用于聊天场景，并支持列表与 streaming 状态。[Bubble](https://x.ant.design/components/bubble/) |
| 问题输入与发送 | `Sender` | 复用输入、发送、loading/disabled 和可选附件槽位；业务校验、幂等键和提交结果仍由项目代码处理。[Sender](https://x.ant.design/components/sender/) |
| 首次进入的帮助入口 | `Welcome`、`Prompts`、`Suggestion` | 提供“物流未收到”“补充订单号”等受控入口，减少纯自由文本的不确定性。[Components Overview](https://x.ant.design/components/overview/) |
| 消息后的客户动作 | `Actions` | 承载复制、反馈、重新发送等非关键动作；补偿批准等内部命令不能放到客户侧。[Components Overview](https://x.ant.design/components/overview/) |
| 多个历史工单/会话（非首切片必需） | `Conversations` | 只有确认需要客户查看多工单历史时再引入，首切片可省略。[Components Overview](https://x.ant.design/components/overview/) |

页面不必模仿 ChatGPT 主应用的全屏对话。更贴近用户参考图的形态是：顶部为帮助中心标题/常见入口，中间或右侧为主要聊天区，同时把“工单已创建、等待补充、等待审批、结果已确认”作为客户可理解的公开状态呈现。`antd` 的 `Steps`、`Result`、`Alert`、`Card`、`Tag` 等可以补齐这些非聊天信息；官方组件总览显示 `antd` 已覆盖布局、导航、录入、数据展示和反馈类别。[Ant Design Components Overview](https://ant.design/components/overview/)

### 2.2 明确不采用的 Ant Design X 能力

- **不渲染 `ThoughtChain` 或 `Think`。** 官方将 `ThoughtChain` 描述为追踪 Agent、Action 和 Tool 调用链，并明确列出调试复杂 Agent 系统的用途；这正是内部执行细节，不属于客户公开信息。[ThoughtChain](https://x.ant.design/components/thought-chain/)
- **首版不引入 `@ant-design/x-sdk`。** 官方 SDK 能管理对话数据并提供 OpenAI/DeepSeek Provider，也支持自定义 Provider；但本项目已有 Spring + LangGraph 边界，复用 SDK 会额外引入一套请求/会话抽象。[useXChat](https://x.ant.design/x-sdks/use-x-chat/) / [Custom Chat Provider](https://x.ant.design/x-sdks/chat-provider-custom/)
- **浏览器绝不持有模型密钥或直连模型。** Ant Design X 的 OpenAI 集成文档明确提示浏览器模式需要 `dangerouslyAllowBrowser` 且有安全风险；本项目不采用该模式。[OpenAI integration](https://x.ant.design/docs/react/model-use-openai/)
- **不把 LangGraph 原始事件、tool payload、模型 reasoning 或审批草稿映射成聊天消息。** 客户端只消费后端生成的 `CUSTOMER_PUBLIC` 投影，例如公开回复、澄清问题、公开进度和最终结果。

如果后续确实需要 SDK 的消息状态管理，也只能用自定义 Provider 适配项目自己的 Spring API。官方文档支持把自定义服务响应转换为 `useXChat` 可消费的消息，因此没有理由让浏览器绕过项目后端。[Custom Chat Provider](https://x.ant.design/x-sdks/chat-provider-custom/)

## 3. 客服与审批：用 Ant Design 组成同一内部工作台

Ant Design 官方定位是企业级 React UI 库，提供 TypeScript 类型、国际化和主题定制；其组件总览覆盖本工作台需要的布局、导航、数据录入、数据展示和反馈能力。[官方仓库 README](https://github.com/ant-design/ant-design#ant-design) / [Components Overview](https://ant.design/components/overview/)

| 内部工作台能力 | 建议组件 | 边界 |
|---|---|---|
| C 风格应用骨架 | `Layout`、`Sider`、`Menu`、`Breadcrumb`、`Tabs` | `Layout` 官方支持 Header/Sider/Content 和响应式、可折叠侧栏，足够搭建内部壳。[Layout](https://ant.design/components/layout/) |
| 工单/审批队列 | `Table`、`Pagination`、`Input.Search`、`Select`、`Tag`、`Badge` | `Table` 官方支持结构化数据、排序、搜索、分页和过滤，满足 MVP 队列。[Table](https://ant.design/components/table/) |
| 工单与提案核对 | `Descriptions`、`Card`、`Timeline`、`Steps`、`Alert` | 展示 Spring 权威快照、公开事实、补偿金额与审计摘要；不展示模型私有推理。[Descriptions](https://ant.design/components/descriptions/) / [Steps](https://ant.design/components/steps/) |
| 批准/拒绝 | `Form`、`Radio`、`Input.TextArea`、`Modal`、`Popconfirm`、`Button` | 表单校验用于即时反馈；审批资格、租约、状态转换和拒绝原因仍由 Spring 强制校验。[Form](https://ant.design/components/form/) |
| 断线、空态与最终反馈 | `Alert`、`Result`、`Empty`、`Spin`、`notification` | 明确区分加载、断线、未知结果、失败和完成，不能把“按钮已点击”当成执行成功。[Result](https://ant.design/components/result/) |

`SUPPORT_WORKBENCH` 和 `APPROVAL_VIEW` 可共用 `InternalShell`、状态组件和只读事实卡片，但页面注册应按权限拆开：客服不应因为菜单被隐藏就能访问审批路由，审批人也不应自动获得完整客服队列。后端返回允许的 capability/permission，前端据此构造可见菜单和路由；API 再独立执行相同授权。

首版不建议直接采用 Ant Design Pro/完整后台模板。Issue #10 只需要一条客户调查与补偿审批纵向切片，完整脚手架会同时引入更多页面约定、数据流和工程选择；`antd` 的 `Layout`、`Table`、`Form` 已覆盖当前必需能力。若后续内部页面数量明显增长，再单独评估 Pro Components，而不是在此票顺带决定。

## 4. 版本、许可证与安装边界

### 4.1 候选版本

| 包 | 候选版本 | 官方证据 | 与项目基线的关系 |
|---|---:|---|---|
| `antd` | `6.5.4` | 官方 changelog 标记 6.5.4 于 2026-08-07 发布；对应 tag 的 `package.json` 声明 React/React DOM `>=18.0.0`。[Changelog](https://ant.design/changelog/) / [6.5.4 package.json](https://github.com/ant-design/ant-design/blob/6.5.4/package.json) | React 19.2.7 满足 peer range；项目组合仍需实测。 |
| `@ant-design/x` | `2.9.0` | 官方 changelog 标记 2.9.0 于 2026-07-23 发布；包声明 `antd ^6.1.1`、React/React DOM `>=18.0.0`。[Changelog](https://x.ant.design/changelog/) / [2.9.0 package.json](https://github.com/ant-design/x/blob/2.9.0/packages/x/package.json) | `antd 6.5.4` 与 React 19.2.7 均落入声明区间；其仓库开发环境使用 TypeScript 5.9.x，因此 TypeScript 6.0.3 不能只凭 peer range 宣称已验证。 |

两者的包元数据均声明 **MIT**；许可证允许使用、修改、分发和再许可，但分发时需保留版权及许可声明。[Ant Design LICENSE](https://github.com/ant-design/ant-design/blob/master/LICENSE) / [Ant Design X LICENSE](https://github.com/ant-design/x/blob/main/packages/x/LICENSE)

### 4.2 降低成本同时控制依赖面

- 让 `@ant-design/x` 和内部工作台共享同一 `antd` 6.x 实例及主题 token，不自行重写一套按钮、输入、弹窗和状态颜色。
- 只从包入口导入实际使用的组件。`@ant-design/x` 官方说明 ESM 默认支持 tree shaking，包元数据也声明 `sideEffects: false`；但它仍包含 `mermaid`、代码高亮等直接依赖，所以必须用生产构建报告验证实际 bundle，而不能只凭“按需引入”假设体积很小。[Introduction](https://x.ant.design/components/introduce/) / [package.json](https://github.com/ant-design/x/blob/main/packages/x/package.json)
- 客户 shell 可做 route-level lazy loading，避免内部用户加载聊天组件；内部 shell 同理不加载客户聊天页面。
- 固定精确版本并提交 lockfile。Ant Design 与 Ant Design X 均按语义化版本发布，但 minor 会增加能力；MVP 阶段不要使用宽泛的 `latest` 或无上界范围。[Ant Design changelog](https://ant.design/changelog/) / [Ant Design X changelog](https://x.ant.design/changelog/)
- 不为“减少代码”引入 X Card、动态 Agent UI 或完整 X SDK；这些能力超出首个纵向切片，也会扩大可渲染协议和安全审计面。

## 5. 实施票必须验证的最小门槛

1. 在 Issue #9 的 Node 24、React 19.2.7、TypeScript 6.0.3、Vite 8 候选基线上安装精确版本并提交 lockfile。
2. 执行 `tsc --noEmit`、单元测试和生产构建，证明 `antd 6.5.4`、`@ant-design/x 2.9.0` 与当前工具链真实兼容。
3. 检查生产 bundle：客户入口是否只加载所用 X 组件，内部入口是否没有捆入聊天/Markdown/Mermaid 代码。
4. 做键盘、焦点、窄屏和屏幕阅读器冒烟测试。组件提供 responsive/semantic DOM 能力不等于项目页面自动无障碍。
5. 做三类权限负向测试：客户不能访问内部路由/API；客服不能执行审批；审批人不能越权查看或操作非分配范围。
6. 检查浏览器网络与构建产物：不存在模型密钥、LangGraph 地址、原始 Agent 事件、tool payload、reasoning 或内部审批草稿。
7. 验证断线和未知结果：前端重新同步 Spring 权威状态，且重复提交不会造成第二次补偿。

## 6. 可写回 Issue #10 的决议摘要

> 客户端采用帮助中心式独立界面，聊天区域使用 Ant Design X 的 Bubble/Sender 等纯 UI 组件，并展示客户可理解的工单公开进度；客服与审批人采用共享 C 风格的 Ant Design 内部工作台壳，按服务端权限分别注册 SUPPORT 与 APPROVAL 页面。组件与设计 token 可以复用，但两类角色不共用信息架构。首版使用 `antd@6.5.4` + `@ant-design/x@2.9.0` 候选组合，不引入 X SDK、Think/ThoughtChain，不在浏览器直连模型或暴露 LangGraph 原始流；最终授权与权威状态均由 Spring 执行。版本组合必须经最小 React 构建后才视为项目已验证基线。
