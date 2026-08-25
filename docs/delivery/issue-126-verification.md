# Issue #126：DeepSeek Flash 真实业务 shadow 验证

## 范围与安全边界

本票只在独立 Compose project 中，将已经通过 Issue #125 真实契约准入的
`deepseek-v4-flash` 接入合成工单 shadow。Spring 的既有 fake 路径继续产生权威业务结果；
真实模型只生成脱敏 comparison，不提交结论、不创建补偿提案、不解决工单、不发送消息，
也不改变 Agent 处理代次。

真实验证只从启动进程继承 `DEEPSEEK_API_KEY`，脚本不读取 `.env`。密钥、prompt、
供应商响应正文、工单或订单标识、LangGraph thread/run/checkpoint 标识、供应商 response ID
均不进入报告、日志或仓库文件。Agent Server 是唯一连接专用 `provider-egress` 网络的服务；
Spring 与 PostgreSQL 仍只连接内部网络。

## 固定边界

- 真实场景：正常、精确二十四小时边界、二十四小时内无资格。
- 离线故障场景：模型拒绝、read timeout、非法 JSON。
- 每个真实场景最多一次供应商尝试，不重试、不切换模型；本批真实请求上限为 6。
- connect timeout 为 3 秒、read timeout 为 12 秒、单次 deadline 为 20 秒。
- Spring 代次终态后，最多用 10 秒有界等待 LangGraph 最终脱敏 comparison；超时即阻断。
- 401、402、403、429、5xx、网络、超时或供应商 `failed` 状态立即停止；402 单独标为余额不足。

## 本次真实证据

2026-08-25 在一次受控进程中只读取 `D:\customer-agent\.env` 的 DeepSeek key 与模型配置，
校验模型为 `deepseek-v4-flash` 后运行。真实调用 3 次、重试 0 次；三次 HTTP 状态均为 200，
公开 failure classification 均为 `NONE`，contract-valid comparison 为 3/3，fake 与真实判断
匹配 3/3。六个真实/故障场景的业务副作用不变量率为 1.0。

聚合结果：match rate 1.0、failure rate 0.0、P50 931 ms、P95 934 ms、usage/cost 可测率
1.0、平均成本 0.000025756 USD。离线故障分类分别为 `MODEL_REFUSAL`、`READ_TIMEOUT`、
`INVALID_JSON`，均未进入真实供应商调用。Issue #125 前置契约有效，冻结门槛全部通过，
`admittedForFormalMode=true`，无阻断原因。

机器可读的脱敏证据见
[`issue-126-shadow-report.json`](./issue-126-shadow-report.json)。该文件只包含聚合调用计数、
公开分类、comparison 汇总、延迟、usage、成本、冻结配置与 admission 结果。

## 验证

离线 TDD 先复现了 Spring 代次终态已可见、LangGraph 最终 comparison 尚未可见时的一次性读取
竞争；修复为 10 秒有界轮询后，隔离 Compose 离线链路的 3/3 comparison 均可读回。

提交前执行：

```powershell
pwsh ./scripts/check.ps1
```

该完整门禁覆盖真实 PostgreSQL、真实 LangGraph、Spring 业务路径、Agent、后端、前端与浏览器验收。
