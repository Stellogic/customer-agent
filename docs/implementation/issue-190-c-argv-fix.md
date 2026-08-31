# Issue #190 单次诊断入口传参修复

2026-08-31；[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [Draft PR203](https://github.com/Stellogic/customer-agent/pull/203)。本阶段获准最小工程修复与离线验证，**不授权真实API调用**。

## 变更与真实接缝

`scripts/knowledge-sufficiency.ps1` 仅将模式参数改为显式 `[string[]]$modeArgs = @()`，诊断模式追加完整的 `--diagnose-fifth-once`。它修复[上一轮实际入口前置失败](issue-190-c-fifth-diagnostic.md)中PowerShell单元素输出解包、native splat按字符展开的问题。Python源码、冻结请求/prompt/schema/模型/数据及预算规则均无变更。

新增 `scripts/test-knowledge-sufficiency-entry.ps1`，在继承的真实共享锁下调用实际 **pwsh→uv→Python** 入口，分别验证普通开发与诊断模式。它清空API key和其他真实运行开关、使用UV/HF离线模式，要求两模式均非零退出且命中Python `MISSING_API_KEY`，排除 `unrecognized arguments`，同时不产生运行报告目录。该异常在argparse之后、账本构造/HTTP之前，所以测试覆盖真实传参而不会创建开发/诊断阶段或调用供应商。没有替换产品runner、假模型或新增生产测试开关。

## RED / GREEN 与证据

base均为 `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。

| RunId | 受测源码 | 实际结果 |
| --- | --- | --- |
| issue190-c-argv-offline-20260831a | e86ca3e（只增加回归，未修复入口） | 普通模式到MISSING_API_KEY；诊断模式复现参数逐字符拆分，预期RED |
| issue190-c-argv-offline-20260831b | **366985c6a12d6ec574604fb2499191daca321244**，工作树干净 | 两种入口均到MISSING_API_KEY；17聚焦/36相关离线组件、Agent Ruff lint/79文件格式、Pyright 0 errors、PowerShell语法PASS |

GREEN总阶段49.1598902秒，其中两入口回归9.0236217秒；pytest聚焦1.17秒、组件15.17秒。36项组件已包含17项聚焦，不能重复计数。离线入口回归预期子进程非零退出，其日志不是新模型失败；其PASS表示到达指定前置断点，不等于真实响应或质量通过。

[证据索引与完整日志/XML](evidence/issue190-c-argv-offline-20260831/index.json)保留RED与GREEN、两个模式的实际Python错误日志、起始SHA/base/耗时、preflight脚本副本；仅替换日志中的本机worktree路径，同时记录原始与归档SHA。没有隐瞒首次测试失败或事后补造原始模型输出。

环境沿用Windows/已有CPython3.13.13、已有uv虚拟环境，没有安装下载。工具精确版本和CPU/内存峰值本轮未采集；这些耗时是本地工程验证，不能用作供应商延迟/生产性能。代码与回归由Codex按用户授权执行，不冒称用户逐行手写。

## 账本、锁与剩余权限

真实API请求0、新增付费0。GREEN结束只读核对原共享账本SHA仍为 **5cd9e0ef8ee6977f0897db31d4c00bfee498194b9456bc437ffe0776b79e8507**，与原5次请求后的快照逐字节一致；累计费用上界0.009084元、未结算0。开发STOPPED、5请求/4完成/metrics=null、第5次NOT_CAPTURED，以及前次单诊断入口PRECONDITION_FAIL均保留，没有新增诊断phase。

RED/GREEN每次结束均finally释放自有锁，只读确认一次FREE并成功发送LOCK_RELEASED。GREEN结束窗口已归还，随后仅归档推送；真实诊断仍等待协调重新放行。未执行72题、留出/#189、默认策略切换、最终完整门禁或合入。

## Standards

PASS（静态）@366985c，0项缺陷。显式字符串数组保留诊断开关为单个参数，未改变方法或预算。新测试复用真实PowerShell→uv→Python入口，要求继承锁、清空key；两模式均非零退出并命中MISSING_API_KEY，同时排除参数解析错误与报告目录生成，符合账本/HTTP前停止边界。审阅未运行测试或查询锁。

## Spec

PASS（静态）@366985c，0项缺陷。参数数组修复范围仅传参；新增回归调用实际入口，清空key，并检查两模式都在参数解析后MISSING_API_KEY停止、不创建报告目录。未改变Python判定、冻结请求、数据或共享预算，原STOPPED历史不变。审阅未运行回归、查询锁或调用模型。

两轴各0项未决。文档归档提交不改变受测源码，也不是新运行证据；本次工程PASS不能代替真实单次诊断或质量门。
