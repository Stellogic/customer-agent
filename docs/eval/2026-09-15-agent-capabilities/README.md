# Agent 能力评测结果：2026-09-15

## 结论

**本轮不能证明 Agent 全面能力达标。** 冻结 12 个真实场景，结果为 **2 PASS / 1 FAIL / 9 NOT_RUN**；覆盖率 25%，按完整计划的业务通过率 16.7%，已执行案例通过率 66.7%（2/3）。三个样本不能外推为稳定准确率。

两个通过案例证明：自然语言正文中的订单和物流问题能进入真实调查；86399 秒不产生补偿，259201 秒正确生成 9.90 元模拟部分退款待审批，秒精度修复在本轮真实模型链路中生效。第三例先正确请求订单线索、理解补充并确认建票，但调查行动请求未取得可计量响应，交人工后整例失败。

**业务合同通过仍不等于答好客户问题。** 第一例询问“现在是什么状态，具体晚了多久”，公开回复只说核查完成、不涉及补偿，没有回答物流状态或延迟时长。第二例说明待审核、尚未退款，但没有给出具体方案金额。逐条原文、评分和理由见 [正文语义审阅](semantic-review.md)；不把泛化回复算作完整解答。

## 执行配置与可复现材料

- 修复前基线：`adacdd74f0492ad10f49a064170c2039c85b0b7c`；实际真实评测 SHA：`3f0027c42d0b88f0476059f4f59aa050a3325559`。
- Run ID：`issue242-capabilities-20260915-resume`。2026-09-15 23:15:44（北京时间）开始浏览器阶段，57.155 秒结束；单 worker、每例一次、案例重试 0。
- 链路：真实 Chromium → React → Spring API/SSE → PostgreSQL/LangGraph → DeepSeek `/responses`。受理、行动、判断、回复四角色均 `deepseek-v4-pro`；已收到的 10 次响应均为该模型，失败一次无响应模型信息。
- 模型输出不替换为假模型，不临时修改输入或通过标准。只创建合成订单、客户受理和工单；提案待审批，补偿执行器未启动，执行数为 0。
- 冻结场景、逐角色 prompt/schema 版本、模型参数及六项调查循环限额见 [PLAN](PLAN.md)、[执行计划](raw/plan.json)。调查循环 wall-clock 60 秒不代表整代次限时。
- 用户授权 10 元、80 次请求、160000 token，截止时间为 2026-09-15 23:56:16（北京时间）。未用完预算；因未知用量停止，未继续或更换账本。

首次启动 `issue242-capabilities-20260915` 因预算锁文件所有权错误停止，0 请求、12 NOT_RUN、已清理；[首次失败证据](startup-failure/result.json) 与日志保留。修正本轮文件所有权并以实际 UID 10002 离线验证后，恢复沿用原授权、账本和截止时间，没有重复任何模型请求。

## 12 个场景与观察结果

| 场景 | 业务结果 | 实际观察 |
| --- | --- | --- |
| natural_status：自然语言订单/状态/秒级事实 | PASS | 86399 秒/23 小时，无提案；正文遗漏所问状态和时长 |
| natural_proposal：处理方案与秒级阈值 | PASS | 259201 秒/72 小时，9.90 元模拟部分退款待审批；正文确认未执行，但方案细节不足 |
| ambiguous_order：缺信息澄清后调查 | FAIL | 初次无候选、无票；补充后正确建物流票；行动请求失败，无 Agent 正文，转人工 |
| clarification_denied：否定疑似扣款 | NOT_RUN | 触发未知用量停止 |
| split_asserted：同订单明确两个问题 | NOT_RUN | 同上 |
| two_orders：跨订单保留上下文 | NOT_RUN | 同上 |
| payment_affirmed：澄清后肯定两笔扣款 | NOT_RUN | 同上 |
| payment_refunded：已全退仍疑似重复扣款 | NOT_RUN | 同上 |
| followup_details：客户追加后第二代处理 | NOT_RUN | 同上 |
| human_preference：自然语言要求人工 | NOT_RUN | 同上 |
| supplemental_help：规则/知识/未知送达时刻 | NOT_RUN | 同上 |
| signed_not_received：签收未收到，旧行动路径 | NOT_RUN | 同上；旧路径未获得本轮能力证据 |

受理前后及确认快照、全部公开对话、事实、命令、代次、提案、失败文本均在 [data.json](data.json)；[cases.csv](cases.csv) 适合按例筛选。未运行案例保留完整行，不按零耗时、零费用或语义满分处理。

### 自主行动与知识

三个调查各执行了 5 项程序必需读取，共 15 项 `PROGRAM_REQUIRED`。成功的两个行动模型均选择 `SUBMIT_CONCLUSION`，第三次没有可用选择；本轮没有观察到模型选择补充调查工具或知识搜索。不能把 15 次程序读取当作模型自主选工具的成绩，也不能由两次提交选择推出复杂规划能力。知识、否定、多订单、多轮追加及自然语言人工偏好均缺少本轮完整证据。

## 时延

