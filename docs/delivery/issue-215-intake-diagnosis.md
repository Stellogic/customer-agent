# #215：受理澄清推进诊断

## 当前结论

`intake-v3` 已通过约定的真实双问题受理路径：识别包裹问题并保留疑似重复扣款，澄清后完整列出两项，最终统一确认创建两张工单，全程没有受理协助。实际三次请求，未追加稳定性测试。历史错误转人工的具体原因仍未确认；不能把这次成功当作其根因证明。

按用户要求，不追求多轮稳定性证明，不扩展边界测试。但普通输入中的问题遗漏和澄清不推进不能算作通过。

## 2026-09-04 修复范围对齐

用户已确认的目标、局部修复范围和验收标准整理为[最小修复约定](issue-215-fix-scope.md)。它是本票的轻量实施记录，不新增正式规格层级。本轮对齐未执行新模型调用。

## intake-v3 局部实现

- 首次受理要求模型逐项评估支持的问题类型，区分客户明确陈述、客户不确定和未提及；代码将不确定的问题保留为待澄清项。这不证明模型绝不会误判，真实语义仍由浏览器路径验证。
- 已有订单的澄清回复只让模型判断 `AFFIRMED`、`DENIED` 或 `UNCLEAR`，代码保留已有问题，按判断推进当前队列头。队列清空后进入待最终确认，不自动建单。
- 已准备浏览器诊断 v3：允许首次直接待确认，最多两次澄清，最终点击统一确认并验证两张工单及共同受理记录。仍沿用真实受理模型，无 fake 回退。
- 诊断04冻结最多四次受理请求、不重试、预留 0.10 元。隔离环境将后续调查派发间隔延长到一小时、调查模型预算设为零；本次不评价建单后的调查质量。此设置不修改产品默认值。
- 离线模型适配器回归四项、前端判据八项通过；这些测试不作为真实模型理解质量的证据。Standards / Spec 静态审查无阻断发现，规范化检查和真实验证结果另记。

## 真实观察

| 运行 | 观察 | 结论 |
| --- | --- | --- |
| 诊断01，原提示 | 首次已形成包裹问题，只待澄清重复扣款；无人工协助。原诊断判据要求两项都待澄清，因而停止，未发送追加请求 | 判据过窄，不是产品失败证据 |
| 诊断02，原提示 | 首次两项待澄清；正确回答包裹问题后仍两项待澄清、零拟建问题。两次 HTTP 201，无人工协助和受控校验失败 | `PROGRESS_MISMATCH`，正常澄清未推进 |
| 诊断03，intake-v2 试验 | 首次零拟建问题，仅包裹未收到待澄清，重复扣款既不在拟建问题也不在待澄清队列。HTTP 201，无人工协助。未发送第二次请求 | `INITIAL_PRECONDITION_FAILED`，普通多问题输入存在遗漏；新提示不能算修复成功 |

- 诊断01：[冻结](issue-215-intake-diagnostic-01-freeze.json)、[结果](issue-215-intake-diagnostic-01-result.json)、[分类](issue-215-intake-diagnostic-01-classification.json)。
- 诊断02：[冻结](issue-215-intake-diagnostic-02-freeze.json)、[结果](issue-215-intake-diagnostic-02-result.json)、[分类](issue-215-intake-diagnostic-02-classification.json)。
- 诊断03：[冻结](issue-215-intake-diagnostic-03-freeze.json)、[结果](issue-215-intake-diagnostic-03-result.json)、[分类](issue-215-intake-diagnostic-03-classification.json)。
- 诊断04：[冻结](issue-215-intake-diagnostic-04-freeze.json)、[结果](issue-215-intake-diagnostic-04-result.json)、[分类](issue-215-intake-diagnostic-04-classification.json)。首次包裹问题已拟建、重复扣款待澄清；肯定回复后两项待确认；统一确认后两张工单。三次 HTTP 201，受理协助均为零，结论 `INTAKE_CREATION_PASS`。

这三轮都没有出现人工协助，不能将其等同于 #174 诊断04的错误转人工；也不能据此否认历史故障。源码冻结包含 fingerprint 与 `uncommittedChanges=true`，不把 HEAD 单独当作被测源码。旧 #174 冻结和失败报告未修改。

