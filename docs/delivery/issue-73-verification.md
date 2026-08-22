# Issue #73 验证记录

## 基线与范围

- 实现前显式执行 `git fetch origin main`，并确认 `HEAD`、`origin/main`、`FETCH_HEAD` 均为 `5a324fcabdca5fa664c76c67c509a33bbd9cc8ab`，工作树无未提交项目改动。
- GitHub 实时回读确认父规格 #71 与 #73 均开放，前置 #72 已关闭；本次只建立前端静态路由、两个 Shell 与 route-level lazy loading，不迁移业务 API 的人工身份来源。
- 测试接缝是 `GET /api/auth/session` 的外部响应到浏览器可观察的路径、菜单、Shell、403 与登录跳转；不断言 React 内部状态。

## 依赖兼容性

真实 npm 安装首先证明 `@ant-design/pro-components@2.8.10` 的 peer 只接受 Ant Design 4/5，不能与 Ant Design 6 组成无冲突依赖树。随后依据 npm 发布元数据选择并精确锁定：

- `react-router-dom@7.18.2`
- `antd@6.6.1`
- `@ant-design/pro-components@3.1.14-6`，其 peer 声明为 `antd@^6.0.0`、`react@>=18.0.0`、`react-dom@>=18.0.0`

该组合已通过真实安装、TypeScript 类型检查、Vitest 行为测试与 Vite 生产构建。内部 Shell 使用 Ant Design `Layout`/`Menu`，轻量工作区选择页实际使用 Pro Components `ProCard`；没有引入 Umi Max、Ant Design Pro 应用框架、react-admin 或 refine。

## 路由与分包证据

生产构建为三个业务区域生成独立入口 chunk：

- `CustomerWorkspace`：11.83 kB（gzip 4.17 kB）
- `SupportWorkspace`：6.79 kB（gzip 2.87 kB）
- `ApprovalWorkspace`：7.60 kB（gzip 2.74 kB）

同时生成独立 `CustomerShell`、`InternalShell` 与 `InternalLanding` chunk。初始 `index` chunk 为 230.74 kB（gzip 74.04 kB）；对该文件搜索“物流遇到问题”“客服共享队列”“待审批队列”均无命中，表明三类业务模块未同步进入初始 chunk。分包只用于性能，不作为授权或数据隔离边界。

## 规范化验证

从仓库根目录原样执行 `pwsh ./scripts/check.ps1`。受限沙箱首次运行因无法读取用户 Docker 配置和 named pipe（`Access denied`）失败；在宿主上下文以完全相同命令重跑后退出码为 0：

- 前端容器使用规定的 Node `v24.19.0` 完成 `npm ci`、格式、lint、类型检查、48 个单元/行为测试与生产构建。
- 两条 Issue #29 React 全栈验收（normal、reconciliation）均通过。
- 真实 Spring、PostgreSQL、Agent、补偿执行器与 SSE smoke 通过，最终 `FULL_RESET_GATE` 报告 Spring、database、agent 均为 `UP`。
- 产品运行日志敏感内容扫描通过。

PR 合并仍以 GitHub CI 的远端回读为最终证据。