| 指标 | 样本数 | P50 | P90（nearest-rank） |
| --- | ---: | ---: | ---: |
| 初次受理点击 → 受理响应 | 3 | 4.525 秒 | 4.557 秒 |
| 首次确认 → 首代终态 | 3 | 9.394 秒 | 9.824 秒 |
| 确认 → 页面首次观察到回复区域 | 2 | 7.397 秒 | 7.796 秒 |
| 整例浏览器执行 | 3 | 16.543 秒 | 17.445 秒 |
| 受理角色完整供应商请求 | 4 | 2.507 秒 | 2.779 秒 |
| 行动角色完整供应商请求 | 3 | 3.023 秒 | 3.213 秒 |
| 判断角色完整供应商请求 | 2 | 1.197 秒 | 1.344 秒 |
| 回复角色完整供应商请求 | 2 | 3.559 秒 | 3.659 秒 |

终态时延包含一次失败交人工，不能叫“成功解答时间”。回复区域时点由页面观察器近似采集；模型时延是请求至完整响应/异常，不是首 token 时间。整例包含登录、SQL 采集、断言与刷新，不是模型纯耗时；数据库固定业务时钟不用于这些计算。小样本不报告生产 P95、吞吐量或稳定性承诺。

## 请求、token 与费用

| 角色 | 请求数 | 已知 token | 已知费用估算 |
| --- | ---: | ---: | ---: |
| 受理 | 4 | 5443 | 0.061695 元 |
| 行动 | 3（含 1 次未知用量） | 4407 | 0.046917 元 |
| 判断 | 2 | 580 | 0.006048 元 |
| 回复 | 2 | 2171 | 0.029511 元 |
| 合计 | **11** | **12601（不完整）** | **0.144171 元（不完整）** |

10 次 SETTLED，1 次 PENDING；未知用量预留 **0.169686 元**，IN_FLIGHT 为 0。预留加已知估算为 0.313857 元，用于预算占用核对，**不是实扣费用**。整轮完整 token、完整估算和供应商账单均未知。价格使用执行前核对的 [DeepSeek 官方 Pro 非缓存输入/输出价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)，按输入 9、输出 27 微元/token 保守估算，未把缓存折扣当作已结账单。

全部 11 次请求由持久账本与独立采集交叉核对并通过 intake/ticket/generation ID 关联，无时间窗归属、无遗漏来源、无未归属请求、无逐请求计量不一致。`independentMetricsReconciliation=false` 是因为未知用量仍存在，不表示把未知费用算零后对账通过。逐请求耗时、HTTP、模型、schema、usage 与预留见 [attempts.csv](attempts.csv)、[账本](raw/ledger.final.json)、[独立计量](raw/metrics.json)。

## 失败诊断与交付边界

第 11 次行动请求耗时 3023ms，分类 `TRANSIENT_PROVIDER_ERROR`，没有 HTTP 状态、响应 ID、响应终态或 usage。[行动适配器](../../../agent/src/baseline_agent/deepseek_investigation_action_model.py) 的 `TimeoutError/httpx.TransportError` 分支符合此记录形态，HTTP 429/500/503 分支则会保留状态。可确认的是客户端传输/超时类异常，没有取得完整响应；异常子类未保留，不能再区分连接超时、DNS/TLS、读取或连接中断，更不能断言 DeepSeek 停机或令牌失效。系统保留未知预留并停止后续付费请求，图把 `MODEL_CALL_FAILED` 泛化映射为 `INVALID_MODEL_OUTPUT` 交人工；该原因名称不证明模型返回了非法 JSON。没有发布失败正文，该兜底不算自动调查成功。

本轮暴露的正文信息不足属于需要诚实记录的模型表现；本次没有增加正文关键词拦截或调整提示来重跑提高分数。遵守 [ADR 0011](../../adr/0011-structured-authority-and-free-reply-text.md)，业务权限仍由结构化事实和 Spring 决定。

两项产品修复、聚焦红绿测试及真实浏览器 7/7 结果见 [Issue #242 交付记录](../../delivery/issue-242-project-audit.md) 和 [验证证据](verification/)。真实能力评测保持未完全通过；正式离线完整门禁、集中风险审查和双轴结果在 [PR #243](https://github.com/Stellogic/customer-agent/pull/243) 关联，只有完整门禁通过后合入。Issue #149 不在本次问题判定范围内。

## 数据文件与再汇总

```powershell
python docs/eval/2026-09-15-agent-capabilities/summarize.py --raw docs/eval/2026-09-15-agent-capabilities/raw
```

该命令只读取仓库已有证据，不调用模型。自动生成的 summary/data/cases 保持 `semanticReviewStatus=PENDING`，人工评审结果独立记录在 semantic-review 文件，避免把人工判断混入自动重算。原始 [result.json](raw/result.json) 的能力接受状态仍为 null，不改写运行时结果。

原始 Playwright 报告内保留本机 trace 路径；含浏览器会话信息的 trace 不发布。三张 [现场截图](screenshots/) 是每例 finally 中刷新后的原始画面：前两张可能处于身份恢复状态，不能当作正文截图；成功正文可见性由真实浏览器断言和公开快照支持。数据仅含本轮合成业务，不包含 API 密钥或模型自由推理。原始本机证据位于 `.local/gate-evidence/issue242-capabilities-20260915-resume/`。
