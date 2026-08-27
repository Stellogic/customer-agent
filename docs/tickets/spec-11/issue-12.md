# 验证可复现的全栈运行与合成身份基线

> 父规格：[#11 规格 客服工单调查与补偿审批 Agent MVP 首个纵向切片](../../specs/issue-11.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/12](https://github.com/Stellogic/customer-agent/issues/12)
> Issue 状态：CLOSED
> 创建时间：2026-08-09T11:21:00Z
> 最后更新时间：2026-08-09T15:20:35Z
> 关闭时间：2026-08-09T15:20:35Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

- #11

## What to build

建立一个范围严格受控、可以从空环境重复启动的本地全栈基线，实际验证候选 React、Spring Boot、LangGraph 与 PostgreSQL 版本能够协同运行。该基线只提供后续纵向切片必须共享的运行、迁移、身份和信任边界，不提前实现客服工单业务。

浏览器只能访问 Spring Boot；Spring 与私有 Agent Server 通过受限服务接口通信。Spring 业务数据与 Agent checkpoint 使用同一 PostgreSQL 实例中的不同数据库、账号和迁移权限。所有演示身份及探针数据均为合成数据。

## Acceptance criteria

- [ ] 锁定 React、Node.js、TypeScript、Spring Boot、Java、Python、LangGraph、checkpoint 组件和 PostgreSQL 的精确版本及依赖锁文件；记录实际验证结果，不把候选版本描述为已验证结果。
- [ ] 一条有文档说明的本地启动流程可以启动 React、Spring Boot、私有 Agent Server 和 PostgreSQL，并能从空数据库执行真实迁移。
- [ ] Spring 与 Agent Server 分别使用独立数据库、账号和迁移权限；不存在共享 ORM 模型、跨数据库外键或跨服务事务。
- [ ] React 通过 Spring 提供的最小服务状态投影确认系统可用；浏览器网络请求和生产构建中不存在 Agent Server 地址、模型密钥或数据库凭据。
- [ ] 建立客户、客服、审批人、Agent 和补偿执行器的合成身份入口；正式产品界面不存在自由角色切换器。
- [ ] Agent 与补偿执行器使用不同的受限机器身份，最小探针证明二者不能互相调用对方能力。
- [ ] 自动化冒烟检查覆盖前端类型检查与生产构建、Spring 启动及迁移、Agent Server 启动，以及 Spring 到 Agent Server 的最小受限调用。
- [ ] README 或等价运行说明明确该基线是本地学习与演示环境，不声称生产高可用、水平扩展或灾难恢复。

## Blocked by

None — can start immediately.
