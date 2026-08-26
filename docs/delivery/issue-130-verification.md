# Issue #130：DeepSeek Flash 与 Pro 完整合成评测

## 结论

继续使用 `deepseek-v4-flash`，不建议基于本次证据切换到 Pro。本票只评测，不修改正式模型配置，
也不创建切换票。

在完全相同的 `b0-synthetic-evaluation-v1` 数据集、`investigation-judgment-v1` 提示与
strict schema、关闭 thinking、单场景最多一次供应商尝试和相同计量口径下，Flash 的结构化输出、
业务正确与安全不变量均为 100%；Pro 分别为 95%、88.33% 和 95%。Flash 的 P50/P95 为
840/1242 ms，Pro 为 1547/1904 ms；Flash 本轮费用为 0.0094525 元，Pro 为 0.0325053 元。

这些结果只来自 2026-08-26 的合成客服调查判断评测，不能外推为生产客户效果、通用模型能力或
统计显著的长期排名。

## 公平性、预算与安全边界

- 固定候选只有 `deepseek-v4-flash` 与 `deepseek-v4-pro`；外部 `DEEPSEEK_MODEL` 会被拒绝，
  正式运行默认仍只允许 Flash，不自动切模、不回退 fake。
- 完整数据集为 12 个冻结场景重复 5 次，即每个模型 60 个场景。每轮有 5 个错误证据场景在本地
  输入白名单处被预期拒绝，因此每个模型实际产生 55 次、合计 110 次供应商尝试；重试为 0。
- 密钥只由 `scripts/deepseek-model-comparison.ps1` 从 `D:\customer-agent\.env` 读取到受控进程，
  不从其他文件或已有环境变量取值，不写入报告、日志、镜像或仓库。
- 总费用硬上限为 6 元。按当时官方空闲时段价格和每次 4096 输入/128 输出 token 的保守上界，
  运行前最坏费用为 1.4784 元；实测合计 0.0419578 元。任一供应商、余额、网络、计量或资源异常
  都会停止整轮比较。
- 价格于 `2026-08-26T12:59:16.757943Z` 从 DeepSeek 官方
  [模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)冻结：空闲时段 Flash 的
  缓存输入/未缓存输入/输出为 0.05/1.5/4.5 元每百万 token，Pro 为 0.15/4.5/13.5 元。
- 报告不保存原始 prompt、请求、响应、供应商 response ID、思维链或业务标识。机器可读脱敏证据见
  [`issue-130-model-comparison.json`](./issue-130-model-comparison.json)。

## 对比证据

| 指标 | Flash | Pro | Pro - Flash |
| --- | ---: | ---: | ---: |
| 结构化输出成功率 | 100% | 95% | -5 个百分点 |
| 业务正确率 | 100% | 88.33% | -11.67 个百分点 |
| 安全不变量率 | 100% | 95% | -5 个百分点 |
| 拒答或空输出率 | 0% | 0% | 0 |
| 失败率 | 0% | 5% | +5 个百分点 |
| P50 延迟 | 840 ms | 1547 ms | +707 ms |
| P95 延迟 | 1242 ms | 1904 ms | +662 ms |
| 输入 / 输出 token | 10065 / 1014 | 10065 / 1280 | 0 / +266 |
| 缓存输入 token / 命中尝试 | 7040 / 55 | 6912 / 54 | -128 / -1 |
| 总费用 | 0.0094525 元 | 0.0325053 元 | +0.0230528 元 |

两者所有成功响应均通过 strict schema、completed 状态、thinking 关闭、参数白名单、实际响应形状、
usage 与缓存计量检查。请求模型与响应模型分别一致为 Flash 和 Pro。供应商在两组各 55 次尝试中均未
返回 `system_fingerprint`；报告明确记录为各缺失 55 次，不伪造后端指纹。Pro 出现 3 次脱敏
`INVALID_OUTPUT` 计数，并在重复评测中有 7 个场景结果未同时满足结构、业务与安全判定；报告只保留
合成场景名和聚合分类，不保留模型正文。

## 求职证据摘要

以下内容适合说明一个个人全栈 Agent 工程的可核验过程，不应写成生产上线、真实客户规模或模型训练成果。

- #126 在真实 Spring/LangGraph/PostgreSQL shadow 中完成 3 次真实 Flash 调用：3/3 契约有效、
  3/3 与 fake 匹配，P50/P95 931/934 ms，平均 0.000025756 USD，真实与离线故障场景的业务副作用
  不变量率为 1.0。证据：[`issue-126-verification.md`](./issue-126-verification.md)、
  [`issue-126-shadow-report.json`](./issue-126-shadow-report.json)。
