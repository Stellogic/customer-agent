# Customer Support Agent

本仓库正在实现“客服工单调查与补偿审批 Agent”。当前代码是 Issue #12 的可复现本地全栈基线，只建立后续纵向切片共享的运行、迁移、合成身份和信任边界，不包含客服工单业务。

## 本地启动

前置条件只有 Docker Desktop 与 Docker Compose。首次启动会构建 React、Spring Boot 和私有 Agent Server，并在同一 PostgreSQL 实例中创建相互隔离的业务数据库与 Agent checkpoint 数据库：

```powershell
Copy-Item .env.example .env
docker compose up --detach --build --wait
```

打开 <http://127.0.0.1:4180>。浏览器只请求同源的 `/api/system/status`；Nginx 只把 `/api` 转发给 Spring Boot，Agent Server 和 PostgreSQL 均未发布主机端口。

从空数据库重复验证全部基线：

```powershell
pwsh -File scripts/smoke.ps1 -Reset
```

`-Reset` 只删除本 Compose 项目的本地合成数据卷。日常复测可省略该参数。停止服务：

```powershell
docker compose down
```

## 已锁定版本

| 组件 | 精确版本或镜像 |
|---|---|
| React / React DOM | `19.2.7` |
| Node.js | `24.19.0` |
| TypeScript | `6.0.3` |
| Vite | `8.2.1` |
| Spring Boot | `4.1.0` |
| Gradle | `9.3.1` |
| Java | Temurin `25.0.3+9` |
| Python | `3.13.14` |
| LangGraph | `1.2.10` |
| langgraph-checkpoint | `4.2.0` |
| langgraph-checkpoint-postgres | `3.1.2` |
| PostgreSQL | `18.4` |

前端、后端和 Agent 依赖分别由 `package-lock.json`、`gradle.lockfile` 和 `uv.lock` 固定。早期调研中的 Java `25.0.4`、Python `3.13.15` 是候选值；实现时官方容器仓库尚无对应标签，因此没有把它们误写为已运行验证版本。实际验证证据见 `docs/baseline/verification.md`。

## 边界说明

- Spring 业务运行账号与迁移账号分离；Agent runtime 与 checkpoint 迁移账号也分离。
- Spring 业务库与 Agent checkpoint 库没有共享 ORM、跨库外键或跨服务事务。
- `local-demo` profile 提供客户、客服、审批人、Agent、补偿执行器五个合成身份入口；正式 React 页面没有自由角色切换器。
- Spring→Agent、Agent→Spring 与补偿执行器探针使用三个不同的本地演示机器令牌；跨能力调用返回 `401/403`。
- 所有账号、令牌和探针数据均为本地合成数据，不可用于生产。

这是学习与演示环境，不声称生产高可用、水平扩展、灾难恢复或真实支付能力。
