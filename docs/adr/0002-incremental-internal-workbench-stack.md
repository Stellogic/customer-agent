---
status: accepted
---

# 渐进采用内部工作台组件栈

内部工作台保留现有 Vite 构建，渐进采用 React Router 7、Ant Design 6 与 Pro Components，而不整体迁移到 Ant Design Pro/Umi Max，也不以 react-admin 或 refine 替换定制业务页面。该选择复用成熟后台布局，同时保留客服 SSE、审批租约和资源级权限流程的控制权；依赖版本只有在安装、类型检查、构建和 bundle 实测通过后才能锁定，证据与候选比较见 [统一内部后台管理系统与鉴权方案调研](../research/internal-admin-platform-evaluation.md)。
