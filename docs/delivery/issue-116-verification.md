# Issue #116：默认关闭的业务路径 shadow

## 范围与配置

真实工单调查图继续以 `FixedFakeInvestigationModel` 形成唯一业务结论。新增 shadow 节点只在 fake 结论已由 Spring 权威接口接受后运行，读取同一处理代次已经取得的最小结构化事实，不调用任何 Spring 写接口。

`AGENT_INVESTIGATION_SHADOW_MODE` 的默认值为 `disabled`：此时图不会构造候选 adapter，也不会发生 DeepSeek 调用。`offline` 仅供仓库全栈门禁使用：它以 `httpx.MockTransport` 供应商替身贯穿同一个 DeepSeek Responses adapter、严格请求与响应解析接缝，而不是再次调用业务 fake；`deepseek` 显式选择现有受控 Responses adapter，且仍要求有效 `DEEPSEEK_API_KEY`，缺失配置或调用失败只形成失败比较记录，不回退为第二条业务结论。

本票未把密钥加入仓库、Spring、React、镜像或默认 Compose 配置，也没有运行真实 DeepSeek shadow。真实供应商证据仍为零，不能把离线 `MATCH` 表述为 Flash 已达到 #115 准入门槛。

## 最小记录与副作用边界

shadow 只向 LangGraph 当前线程 checkpoint 写入：

- 由工单、处理代次、候选模型、提示版本和 schema 版本确定的稳定比较标识；
- 当前工单和处理代次标识；
- 候选模型、提示版本、schema 版本；
- `MATCH`、`MISMATCH` 或 `FAILED` 比较结果。

记录不包含订单引用、延迟事实、证据引用、候选结论字段、原始输入输出、供应商 payload、错误正文、提示正文、思维链或凭据。重复回调产生相同比较标识；shadow 失败被收敛为 `FAILED`，不会阻断或重做已经完成的 Spring 业务结论。旧处理代次仍由既有 Spring generation fencing 拒绝，shadow 节点本身没有提交结论、创建提案、解决工单、发送消息或改变处理代次的能力。

## 验证

- `pwsh ./scripts/check.ps1 -Component agent -SkipAcceptance`：离线单元、契约、类型与格式检查；复用 #115 的 24、48、72 小时、取消、退款、重复补偿、待处理动作、错误证据、提示注入及受控失败矩阵，并补充验证 shadow 离线替身经真实 Responses adapter 覆盖关键边界；
- `pwsh ./scripts/check.ps1`：使用 `offline` 替身的真实 React、Spring、LangGraph、PostgreSQL 与浏览器门禁；全栈 smoke 从持久化线程状态读回最小 `MATCH` 记录，同时既有 fake 业务结果保持不变；
- 独立 Standards 与 Spec 双审查；
- GitHub CI、合并、`origin/main` ancestry 与 Issue 关闭读回。
