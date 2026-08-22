# ADR 0002：静态 React Shell 与路由组件栈

## 状态

已接受，对应 #71 / #73。

## 背景

#71 已决定一个 Vite/React 发布单元使用彼此独立的 `CustomerShell` 与 `InternalShell`，由前端静态路由表把服务端当前身份的 `subjectType` 和三种页面 capability 投影成菜单、守卫与默认落点。既有[组件库调研](../research/ui-component-library-evaluation.md)已经确认 Ant Design 适合内部工作台的布局与导航，并明确前端裁剪不是授权边界；#73 要求通过真实安装与构建锁定 React Router 7、Ant Design 6 和 Pro Components 的兼容版本。

## 决策

- 精确锁定 `react-router-dom@7.18.2`、`antd@6.6.1` 与 `@ant-design/pro-components@3.1.14-6`，提交 npm lockfile。
- React Router 只消费仓库内的静态 route/workspace registry；Spring 的 `/api/auth/session` 不返回 React 路径。
- `CustomerShell`、`InternalShell`、客户工作区、客服工作区和审批工作区均按 route lazy loading；分包只优化加载，不承担数据隔离或授权。
- `InternalShell` 使用 Ant Design `Layout`/`Menu`；Pro Components 只在轻量内部选择页使用 `ProCard`，避免整体迁移到 Ant Design Pro/Umi。
- 当前票只把 auth session 用于页面体验。客服与审批业务组件继续通过既有 `/api/demo/session` 接缝取得 `X-Synthetic-*` 所需身份；迁移到 Spring Principal 属于后续票。

## 证据与取舍

- npm 首次安装证明稳定版 `@ant-design/pro-components@2.8.10` 的 peer 仅接受 Ant Design 4/5，不能与 Ant Design 6 形成无冲突依赖树；beta `3.1.14-6` 明确声明 `antd@^6.0.0`、React/React DOM `>=18`，Node `>=22.12.0`，与仓库 Node 24、React 19 基线相容。[Pro Components npm](https://www.npmjs.com/package/@ant-design/pro-components) / [Ant Design npm](https://www.npmjs.com/package/antd) / [React Router npm](https://www.npmjs.com/package/react-router-dom)
- 该 prerelease 的变化风险高于稳定版，因此使用精确版本和 lockfile，不使用 `latest`、`^` 或强制忽略 peer 冲突；升级必须重新执行同一门禁与 bundle 实测。
- 三者均是纯前端运行依赖，不增加服务、数据库或运维组件。Pro Components 会扩大内部选择页 bundle，但 route lazy loading 使它不进入初始/客户业务 chunk；实测数据记录在[交付验证](../delivery/issue-73-verification.md)。
- Ant Design、Pro Components 与 React Router 仓库均使用 MIT 许可；分发仍需保留相应版权与许可声明。[Ant Design LICENSE](https://github.com/ant-design/ant-design/blob/master/LICENSE) / [Pro Components LICENSE](https://github.com/ant-design/pro-components/blob/master/LICENSE) / [React Router LICENSE](https://github.com/remix-run/react-router/blob/main/LICENSE.md)
- 页面只渲染 Spring 已返回的身份投影，不持有凭据、不下发动态组件名，也不把 capability 当作资源授权，新增依赖不会改变服务端安全边界。

## 被否决的方案

- 强制安装 Pro Components 2.8.10：忽略已知 peer 冲突，无法称为兼容版本。
- 整体采用 Ant Design Pro/Umi Max：会引入额外路由、数据流和工程约定，超出两个 Shell 的渐进式改造范围。
- 采用 react-admin 或 refine：面向通用 CRUD 的抽象不能替代本项目的客服 SSE、审批租约和补偿状态流程，并增加锁定成本。
- 复制组件库布局代码：当前壳已能自然复用成熟组件，复制会增加无差异维护成本。

## 影响

静态 workspace registry 成为 capability、路径、菜单和选择卡片的唯一映射来源。组件库升级需要验证 peer 范围、许可证变化、类型检查、完整测试、生产构建与初始 chunk；若 Pro Components prerelease 后续不稳定，可保留相同 registry/Shell 边界并把选择卡片降为 Ant Design `Card`，无需改动业务页面或服务端契约。