- #127 将已准入 Flash 提升为显式正式调查判断，成功路径经真实 LangGraph/PostgreSQL 进入 Spring
  权威复核；受控 401 路径证明不回退 fake、零补偿提案并安全转人工。完整门禁包含 Agent 147 项与
  Chromium 主矩阵 24 项。证据：[`issue-127-verification.md`](./issue-127-verification.md)。
- #128 真实自主调查完成 7 次逻辑调用/7 次供应商尝试，覆盖 5 类受控事实能力，估算 1056 micro-USD；
  另保留“重复行动 → `REPEATED_NO_PROGRESS` → 安全转人工”的 3 次尝试失败证据。预算进入 checkpoint，
  恢复不重置；Agent 168 项与 Chromium 24 项通过。证据：
  [`issue-128-acceptance.md`](../verification/issue-128-acceptance.md)、
  [`issue-128-formal-report.json`](./issue-128-formal-report.json)、
  [`issue-128-failure-evidence.json`](./issue-128-failure-evidence.json)。
- #129 最终澄清恢复链路以 11/11 逻辑调用/供应商尝试成功，估算 1749 micro-USD；客户沟通 2 次、
  3079 ms、661 micro-USD。历史失败依次暴露动态 schema 与领域解析器不一致、重复权威引用约束和
  浏览器固定文案断言，并以“保留失败证据 → 离线最小复现 → 修复 → 真实单路径复验/完整浏览器门禁”
  闭环；Agent 190 项、Chromium 主矩阵 24 项通过。证据：
  [`issue-129-acceptance.md`](../verification/issue-129-acceptance.md)及其链接的脱敏失败/复验报告。
- #130 用同集同参完成 110 次真实 Flash/Pro 调用、0 重试、0.0419578 元 usage 计量估算；Flash 在本次合成集上
  同时取得更高质量、更低延迟和更低成本，因此维持 Flash。实现后的 Agent 全套为 196 项通过。

准确的个人贡献边界可以表述为：设计并实现合成评测、供应商适配与 fail-closed 预算/契约防线，打通
LangGraph 调查、Spring 权威复核和 React 浏览器验收，并保留失败—修复—验证证据。不能表述为训练或
优化 DeepSeek 基座模型、处理真实客户数据、完成真实退款，或证明生产 SLA、商业转化和线上准确率。

### 简历候选表述

1. 在 React + Spring Boot + LangGraph 的合成客服 Agent 项目中，设计最小事实输入、严格结构化输出与
   Spring 二次权威校验；真实 Flash 自主调查以 7/7 模型调用完成 5 类受控事实采集，异常统一安全转人工。
2. 建立固定数据集的 DeepSeek Flash/Pro 横向评测与 6 元费用硬上限，完成 110 次真实调用、0 重试；
   本次合成集上 Flash 的结构/业务/安全指标为 100%/100%/100%，P95 1242 ms，总费用 0.00945 元。
3. 将 schema、预算、checkpoint 恢复、迟到代次围栏和浏览器授权投影纳入自动化门禁；通过保留脱敏
   失败证据和最小复现，修复动态 schema/解析器重复约束与脆弱文案断言，Agent 196 项测试通过。

### 面试展开要点

- **为什么不是“让模型决定补偿”**：模型只做受约束调查判断和行动选择；Spring 重新读取权威事实，
  独立计算资格、方式与金额，人工审批和执行始终不属于 Agent 权限。
- **最有价值的失败链路**：#129 不是反复调用直到成功，而是在首错即停后用脱敏 checkpoint 缩小范围，
  分离供应商输出、动态 schema、领域解析与浏览器断言，逐层最小复现并只复验获批路径。
- **如何保证 Flash/Pro 公平**：固定候选、场景顺序、提示/schema/thinking、token 上限、计价时段和一次尝试；
  同时报告响应模型、指纹缺失、usage/cache、质量、延迟与费用，不用模型名称或价格先验替代实验结果。

## 验证计划

提交前从仓库根目录使用唯一、非 baseline 且非 main-preview 的 Compose project/tag/端口运行：

```powershell
pwsh ./scripts/check.ps1
```

完整门禁结果、双轴审查、CI、PR 合并和 Issue 关闭状态在正式交付时补充。