## 保留的诊断改动

- 网关异常区分 `TRANSPORT`、`RESPONSE_PARSE`、`STATE_CONSISTENCY`；现有服务层异常标为 `SERVICE_VALIDATION`，外层 catch 不覆盖已分类原因。
- 现有转人工分支仅记录阶段与原因码；状态一致性拒绝另记录已校验的 intent/status 枚举和问题数量。不保存原始响应、客户内容、订单标识、异常正文或密钥。
- 浏览器诊断 v2 接受“两项待澄清”和“一项已确定、一项待澄清”两种合法起点。正确回复须只推进队列头、保留已有问题和尾部；队列清空则进入待最终确认，不点击建单确认。
- 没有放宽 `hasConsistentShape` 或 Spring 业务校验，没有更换模型、增加架构/依赖或 fake 回退。

## 提示试验与撤回

代码检查未发现页面回复或队列在 React → Spring → LangGraph → 模型请求之间漏传。曾尝试把模糊的 resolve 队列头规则明确为：肯定回复新增该问题、否定回复移除该项、含糊回复才继续问；保留已有问题和摘要，澄清不等于最终建单确认。

该试验版本为 `intake-v2`，但诊断03首次受理即遗漏重复扣款，无法证明修改有效。试验改动已撤回；差异保存在本地 `issue215-intake-diagnostic-03/intake-v2-trial.patch` 证据目录。不能把这次试验标成产品修复。

## 费用与资源

用户分别明确授权了原提示和新提示试验向 DeepSeek 外发同一合成场景。每轮独立 RunId、最多初次受理和一次追加、预留 0.10 元；旧预留全部保留，没有自动重跑同一 RunId。

诊断04在用户明确允许新版外发后执行，最多四次请求、实际三次，包含最终建单确认；另预留 0.10 元。当前已结算 3.810222 元，十笔 PENDING 共 2.80 元，占用上界 6.610222 元，距 8 元上限尚未预留 1.389778 元。PENDING 不是实际账单，provider usage 未完整取得。

四轮拥有的 Compose 容器、网络、卷和门禁镜像均清理并回读为空，脚本报告 `LOCK_RELEASED`。诊断 runner 保留已执行的第四轮冻结，不能直接重用。

## 验证状态

- 保留的诊断能力：后端聚焦 34 项、前端判据 7 项通过；格式、类型、日志统计和浏览器清单检查通过。
- 后端规范化组件检查通过：`issue215-backend-diag-check-02`。
- 提示试验曾通过 Agent 规范化组件检查：448 passed、3 skipped，Ruff/Pyright 通过；这不代表真实模型有效。撤回后 Agent 三个文件与原基线一致。
- intake-v3 Agent 规范化组件检查：`issue215-agent-v3-check-02`，452 passed、3 skipped，Ruff/Pyright 通过。前端全量离线测试 234 passed、3 skipped。
- 真实模型正常路径：诊断04通过，统一确认后两张工单，共同受理关联已验证。
- Standards / Spec 静态审查均无阻断发现；包括诊断04的调用次数、预算及隔离配置核对。
- 离线完整检查 `issue215-v3-offline-01/02` 在 #162 后台任务输出 Docker 正常进度 `Creating` 时退出。PowerShell 7.6.5 最小复现证实：原生命令退出 0，但 stderr 经后台任务传给 `Receive-Job -ErrorAction Stop` 后仍抛异常。已在该命令末尾添加 `2>&1`；正常退出可通过，非零退出仍由原有检查抛错。以 `issue215-v3-offline-03` 补跑完整检查，不追加真实模型测试。
- 完整检查 `pwsh ./scripts/check.ps1 -Issue 215 -RunId issue215-v3-offline-03` 通过，退出码 0：三组件检查、集成 smoke、RAG 检索门禁、59 项常规浏览器用例及分阶段重启/到期验收均通过，自有容器、网络、卷和门禁镜像已清理。原始日志保存在本工作树 `.local/issue215-v3-offline-03.log`。
- 本次验证针对 `c28971e` 上的工作树改动；本记录不作为 PR 已合入或 Issue 已关闭的证明。
