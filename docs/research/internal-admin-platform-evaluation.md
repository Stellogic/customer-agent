# 统一内部后台管理系统与鉴权方案调研

> 调研日期：2026-08-16
>
> 目标：为客服与审批人共用一个 `InternalShell`、统一登录并按服务端权限访问不同页面，评估可复用或可直接采用的成熟开源后台方案。
>
> 证据范围：仓库决策时点基线 `77f165219c82afd94ad0bc70e27e4dcd5762c31c`（2026-08-16）以及候选项目、Spring Security、React Router 的官方文档、官方 GitHub 仓库、官方许可证。第 2 节描述的是该历史快照，不代表本文入库时的最新实现；后续 Issue #72–#79 已按接受的决策完成登录、Principal、双 Shell、参与者隔离与旧入口收缩。
>
> 验证边界：决策时完成的是静态源码核对和一手资料调研；当时没有安装候选依赖、迁移产品代码、运行兼容性或 bundle 实验，因此文中的“可兼容”只代表当时的官方声明。后续实现与验收证据应以对应 Issue、交付文档和当前锁文件为准。

## 1. 结论摘要

1. **产品形态应改为一个统一内部后台，而不是两个彼此孤立的入口。** 推荐路由形态是 `/internal/**` 下共用一个 `InternalShell`、一个登录态读取流程、一个用户菜单和退出入口；客服与审批页面作为 shell 内的权限页面。这个方向也符合仓库既有 UI 决议中“`SUPPORT_WORKBENCH` 与 `APPROVAL_VIEW` 共用内部工作台外壳”的约束；在决策时点，实现尚未完成该决议。[既有 UI 选型结论](./ui-component-library-evaluation.md#3-客服与审批用-ant-design-组成同一内部工作台)
2. **首选不是整仓替换，而是采用 Ant Design Pro 的可复用层。** 建议在当前 Vite 应用里引入 React Router 7、`antd` 6 和 `@ant-design/pro-components` 的 `ProLayout`/页面组件，借鉴 Ant Design Pro 的 shell、菜单、403/404、账号区和路由组织；不要直接把现有前端替换成完整 Ant Design Pro/Umi Max 模板。官方模板确实原生使用 React 19.2.7、Ant Design 6、Pro Components 和 Umi Max 4，但同时带入图表、AI UI、React Query、Umi 工程体系等广泛依赖，整仓采用会把“统一后台”扩大成构建系统迁移。[Ant Design Pro 仓库](https://github.com/ant-design/ant-design-pro) / [当前 package.json](https://github.com/ant-design/ant-design-pro/blob/master/package.json)
3. **若后续内部页面快速扩展为大量 CRUD，refine 是最值得做第二阶段原型的完整框架候选。** refine v5 官方支持 React 18/19，可继续使用 React Router，并有 Ant Design 适配、`authProvider`、`accessControlProvider`、按资源菜单和按钮控制；但它要求 TanStack Query v5，并增加 resource/provider 抽象。当前工单调查、审批租约、SSE 权威快照并不是普通 CRUD，立即全面迁入 refine 的收益尚未被证明。[refine v5 迁移说明](https://refine.dev/core/docs/migration-guide/4x-to-5x/) / [路由设计](https://refine.dev/core/docs/guides-concepts/routing/)
4. **不建议直接采用 react-admin 作为本项目统一后台。** 它成熟、MIT、明确支持 React 19，并且鉴权与资源授权能力完整；但默认技术栈是 Material UI，核心抽象围绕 REST/GraphQL 资源 CRUD。为迁入现有高度定制的队列、租约、SSE 与审批流程，需要自定义 `dataProvider`、自定义路由、布局和权限适配，同时放弃已确认的 Ant Design 方向，迁移成本和视觉体系冲突高于收益。[react-admin 官方仓库](https://github.com/marmelab/react-admin) / [当前包元数据](https://github.com/marmelab/react-admin/blob/master/packages/react-admin/package.json)
5. **真正的安全边界必须在 Spring。** 前端菜单、路由 guard、Ant Design Pro `access`、react-admin `canAccess` 或 refine `<CanAccess>` 都只用于减少误入和隐藏无权 UI；Spring Security 必须对每个 API 做请求级授权，并在业务方法对工单分配、审批租约、资源归属和动作做资源级授权。[Spring 请求授权](https://docs.spring.io/spring-security/reference/7.0/servlet/authorization/authorize-http-requests.html) / [Spring 方法授权](https://docs.spring.io/spring-security/reference/servlet/authorization/method-security.html)

## 2. 决策时点的仓库事实与差距

### 2.1 当时的前端

- 前端生产依赖当时只有 `react@19.2.7` 和 `react-dom@19.2.7`，没有 React Router、UI 组件库、后台框架或统一鉴权客户端。[决策时点 `frontend/package.json`](https://github.com/Stellogic/customer-agent/blob/77f165219c82afd94ad0bc70e27e4dcd5762c31c/frontend/package.json)
- 根组件当时通过 `globalThis.location.pathname === "/support" | "/approver"` 手工选择两个页面；两条路由分别请求旧演示会话端点，各自显示“无权访问”状态，没有共享 shell、嵌套路由、统一菜单、统一 401/403 处理或退出流程。[决策时点 `RootApplication.tsx`](https://github.com/Stellogic/customer-agent/blob/77f165219c82afd94ad0bc70e27e4dcd5762c31c/frontend/src/RootApplication.tsx)
- 客服与审批页当时已经使用同源 `fetch` 和 `credentials: "same-origin"`，这为采用 Spring 托管的 HttpOnly 会话保留了自然迁移路径；但前端仍把固定 demo 身份枚举写在类型守卫里。[决策时点 `RootApplication.tsx`](https://github.com/Stellogic/customer-agent/blob/77f165219c82afd94ad0bc70e27e4dcd5762c31c/frontend/src/RootApplication.tsx)

### 2.2 当时的后端

- 后端当时使用 Spring Boot 4.1.0，但依赖中没有 `spring-boot-starter-security`、OAuth2 Client 或 Resource Server；因此不能把该快照描述为 Spring Security 鉴权。[决策时点 `backend/build.gradle.kts`](https://github.com/Stellogic/customer-agent/blob/77f165219c82afd94ad0bc70e27e4dcd5762c31c/backend/build.gradle.kts)
- 旧演示身份入口当时只在 `local-demo` profile 生效，通过值为固定 demo ID 的 HttpOnly、SameSite=Strict Cookie 创建合成身份；它适合作为演示夹具，不是账号密码登录、OIDC 或通用会话实现。[决策时点 `SyntheticIdentityController.java`](https://github.com/Stellogic/customer-agent/blob/77f165219c82afd94ad0bc70e27e4dcd5762c31c/backend/src/main/java/com/stellogic/customeragent/identity/SyntheticIdentityController.java)
- 审批 API 当时仍主要信任旧 `X-Synthetic-*` 人工身份头，并由控制器手工检查固定审批人集合；部分客服 API 同样支持合成请求头。这不是可上线的统一 Principal/GrantedAuthority 模型。[决策时点 `ApprovalController.java`](https://github.com/Stellogic/customer-agent/blob/77f165219c82afd94ad0bc70e27e4dcd5762c31c/backend/src/main/java/com/stellogic/customeragent/approval/ApprovalController.java) / [决策时点 `SupportWorkbenchController.java`](https://github.com/Stellogic/customer-agent/blob/77f165219c82afd94ad0bc70e27e4dcd5762c31c/backend/src/main/java/com/stellogic/customeragent/queue/SupportWorkbenchController.java)
- 现有业务层已经有值得保留的资源级约束：客服详情按当前有效分配过滤，审批详情与决定绑定当前 lease token/version。引入 Spring Security 时应把“谁登录了”统一为 `Authentication`，而不应删掉这些比角色更细的业务围栏。[`SupportWorkbenchProjectionService.java`](../../backend/src/main/java/com/stellogic/customeragent/queue/SupportWorkbenchProjectionService.java) / [`ApprovalController.java`](../../backend/src/main/java/com/stellogic/customeragent/approval/ApprovalController.java)

### 2.3 目标边界

```text
/help/login                    客户登录入口
/internal/login                内部工作人员登录入口或未来 OIDC 跳转
/help                          需要 CUSTOMER_HELP_ACCESS
/internal                      双角色内部工作人员的轻量工作区选择页
/internal/support              需要 SUPPORT_WORKBENCH_ACCESS
/internal/support/tickets/:id  需要客服权限 + 当前有效分配/可见范围
/internal/approvals            需要 APPROVAL_WORKBENCH_ACCESS
/internal/approvals/:id        需要审批权限 + 当前有效 lease/业务资格
```

登录后，前端只从 Spring 的当前用户端点读取最小身份投影（例如 `id`、`displayName`、`subjectType`、`roles` 和 `capabilities`），据此通过静态映射构造菜单和默认跳转；Spring 不需要知道或返回 React 路由路径。`capabilities` 是 UI 投影，不是授权凭据；每次 API 请求仍由 Spring 从服务端会话恢复 `Authentication` 并重新授权。Spring Security 官方说明认证持久化由 `SecurityContextRepository` 负责，典型会话登录后的后续请求携带 session cookie，认证成功时会更换 session id 以防 session fixation。[认证持久化](https://docs.spring.io/spring-security/reference/servlet/authentication/persistence.html) / [Session 管理](https://docs.spring.io/spring-security/reference/servlet/authentication/session-management.html)

## 3. 候选一：Ant Design Pro / Pro Components

### 3.1 能提供什么

Ant Design Pro 将自己定位为企业应用的开箱即用 React 方案，官方模板包含登录、403/404/500、Dashboard、列表、表单、详情、响应式布局、主题和国际化；当前主线明确使用 React 19、Umi Max 4 和 Ant Design 6。[官方仓库与功能清单](https://github.com/ant-design/ant-design-pro)

Umi Max 的 Layout 插件基于路由配置生成顶栏/侧栏菜单，支持共享 Layout、403/404 和错误边界；与 Access 插件结合时，路由上的 `access` 字段既控制无权路由的 403，也参与菜单裁剪。[Umi Max Layout 与菜单](https://umijs.org/en-US/docs/max/layout-menu/) / [Umi Max 权限插件](https://umijs.org/en-US/docs/max/access/)

其权限模型由 `src/access.ts` 根据 `initialState` 生成布尔值或资源判断函数，再通过路由 `access`、`useAccess()` 和 `<Access>` 控制页面或局部元素。[Umi Max 权限插件](https://umijs.org/en-US/docs/max/access/) 这很适合把 Spring 返回的 capability 投影转成菜单与页面 guard，但该 JavaScript 判定可以被用户修改，不能替代 API 授权。

### 3.2 与本项目的匹配度

**高匹配部分：**

- `ProLayout` 可以直接承载一个 `InternalShell`，复用 Logo、侧栏、账号区、面包屑、页面容器、折叠和窄屏行为；Umi 官方也说明 Layout 菜单可由路由自动生成，并提供 403/404。[Layout 与菜单](https://umijs.org/en-US/docs/max/layout-menu/)
- 当前 Ant Design Pro 主线依赖 React 19.2.7、Ant Design 6 和 `@ant-design/pro-components`，与仓库的 React 19.2.7 版本方向一致；但“版本数字一致”仍不能替代在本仓库 TypeScript 6/Vite 8 上的实际安装和构建验证。[Ant Design Pro package.json](https://github.com/ant-design/ant-design-pro/blob/master/package.json) / [`frontend/package.json`](../../frontend/package.json)
- 既有仓库决议已经选择 Ant Design 作为内部工作台组件方向，因此复用 Pro Components 不引入第二套视觉系统。[既有 UI 选型](./ui-component-library-evaluation.md)

**不匹配或成本：**

- 完整 Ant Design Pro 是 Umi Max 应用模板，不是仅安装一个 UI 包；其构建/开发脚本运行 `max`，同时带有 Pro Components、图表、Ant Design X、X SDK、React Query、D3、地图数据、Markdown/高亮等依赖。[Ant Design Pro package.json](https://github.com/ant-design/ant-design-pro/blob/master/package.json) 直接替换会涉及 Vite 路由、构建、测试、环境变量、代理、目录约定和部署产物的系统迁移。
- `access.ts` 的授权值来自前端 initial state。它适合 UX，不负责 Spring API、审批 lease、客服分配或字段级投影的权威授权。[Umi Max 权限插件](https://umijs.org/en-US/docs/max/access/)
- 脚手架自带大量示例页面和 mock；官方提供 `simple` 脚本删除额外页面与依赖，而且明确说明此操作不可逆，反映出完整模板默认依赖面大于本项目当前需求。[Ant Design Pro 使用说明](https://github.com/ant-design/ant-design-pro#simplify-to-simple-version)

### 3.3 直接采用判断

| 采用方式 | 判断 | 原因 |
|---|---|---|
| 复制完整 Ant Design Pro 仓库并移植现有页面 | **暂不推荐** | 会把 UI 重构升级为 Vite→Umi Max 的平台迁移；现有测试、构建和部署都要重接，尚无证据证明收益覆盖成本。 |
| 在当前 Vite 应用安装 `antd` + `@ant-design/pro-components` | **推荐进入实现原型** | 保留现有构建和业务页面，直接获得成熟内部 shell 与页面容器；符合既有 Ant Design 决议。 |
| 参考 Ant Design Pro 的路由、账号区、403/404、菜单组织代码 | **推荐** | 复用成熟交互和信息架构，但将登录态与权限数据源替换为 Spring。 |

Ant Design Pro 及 Pro Components 均采用 MIT 许可证，可使用、修改和分发，但分发副本或实质部分时必须保留版权与许可证文本。[Ant Design Pro LICENSE](https://github.com/ant-design/ant-design-pro/blob/master/LICENSE) / [Pro Components package.json](https://github.com/ant-design/pro-components/blob/master/package.json)

## 4. 候选二：react-admin

### 4.1 能提供什么

react-admin 是 Marmelab 维护的 React 单页后台框架，基于 Material UI、React Router、TanStack Query 和 react-hook-form，提供 REST/GraphQL `dataProvider`、`authProvider`、资源 CRUD、列表/表单、菜单、主题、i18n 和通知；官方仓库还包含 helpdesk 示例。[官方仓库](https://github.com/marmelab/react-admin)

认证由应用自行实现的 `authProvider` 适配后端；配置后，框架可保护资源页面并把匿名用户重定向到登录页。[Security](https://marmelab.com/react-admin/Authentication.html) 授权推荐使用 `authProvider.canAccess({ resource, action, record? })`，可以表达 RBAC、ABAC、ACL 和记录级检查；核心 List/Create/Edit/Show 页面会自动检查，但自定义路由必须显式包裹 `<Authenticated>` 与 `<CanAccess>`，自定义菜单也必须显式裁剪。[Authorization](https://marmelab.com/react-admin/Permissions.html)

当前 `react-admin` 包元数据声明 React/React DOM `^18 || ^19`、React Router `^6.28.1 || ^7.1.1`，许可证为 MIT；直接依赖还包含 MUI、Emotion、TanStack Query、react-hook-form 和多项 `ra-*` 包。[官方 package.json](https://github.com/marmelab/react-admin/blob/master/packages/react-admin/package.json) 官方仓库有持续维护的 master/next 分支约定并提供频繁发布流程，但实际选用版本仍应固定并在本项目锁文件中验证。[维护与发布说明](https://github.com/marmelab/react-admin#versions-in-this-repository)

### 4.2 与本项目的匹配度

**优点：**

- 三个候选中，react-admin 对传统资源 CRUD 的现成页面、表单、过滤、权限检查最完整；若未来要做用户、规则、知识库、配置等大量管理表，它能显著降低重复代码。[功能清单](https://github.com/marmelab/react-admin#features)
- `canAccess` 支持传 `record`，可以承载“记录级可见性”的 UI 查询；异步实现也可向 Spring 请求当前权限。[Authorization](https://marmelab.com/react-admin/Permissions.html)
- `dataProvider` 是适配器，不强制后端采用某个既定 REST 方言；官方说明可为现有 API 编写自定义 provider。[架构](https://marmelab.com/react-admin/Architecture.html)

**缺点：**

- 当前核心页面是专用工作流：客服队列 + 当前分配详情、审批 claim/release、lease token/version、幂等决定和 SSE 权威刷新。把这些硬映射为 List/Edit/Create 资源可能弱化领域动作，仍会大量使用 Custom Routes 和自定义 hooks。
- 默认 UI 是 Material UI，而仓库已确认 Ant Design 方向；同时保留 MUI 和 Ant Design 会造成主题、交互和 bundle 双重成本，迁到 MUI 又会推翻既有决议。[react-admin 技术栈](https://github.com/marmelab/react-admin) / [既有 UI 选型](./ui-component-library-evaluation.md)
- 官方明确说明 custom route 默认没有认证或授权，必须开发者显式保护；因此“使用 react-admin”并不会自动保护本项目的定制审批页。[Authorization - Custom Routes](https://marmelab.com/react-admin/Permissions.html#custom-routes)
- react-admin 的部分高级 RBAC 等能力存在 Enterprise 私有模块；开源核心已有 `canAccess`，但选型时不能把商业扩展能力误算为 MIT 核心自带。[开源仓库与 Enterprise 边界](https://github.com/marmelab/react-admin#support)

### 4.3 直接采用判断

**不建议作为当前统一后台的主框架。** 可以参考它的 `authProvider`/`dataProvider` 边界、错误处理和 helpdesk 信息架构；未来若出现独立的 CRUD 管理域，可在原型中评估 react-admin，但不应为客服与审批两条定制工作流先引入 MUI 全栈。

react-admin 开源核心为 MIT，官方明确可免费用于商业用途。[官方 LICENSE 说明](https://github.com/marmelab/react-admin#license)

## 5. 候选三：refine

### 5.1 能提供什么

refine Core 是面向 CRUD 密集型内部工具、后台和 B2B 应用的 headless React 元框架，将 UI 与路由解耦，官方支持 Ant Design、Material UI、Mantine、Chakra UI，并通过 provider 接入数据、认证、授权和路由。[官方仓库](https://github.com/refinedev/refine)

refine 的 `authProvider` 提供 login/logout/check/getIdentity/getPermissions 等异步边界，可接自建后端或第三方身份服务；复杂授权推荐独立使用 `accessControlProvider`。[Auth Provider](https://refine.dev/core/docs/authentication/auth-provider/) `accessControlProvider.can({ resource, action, params })` 可表达 RBAC/ABAC/ACL，`<CanAccess>`/`useCan` 控制页面与元素，Ant Design 的侧栏和按钮集成还能自动隐藏无权项。[Authorization](https://refine.dev/core/docs/guides-concepts/authorization/)

需要特别注意：官方明确警告，仅向 `<Refine>` 提供 `accessControlProvider` **不会自动强制路由授权**，受保护路由仍需包裹 `<CanAccess>`；这同样只是前端层，Spring API 仍须独立拒绝越权请求。[Access Control Provider](https://refine.dev/core/docs/authorization/access-control-provider/)

refine v5 官方说明支持 React 18/19，升级到 TanStack Query v5，并提供 `@refinedev/antd`、`@refinedev/react-router` 的同代包；其 Quick Start 明确支持 Vite，因此比 Ant Design Pro 整仓更容易嵌入当前工程。[v5 兼容与包矩阵](https://refine.dev/core/docs/migration-guide/4x-to-5x/) / [Quick Start](https://refine.dev/core/docs/getting-started/quickstart/)

### 5.2 与本项目的匹配度

**优点：**

- 可保留 Vite、React Router 和 Ant Design，不强制替换为 Umi 或 MUI；路由仍由应用自己定义，refine router provider 只提供推断、跳转和查询参数集成。[Routing](https://refine.dev/core/docs/guides-concepts/routing/)
- `accessControlProvider` 与 Spring capability 投影有清晰适配点，Ant Design Sider 会根据 resource/list 权限自动隐藏菜单项。[Authorization - UI integrations](https://refine.dev/core/docs/guides-concepts/authorization/#ui-integrations)
- 对未来普通 CRUD、分页过滤、表单、缓存和实时更新比纯 Pro Components 提供更多应用层抽象。[官方功能清单](https://github.com/refinedev/refine#key-features)

**缺点：**

- 引入 Core、TanStack Query、React Router adapter、Ant Design adapter 及 provider 体系；refine v5 官方明确要求 TanStack Query v5。[v5 迁移说明](https://refine.dev/core/docs/migration-guide/4x-to-5x/)
- 当前页面已有专用 fetch/SSE/租约与幂等状态机，迁成 resource/action 需要适配设计；若只使用 shell、菜单和路由，refine 提供的 CRUD 层多数暂时闲置。
- provider 与 resource 元数据会形成框架锁入；虽可替换 UI/路由，页面若大量使用 `useList`、`useOne`、`useForm`、`useCan`，退出成本高于只使用 Ant Design/React Router。refine 自己的 v4→v5 文档也列出 data hook 返回结构、router/auth provider 等多项破坏性迁移，说明 major 升级需要预算。[v5 破坏性变更](https://refine.dev/core/docs/migration-guide/4x-to-5x/)

### 5.3 直接采用判断

**可作为条件式第二选择，不建议未经原型直接全面迁移。** 如果近期路线图确认会增加多个标准 CRUD 内部模块，建议做一个隔离 spike：保留一个现有审批页为 Custom Route，再用一个普通管理资源验证 data/auth/access providers、SSE 和 bundle；只有收益被测量后才决定全面使用。若内部后台仍主要是客服与审批两条领域工作流，则 Pro Components + React Router 更轻。

refine Core 官方仓库采用 MIT 许可证。[官方仓库许可证](https://github.com/refinedev/refine#license)

## 6. 横向比较

| 维度 | Ant Design Pro / Pro Components | react-admin | refine v5 |
|---|---|---|---|
| 核心定位 | 企业后台模板 + Ant Design 高阶组件 | Material UI 资源 CRUD 后台 | Headless CRUD/内部工具元框架 |
| React 19 | Pro 模板当前直接使用 19.2.7 | 包 peer range 明确含 React 19 | v5 官方明确支持 React 18/19 |
| 保留当前 Vite | 只用 Pro Components：是；整仓 Pro：否，转 Umi Max | 是 | 是 |
| 保留 Ant Design | 是 | 否，默认 MUI | 是，官方 adapter |
| 共享 shell/菜单 | 强，ProLayout 与路由菜单成熟 | 强，但默认 MUI Layout | 强，ThemedLayout/Sider + resources |
| 页面级 UI 权限 | Umi route `access` / `<Access>` | `<Authenticated>` / `<CanAccess>` | `<Authenticated>` / `<CanAccess>` |
| 资源/记录级 UI 权限 | 可写函数，但需自建约定 | `resource/action/record` 成熟 | `resource/action/params` 成熟 |
| Spring 适配 | 自行读取 session/capabilities | 自写 authProvider/dataProvider | 自写 authProvider/accessControlProvider/dataProvider |
| 专用工作流与 SSE | 灵活，业务代码直接掌控 | 需大量 custom routes/hooks | 可做 custom route/live provider，但有适配层 |
| 锁入 | 组件采用低；整仓 Umi 采用高 | 高：RA resource/provider + MUI | 中高：Refine providers/resources/hooks |
| 依赖与包体风险 | Pro Components 中；整仓 Pro 高 | MUI/Emotion/Query/Form/RA 多包 | Core/Query/router/UI adapters 多包 |
| 许可证 | MIT | MIT 核心；部分 Enterprise 商业 | MIT Core |
| 当前建议 | **首选：采用组件与模式** | 不选主框架 | CRUD 增长时做 spike |

“包体风险”是基于官方依赖图的相对判断，不是实测 KB 数字。候选都支持 tree shaking 或模块化使用，但本项目必须用相同页面和 production build 报告比较首屏、异步 chunk、CSS 和运行时请求，才能形成量化结论。[Pro Components `sideEffects: false`](https://github.com/ant-design/pro-components/blob/master/package.json) / [react-admin `sideEffects: false`](https://github.com/marmelab/react-admin/blob/master/packages/react-admin/package.json)

### 6.1 维护性证据与边界

- Ant Design Pro 官方仓库当前有 v6 主线、发布页和持续更新的 React 19/Umi Max 模板；Pro Components 也有独立仓库与发布包，说明模板与组件层可以分开升级。[Ant Design Pro releases](https://github.com/ant-design/ant-design-pro/releases) / [Pro Components 仓库](https://github.com/ant-design/pro-components)
- react-admin 官方仓库明确维护 `master`（下一个 patch）和 `next`（下一个 major/minor），并提供发布与商业支持入口；这比无人维护模板更适合作为长期依赖，但商业支持不代表开源核心包含全部 Enterprise 模块。[版本分支说明](https://github.com/marmelab/react-admin#versions-in-this-repository) / [支持边界](https://github.com/marmelab/react-admin#support)
- refine 官方仓库和 releases 显示 v5 仍在发布，官方文档有完整的 v4→v5 迁移指南；这同时证明活跃维护和 major 升级成本，不能只看 release 数量判断稳定性。[refine releases](https://github.com/refinedev/refine/releases) / [v5 迁移指南](https://refine.dev/core/docs/migration-guide/4x-to-5x/)

三者都是前端方案：它们可以适配 Spring 登录和权限投影，但都不提供本项目可直接采用的 Spring 工单/审批授权后端。维护性选择因此还要看团队能否长期维护 adapter、升级测试和安全回归，而不能仅凭 GitHub star 或最新发布日期决定。

## 7. Spring Security 推荐边界

### 7.1 统一登录：本地会话与 OIDC 分层

**推荐部署形态：Spring 作为同源 Web/BFF，浏览器只持有 HttpOnly session cookie。** Spring Security 官方把认证结果通过 `SecurityContextRepository` 持久化到后续请求；这与当前同源 fetch 兼容，并避免把 OIDC access/refresh token 暴露给 React。[认证持久化](https://docs.spring.io/spring-security/reference/servlet/authentication/persistence.html)

- 本地开发/演示：可以使用 Spring Security form login 或受控 demo authentication provider，形成真实 `Authentication` 和 `HttpSession`；固定合成入口只能保留在 `local-demo` profile，不能成为生产登录协议。
- 生产/组织内部环境：如果已有身份提供方，优先使用 `oauth2Login()` 走 Authorization Code Grant/OIDC；Spring Security 官方 OAuth2 Login 同时支持 OAuth 2.0 Provider 和 OpenID Connect 1.0 Provider。[OAuth2 Login](https://docs.spring.io/spring-security/reference/servlet/oauth2/login/)
- 本文不选择具体 IdP，因为仓库没有 Azure AD、Keycloak、Okta 等部署约束或租户信息；直接决定会超出证据。

会话型浏览器应用必须保留 CSRF 防护。Spring Security 官方说明同步 token 是主要防护，SameSite 只能作为纵深防御；SPA 使用 Cookie CSRF token 时还需处理 BREACH 编码以及登录/退出后刷新 token。[CSRF 原理](https://docs.spring.io/spring-security/reference/features/exploits/csrf.html) / [SPA CSRF 配置](https://docs.spring.io/spring-security/reference/servlet/exploits/csrf.html#csrf-integration-javascript-spa)

### 7.2 RBAC 只做粗门，资源授权继续做细门

建议把角色与动作权限分开：

| 层次 | 示例 | 执行位置 |
|---|---|---|
| 认证 | 已登录内部用户 | Spring Security session/OIDC |
| 粗粒度角色 | `ROLE_SUPPORT`、`ROLE_APPROVER` | `authorizeHttpRequests` + 菜单投影 |
| 动作权限 | `support:workbench:read`、`approval:decision:write` | `hasAuthority` / `@PreAuthorize` |
| 资源范围 | 当前客服是否有该工单有效分配 | 业务查询/领域服务，必要时自定义 AuthorizationManager |
| 业务围栏 | 审批 lease 是否归属本人、版本是否当前、提案是否仍可决策 | 现有审批服务事务内校验，不能只靠角色 |

Spring Security 的请求 DSL 支持 `hasRole`、`hasAuthority`、`permitAll`、`denyAll`，适合在 `/api/support/**`、`/api/approver/**` 做默认拒绝和粗粒度门禁。[Authorize HTTP Requests](https://docs.spring.io/spring-security/reference/7.0/servlet/authorization/authorize-http-requests.html) 方法级授权通过 `@EnableMethodSecurity` 启用，可使用 `@PreAuthorize` 等注解并引用方法参数或返回值；官方特别说明 Spring Boot Starter Security 默认不会自动启用方法授权。[Method Security](https://docs.spring.io/spring-security/reference/servlet/authorization/method-security.html)

### 7.3 响应语义

- 未登录 API 请求返回 `401`；前端根据受保护路由语境，将客户页面请求转到 `/help/login?returnTo=...`，将内部工作台请求转到 `/internal/login?returnTo=...`。已登录但无粗权限返回 `403`。
- 对可枚举风险高的工单/提案资源，继续使用项目既有的不可枚举语义（例如无可见范围时 `404`）以及 `Cache-Control: no-store`，不要因为框架默认 403 就泄露资源存在性。[既有验证记录](../baseline/verification.md)
- SSE 建连和每次轮询/重授权都必须读取当前 Spring Principal 并重新检查资源资格；隐藏菜单或初次连接成功不能替代持续授权。

## 8. React Router 与前端权限边界

推荐使用 React Router 的嵌套 layout route：`InternalShell` 渲染 `<Outlet>`，客服与审批页面作为子路由；官方 Declarative Routing 明确支持无 path 的 layout route 和嵌套路由。[React Router Routing](https://reactrouter.com/start/declarative/routing)

前端路由层需要：

1. 根 `SessionBoundary` 只调用一次当前用户端点，区分 loading / anonymous / authenticated。
2. `InternalShell` 只对 authenticated 内部用户挂载，基于服务端返回 capability 过滤菜单。
3. 每个页面 route 再声明所需 capability；直接输入 URL 时显示 403，而不是静默跳回首页。
4. 收到 API `401` 清空当前 UI 身份并跳转登录；收到 `403` 保留登录态、展示拒绝页；收到资源 `404` 不泄露额外详情。
5. route-level lazy load 客服与审批 chunk，避免所有角色下载不需要的页面代码；这降低包体和意外暴露面，但下载边界仍不是数据授权。

React Router 的 middleware 文档给出了认证 middleware + session 的模式，也说明为了让认证逻辑在每次 client navigation 都走服务端，需要配合 loader；本项目是 Spring 提供 API/静态产物的 SPA，不应另引入 React Router 服务端 session，而应让 route guard 查询 Spring 会话。[React Router Middleware](https://reactrouter.com/how-to/middleware) React Router 自己的 Security 文档也明确其内容不是完整安全指南，因此不能把客户端 router 当作授权系统。[React Router Security](https://reactrouter.com/how-to/security)

## 9. 推荐实施路径与决策门

### 阶段 A：先建立安全与壳，不绑定完整后台框架

1. 引入 `spring-boot-starter-security`，建立统一 `Authentication`、`SecurityFilterChain`、会话登录和 CSRF；把合成身份适配为仅 `local-demo` 可用的认证入口。
2. 把控制器里的 `X-Synthetic-*` 人类身份读取迁到 Spring Principal；机器身份维持独立最小权限认证链，避免与浏览器角色混用。
3. 建立当前用户端点与统一 logout；返回最小 UI 身份/权限投影。
4. 引入 React Router，创建 `/internal` 的 `InternalShell`、登录页、403/404、统一菜单与账号区。
5. 引入精确版本的 `antd` 与 `@ant-design/pro-components`，将现有客服和审批页面挂进同一 shell；业务状态、SSE 和租约协议先不重写。

### 阶段 B：用数据决定是否引入 refine

只有满足以下至少一项，才建议创建 refine spike：

- 已确认至少 3–5 个标准 CRUD 内部资源即将实现；
- 当前页面重复出现列表分页、过滤、表单、缓存失效、权限按钮等通用代码；
- 团队愿意接受 TanStack Query 与 refine resource/provider 作为长期应用层接口。

Spike 必须同时验证一个普通 CRUD 页面和一个现有审批定制页；如果只能证明 CRUD demo 好用，不能推导出它适合租约/SSE 工作流。

### 阶段 C：不建议执行的捷径

- 不要把整个 Ant Design Pro 仓库覆盖到 `frontend/` 后再修编译；应先有迁移票、依赖清单和回退方案。
- 不要仅根据角色隐藏菜单后就移除后端资源校验。
- 不要把 OIDC token 存在 localStorage；推荐 Spring 会话/BFF，浏览器只持 HttpOnly cookie。
- 不要把当前合成 header/cookie 改名为“真实登录”后继续使用。

## 10. 实现前必须通过的验证清单

1. **依赖兼容：** 在 React 19.2.7、TypeScript 6.0.3、Vite 8.2.1 上安装精确版本，执行 lockfile 审计、typecheck、单测和 production build。
2. **bundle：** 记录改造前后 JS/CSS 总量、登录首屏 chunk、客服 chunk、审批 chunk；确认未使用的图表、Ant Design X、D3、MUI 或 refine devtools 没进入生产包。
3. **认证：** 未登录直达两个内部 URL；登录后 session fixation；超时；退出；并发会话策略；Cookie 的 HttpOnly/Secure/SameSite；登录与退出后的 CSRF token 刷新。
4. **粗权限：** SUPPORT 访问审批菜单、路由和 API 均拒绝；APPROVER 访问客服菜单、路由和 API 均拒绝；双角色用户只登录一次且看到两类菜单。
5. **资源权限：** 客服读取非分配工单；审批人读取/决定无本人 lease、过期 lease、错误版本的提案；SSE 权限在运行期间撤销。
6. **语义与隐私：** 401/403/404 不混淆；不可枚举资源继续 404；敏感投影 `no-store`；前端构建与网络中没有模型密钥、LangGraph 私有地址或其他角色的数据。
7. **UI：** 桌面与 360px 窄屏；键盘、焦点、landmark、唯一 H1；页面刷新和浏览器前进/后退；403/404 和断线恢复。
8. **规范化检查：** 完成实现前从仓库根目录执行 `pwsh ./scripts/check.ps1`；该命令是仓库硬性门禁，不以候选框架自己的测试替代。[`AGENTS.md`](../../AGENTS.md)

## 11. 最终建议

本项目下一步应采用下面的组合，而不是把某个开源后台当成安全系统：

```text
React 19 + Vite 8
  + React Router 7（统一嵌套路由）
  + Ant Design 6 / Pro Components（InternalShell 与后台 UI）
  + 现有领域页面与 SSE/租约协议（渐进迁移）

Spring Boot 4.1
  + Spring Security（session 或 OIDC 登录）
  + request/method authorization（角色与动作）
  + 现有领域服务（分配、lease、幂等、状态机等资源级权威）
```

因此，**直接使用开源项目的合理边界是直接使用 Ant Design/Pro Components 的产品化组件与 Ant Design Pro 的后台组织模式，而不是直接替换成完整模板；refine 保留为 CRUD 规模扩大后的可验证候选；react-admin 不进入当前主路线。** 这一建议与仓库既有 Ant Design 决议一致，同时修正当前“两条独立页面 + 合成身份”的落地偏差。[既有 UI 决议](./ui-component-library-evaluation.md) / [Ant Design Pro](https://github.com/ant-design/ant-design-pro) / [refine](https://github.com/refinedev/refine) / [react-admin](https://github.com/marmelab/react-admin)
