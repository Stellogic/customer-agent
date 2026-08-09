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

## Issue #18 增量验证

验证日期：2026-08-10（Asia/Shanghai）。先在保留 V1→V6 历史的现有 Compose 数据卷执行 V7，回读 Flyway 历史为 `1:true` 至 `7:true`；再从空数据卷运行完整后端测试、Agent 测试、React 单测/生产构建、真实 PostgreSQL/LangGraph smoke 与 React 实时验收，全部通过。最终 smoke 结果包含 93 条 checkpoint，并继续通过既有补偿、澄清恢复和 SLA 用例。

客户转人工验收证明：相同请求身份重放返回原结果，不同参数复用身份返回冲突，断线后可按稳定身份查询；Spring 在一个事务中保留原生命周期、写入 `customer_human_preference=true`、切换为 `HUMAN`、把当前 generation 标记为 `HANDED_OFF`、失效当前澄清、保存只含结构化调查事实与证据引用的内部接手摘要、发布固定公开说明、写入共享队列和审计。客户快照只包含固定说明与公开状态，不包含 `CUSTOMER_REQUESTED` 内部原因或接手摘要。

旧 generation 的事实读取、澄清写入和结论提交分别被拒绝；使用转人工前已经成功的原澄清请求键和原结论请求键重放也被拒绝。拒绝均有受控审计，拒绝后公开消息数量不变。首次并发验收暴露了转人工与澄清回复的数据库锁序死锁；修复后转人工、澄清和 Agent 工具入口先取得同一工单的事务级业务权威锁。后续干净运行分别观察到 `[202, 202]` 与 `[202, 409]` 两种合法串行化结果：前者是澄清回复先作为当时有效输入提交，后者是转人工先撤销 Agent 权威；两者最终都收敛为 `HUMAN`、客户人工偏好为真、无 `ACTIVE` generation、无 `OPEN` 澄清，旧代次不能再产生副作用。React 单测还证明重复点击只提交一次，并忽略 `HUMAN` 模式下迟到的 Agent SSE 公开消息。

共享队列沿用 Issue #17 的 `shared_support_queue_entry`，主键扩展为工单与原因的组合。同一工单同时保留 `SLA_BREACH` 与 `CUSTOMER_REQUESTED_HANDOFF` 两个原因；既有 `/api/support/escalations` 仍只返回一次 SLA 违约摘要，新 `/api/support/queue` 聚合最小原因集合。转人工未改变 `WAITING_FOR_EXTERNAL` 生命周期、86399 秒解决累计值或已经形成的 4 个 SLA 事实。

本轮宿主 Docker 代理 `127.0.0.1:7897` 仍无法读取 Temurin/nginx 镜像元数据；后端、Agent、前端测试镜像正常构建并通过，运行镜像以本地缓存的 Issue #17 固定运行时层和本轮已测试产物离线组装。该路径完成了真实 Spring、PostgreSQL、Agent Server、LangGraph 与浏览器边界验证，但不证明外部镜像仓库可用。

## Issue #19 增量验证

验证日期：2026-08-10（Asia/Shanghai）。从空 Compose 合成数据卷执行 V1→V8，Flyway 历史为 `1:true` 至 `8:true`；完整后端测试、Agent 测试、React 生产构建、真实 PostgreSQL/LangGraph/Spring smoke、React 实时验收与前端敏感串扫描全部通过。最终 smoke 包含 69 条 checkpoint，并继续覆盖 #16 澄清恢复、#17 SLA 与共享队列、#18 客户主动转人工，以及补偿提案和额度预占不变量。

固定 Agent 用例确定性覆盖 `TOOL_RETRY_EXHAUSTED`、`FACT_CONFLICT`、`INVALID_TOOL_RESPONSE`、`REQUIRED_FACT_MISSING`、`UNSUPPORTED_SCENARIO` 五个封闭理由码。暂时性事实工具错误按配置预算立即重试，不依赖真实等待；预算耗尽后只发送受控理由码与结构化摘要，不携带异常、stack、prompt、自由形式推理或原始 payload。原先会到达 Spring 确定性拒绝的不支持订单现在在提案产生前转人工；剩余额度冲突仍由 Spring 拒绝结论，再映射为转人工，所有用例保持零提案副作用。

调查异常转人工复用 #18 的同一 `HumanHandoffService` 事务：保留生命周期、切换 `HUMAN`、撤销当前 generation、失效澄清、发布固定公开说明、写入共享队列和审计。客户人工偏好保持 `false`，不会把 Agent 发起的转人工伪造成客户请求。相同 generation/request/参数在转人工后仍可历史重放；不同参数复用返回 `409`，新请求和旧 generation 工具调用返回 `403`。两个不同异常理由并发触发观察到 `[202, 403]`，数据库只有一条请求、一个固定公开消息和一个 `AGENT_HUMAN_HANDOFF` 队列原因。

持久化摘要仅包含 `conclusionCode` 与受控的事实 `type`、`value`、`evidenceReference`，并且每项事实必须精确匹配当前 generation 在 Spring 中已经记录的调查事实；伪造值或仅伪造合法引用前缀会返回 `422`，不会改变工单或发布消息。客户投影不含内部理由码或摘要，共享队列只呈现聚合理由，不提供完整摘要读取入口。集成验收还发现 Agent 发起转人工最初错误限制为 `INVESTIGATING`；修复后当前有效 generation 在 `WAITING_FOR_CUSTOMER` 等未关闭生命周期也可转人工，同时保持原生命周期。宿主 Docker 代理仍不可达，本轮运行镜像由本地 #18 固定运行时层与本轮已通过测试的 JAR、Agent 源码和前端产物离线组装，不把该结果表述为外部镜像仓库可用性验证。
