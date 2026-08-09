# Issue #12 全栈基线验证记录

验证目标是把候选技术组合提升为“本仓库实际运行过的本地基线”，而不是证明生产部署能力。

## 验证口径

- 从空 Compose 数据卷启动 PostgreSQL 18.4。
- 由 `spring_migrator` 和 `agent_migrator` 执行真实迁移；运行账号无 DDL 权限。
- 运行 Spring API 测试、Agent 测试、React 类型检查与生产构建。
- 通过 Spring 状态投影确认 PostgreSQL 与带认证的 Agent `/threads/search` 受限调用。
- 创建真实 Agent Server thread/run，执行 LangGraph 节点，回调 Spring 的 Agent 专属能力并在 Agent 数据库产生 checkpoint。
- 验证 Agent 与补偿执行器令牌不能互用，Spring 与 Agent 运行账号不能连接对方数据库。
- 验证 Agent Server 进程环境中不存在补偿执行器令牌。
- 扫描生产前端静态文件，拒绝 Agent 地址、本地令牌和数据库 URI。

统一命令：

```powershell
pwsh -File scripts/smoke.ps1 -Reset
```

## 实际结果

验证日期：2026-08-09（Asia/Shanghai）。首次启动前确认本项目不存在 Compose 数据卷；未删除或复用其他项目数据。

| 检查 | 结果 |
|---|---|
| Spring API 测试 | 2 个测试通过，JDK 25 编译与运行 |
| Agent 测试 | 1 个测试通过，Python 3.13.14 |
| React | TypeScript 6.0.3 类型检查、Vite 8.2.1 生产构建通过 |
| 真实迁移 | `spring-migrate`、`agent-migrate` 均以退出码 0 完成 |
| 服务状态 | Spring、PostgreSQL、Agent 均为 `UP` |
| LangGraph / checkpoint | 受保护 API 创建 thread `019fe68e-08a3-75e1-bc92-15d9eefb81f1`；一次图运行后 Agent 数据库有 6 条 checkpoint |
| 机器身份 | Spring 令牌可调用 Agent；执行器令牌被 Agent API 拒绝；Agent/执行器不能互调 Spring 能力 |
| 数据库身份 | `spring_app@customer_agent`、`agent_runtime@agent_checkpoint` 正向连接成功，两个跨库连接均被拒绝 |
| 浏览器产物 | 未发现 Agent 地址、本地机器令牌或 PostgreSQL URI |

实际运行时输出：Node `v24.19.0`；Temurin `25.0.3+9`；Python `3.13.14`；PostgreSQL `18.4`。Spring 状态投影为：

```json
{"status":"UP","services":{"agent":"UP","database":"UP","spring":"UP"}}
```

调研候选 Java `25.0.4` 与 Python `3.13.15` 在实现日没有对应的官方容器标签，因此没有纳入“已验证”表述；实际可拉取并已运行的补丁版本如上。

## 明确不覆盖

- LangGraph 开发服务器被强制终止后的 checkpoint 恢复保证。
- 生产身份提供商、mTLS、密钥轮换或互联网暴露。
- 高可用、水平扩展、备份恢复、灾难恢复与真实补偿执行。

## Issue #16 增量验证

验证日期：2026-08-10（Asia/Shanghai）。从空 Compose 合成数据卷运行 V1→V5 后，Flyway 历史为 `1:true` 至 `5:true`，完整 Spring/PostgreSQL/LangGraph smoke 退出码为 0。结果包含 55 条 checkpoint；同一 generation/thread 上分别存在初始 run 与按 `resumeRequestId` 标识的恢复 run；并发澄清回复只接受一个，状态码为 `[202, 409]`；未知恢复响应可按稳定身份查询为 `SUBMITTED`。既有无需补偿、自主解决、不可变提案修订、并发额度预占和拒绝用例同时通过。

另以隔离临时数据库先迁移到 V4，写入 `INVESTIGATING` 与 `RESOLVED` 两条合成旧工单，再单独执行 V5。升级后两条记录均保留：调查中工单的 `resolution_running_since` 回填为原 `created_at`，已解决工单保持空值；`resolution_elapsed_seconds=0`、`customer_human_preference=false`，既有提案表和新增澄清/恢复表同时存在。临时数据库在回读后已删除。

React 实时验收通过，生产构建扫描未发现 Agent 地址、本地机器令牌或 PostgreSQL URI。验证期间宿主 Docker 代理端口不可用，无法重新拉取 Nginx/Temurin 运行时基础镜像；因此集成栈使用本轮已通过测试的本地缓存镜像启动，业务数据库、Spring、Agent Server、LangGraph 和浏览器 API 边界均为真实进程，不把该结果表述为镜像仓库可用性验证。

## Issue #17 增量验证

验证日期：2026-08-10（Asia/Shanghai）。从空 Compose 合成数据卷运行 V1→V6 后，Flyway 历史为 `1:true` 至 `6:true`；后端完整测试、Agent 测试、React 单测/生产构建、真实 PostgreSQL/LangGraph smoke 与 React 实时验收均通过。smoke 结果包含 79 条 checkpoint，并保留 Issue #16 的同 generation/thread 恢复、并发澄清回复 `[202, 409]` 和稳定恢复查询。

可控时钟验收把首次响应精确放在 12 分钟和 15 分钟边界，并把解决累计时长放在 69120 秒、86399 秒和 86400 秒边界。结果证明：首次响应在 `WAITING_FOR_CUSTOMER` 仍形成预警/违约；解决时钟在 `WAITING_FOR_CUSTOMER` 的 86399 秒保持不变，在 `WAITING_FOR_EXTERNAL` 继续到 86400 秒；澄清恢复请求返回前已原子形成解决预警、违约及审计；重复调度后同一工单仍只有 4 个 SLA 事实和 4 个对应审计事件。并发验收让调度器等待工单行锁、在同一事务中把已耗 86400 秒的工单转为 `RESOLVED`，提交后仍补齐不可撤销的解决预警/违约；随后重开到 `INVESTIGATING` 保留 86400 秒，数据库约束拒绝把累计值降为 0。预警只投影给当时的 `support-demo` 当前分配，违约队列仅包含工单标识、生命周期、处理模式、原因、违约目标和进入时间，未暴露客户、订单、描述、消息或调查事实；队列未改变 `WAITING_FOR_EXTERNAL` / `AGENT`。

另以隔离临时数据库先迁移到 V5，写入一条 `WAITING_FOR_CUSTOMER` 旧工单，再单独执行 V6。升级后工单仍为 `WAITING_FOR_CUSTOMER`，`resolution_elapsed_seconds=1234`、`resolution_running_since=null`、首次响应事实仍存在，V1→V6 历史完整且新增 SLA/通知/共享队列表均存在。临时数据库在回读后已删除。首次完整 Compose 启动仍遇到宿主 Docker 代理 `127.0.0.1:7897` 不可达；本轮随后以已通过测试的本地镜像离线组装运行时完成上述真实进程验收，不把该结果表述为外部镜像仓库可用性验证。
