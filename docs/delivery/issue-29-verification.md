# Issue #29 验收口径

## 自动化分层

- `pwsh -File scripts/smoke.ps1 -Reset` 从本 Compose 项目的空合成数据卷执行 V1→V19，并运行广域后端/Agent 集成 smoke、React、真实 Spring/PostgreSQL/Agent Server/LangGraph 和模拟执行器。日常可在同一专用数据卷上不带 `-Reset` 复测可隔离的产品验收；每次进程为两条 Issue #29 场景创建唯一订单 namespace，不清空全库，也不覆盖之前的执行、幂等和持久化证据。要求空 fixture 的广域 `integration-smoke` 只在 `-Reset` 模式运行，无 Reset 模式会明确打印跳过原因，不能替代正式全量检查。
- `frontend/src/Issue29.e2e.test.tsx` 提供两条命名产品链：正常执行，以及副作用后响应丢失→`UNKNOWN`→同身份对账。两条链均从 React 客户表面创建工单，经 React 审批表面批准，再回到客户表面断言唯一结果。
- `.github/workflows/ci.yml` 只运行固定工具和假模型的确定性组件测试；不使用真实模型、不需要 API key。
- `pwsh -File scripts/real-model-smoke.ps1` 是显式 opt-in release smoke。它只发送固定合成事实，使用严格 JSON Schema，并仅评价结构化正确性、最小证据和安全不变量；不评价逐字措辞，也不赋予模型审批或执行权。

## 生产产物与隐私检查

完整 smoke 让浏览器网络、生产前端产物和产品日志共同消费 `frontend/src/sensitive-content-patterns.json`，拒绝 Agent 地址、本地机器令牌、PostgreSQL URI、模型密钥、prompt、reasoning、原始工具 payload、checkpoint、thread/run/trace 和支付凭据。私有 Agent Server 的第三方错误日志会附带编排标识，因此 Compose 明确不采集该容器日志；其可用性只经 Spring 授权状态投影和健康检查观测。

真实模型 smoke 采用 OpenAI Responses API 严格结构化输出。实现依据：[Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs)。密钥只从当前进程环境传入临时容器，不写入 Compose、`.env.example` 或前端。

当外部镜像仓库不可用、但固定运行时基础镜像已在本机验证并缓存时，`scripts/build-offline-runtime.ps1 -TestTag <本轮测试标签> -RuntimeTag <已缓存固定运行时标签>` 使用三个 `Dockerfile.offline`，只把本轮已通过测试的 JAR、Agent 源码和前端 `dist` 放入固定运行时层。输出统一使用稳定的 `local` 标签，避免每个 Issue 在多处同步默认标签。该路径能验证真实本地进程，但不能证明外部 registry 可用，也不能替代一次可联网的正式镜像构建。

## 交付边界

可证明的是“可运行的全栈 Agent MVP 及本地端到端验证”。不声称生产高可用、水平扩展、灾难恢复、真实支付、外部镜像仓库持续可用或强制进程重启后的 checkpoint 生存。

## 2026-08-11 本地验证记录

- 空 Compose 合成数据卷执行 V1→V18；两条 React 全栈验收分别通过，正常链约 2 秒，响应丢失/对账链约 4 秒。
- 两条链各自回读为一条 `SUCCEEDED` execution、一条 provider operation 和一条 simulated partial refund；响应丢失链尝试结果顺序为 `UNKNOWN,FOUND`。
- 原有完整 Spring/PostgreSQL/LangGraph smoke 通过并产生 77 条 checkpoint；并发、授权、审批、转人工、SLA、关闭/重开与补偿回归保持通过。React live integration 2/2 通过。
- Agent 确定性测试 22/22，React 确定性测试 23/23，后端完整 Gradle 套件、TypeScript 类型检查与生产构建通过。
- 真实浏览器 `360×800` 检查中，`documentElement.scrollWidth=345`、`body.scrollWidth=345`，不超过 `innerWidth=360`；三个具名表单控件均可见且在视口内，页面含一个 `main`、一个 H1，焦点轮廓可见，控制台无 warning/error。
- 生产前端产物确认包含 `/support` 与 `/approver` 路由，并通过共享敏感字段扫描；两条 live React 验收记录的全部浏览器请求保持为前端同源 `/api/`，请求体和响应体也通过同一规则。Spring、PostgreSQL 与执行器产品日志通过共享规则；Agent Server 日志流按上述隐私边界不进入产品日志面。
- 真实模型脚本未在本次自动验收中调用，因为当前终端没有 `OPENAI_API_KEY`，且 release smoke 要求调用者显式提供；因此不把真实模型可用性写成已验证结果。
- 外部 registry 元数据读取被宿主 Docker 代理 `127.0.0.1:7897` 拒绝。本轮使用已通过测试的产物与已缓存固定运行时层离线组装后完成真实进程验收，不把该结果表述为 registry 可用性验证。

## 2026-08-13 同卷复测验证记录

- 同一 Compose 数据卷先运行一次 `FULL_RESET_GATE`，再不带 `-Reset` 运行 `PERSISTENT_RERUN_SUITE`，两种显式模式均通过且前次证据保留；后者不声称等价全量。
- rerun suite 重新执行 Issue #29 正常链与响应丢失/对账链，并验证本轮唯一 namespace 各自只有一条 `SUCCEEDED` execution、一条 provider operation、一条 result、一条 simulated partial refund、一条客户成功消息，工单为 `RESOLVED`。
- 对账链在冻结时钟下的 execution 与 reconciliation attempt 具有相同 `started_at`；验收按 `started_at` 后再按 `EXECUTION → RECONCILIATION` 的业务阶段排序，连续五次聚合均为 `UNKNOWN,FOUND`，不使用随机 UUID 推断先后。
- rerun suite 只回读 `FULL_RESET_GATE` 已创建的自动执行器成功结果，证明同卷持久证据仍为 `SUCCEEDED:1:RESOLVED`；它不创建新的广域自动执行 fixture，也不替代全量门禁中的 executor 推进验证。
