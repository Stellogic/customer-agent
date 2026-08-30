# Issue #190 原第5次请求的单次诊断

2026-08-31；[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [Draft PR203](https://github.com/Stellogic/customer-agent/pull/203)。这是协调明确授权的**一次诊断，最多1次真实API请求**，不是恢复72题、质量评测或产品策略切换。

## 固定边界与接缝

原开发记录仍为[attempt-a](issue-190-c-development-attempt-a.md)：STOPPED、5次请求、4/72合法完成、metrics=null，第5次原文NOT_CAPTURED；不修改这些历史证据。

- 仅使用固定开发归档的第5项 `weaving-direct-3`，复用原 `request_body` 和相同UTF-8 JSON序列化。发送字节SHA必须为 `d3a9e630949ed0093103ac435db610d9eacd9115c92be2e750be5914b056e20b`，否则在写入诊断阶段或发送前停止。没有新增请求字段或修改prompt/schema/模型/Top5。
- 原账本归档SHA为 `5cd9e0ef8ee6977f0897db31d4c00bfee498194b9456bc437ffe0776b79e8507`。首次诊断前共享账本完整状态必须与该固定快照一致；账本不存在、原历史变化、费用或合同变化均停止，不创建替代历史。
- 原 `seen_development` 保持STOPPED。新增固定 `fifth_request_diagnostic_once`，使用独立opt-in `issue-190-fifth-request-diagnostic-once`。这个阶段只允许1次预留/请求；阶段一旦开始，不论成功、失败或进程中止，换RunId均不能重开。没有重置/清理STOPPED或一般续跑入口。
- 复用原HTTP请求、解析、身份漂移检查、有界脱敏取证、预留和结算代码。可信usage结算，未知usage留预留并停止；无重试或其他API调用。新增费用计入原共享账本，原5次记录不修改。
- 成功仅标 `DIAGNOSTIC_COMPLETED`、metrics=null；失败保留STOPPED与错误码/脱敏证据。原开发完成数不加1，不产生诊断“准确率”或质量PASS。

入口为原 `scripts/knowledge-sufficiency.ps1 -DiagnoseFifthOnce`，Python同步要求 `--diagnose-fifth-once` 和独立opt-in。原真实共享锁、干净工作树和当前UTC价格确认仍必需；未授权者不应据此运行。

## 官方价格与预算确认

本轮于本地2026-08-31（UTC日期2026-08-30）再次只读核对[官方价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)：Flash高峰未缓存输入3元/百万token，输出9元/百万token；上下文1M。[官方Flash配置](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash/raw/main/config.json)为1048576位置。冻结输出帽仍为256；不推断更小计费输入上界。

原已结算上界0.009084元、未结算0；此次最大预留3.148032元，合计3.157116元≤6元。只会预留1次；可信usage后释放差额，未知usage保留全额。此预留不是预计实际费用。即使预算仍剩余，也不授权第二次请求。别名非不可变版本，继续记录实际返回模型/fingerprint并执行原漂移停止规则；缺fingerprint不包装成权重一致证明。

## 离线验证与审查

受测干净源码 **69115499462dadeed5a1f68797b6f7d46dadbaa9**，base **c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472**。RunId `issue190-c-fifth-offline-20260831b`：17项聚焦、36项相关离线组件、Agent Ruff lint/79文件格式、Pyright 0 errors、PowerShell入口语法均PASS，39.1219966秒。36已包含17项，非53项独立测试；pytest各1.11秒、15.33秒。工作树无格式增量。

新增离线回归覆盖合法/非法结构/未知usage的单次诊断、实际请求字节hash、原5历史与STOPPED不变、新RunId阻止再次发送、缺失历史拒绝和累计预算不足停止。使用MockTransport/临时账本，不是真模型比较。保留前一RunId `issue190-c-fifth-offline-20260831a` 的17聚焦PASS但Ruff拒绝未标raw测试正则的失败记录，修复未改变方法或运行契约。

[原始离线日志/XML索引](evidence/issue190-c-fifth-offline-20260831/index.json)同时保存原始/脱敏归档SHA及本次preflight脚本副本。环境为既有Windows/CPython3.13.13虚拟环境，无安装下载；脚本清空真实key，HF离线，使用既有certifi和仅子进程 `NO_PROXY=*`。本节离线阶段真实API0次/新增费用0元，机器成本/资源峰值未采集。两次运行结束均释放锁，单次回读FREE并成功通知LOCK_RELEASED；窗口保留至本次已授权真实诊断结束。

### Standards

PASS（静态）@6911549，0项缺陷。独立opt-in、固定phase及原第5次请求SHA约束单次调用；开始前校验共享账本与原归档一致，保留STOPPED和5次历史/累计费用。重复phase不因新RunId放行，复用原预留、结算、解析与取证；不计算质量、不恢复72题，无通用框架或冻结合同变更。审阅无运行或留出/#189读取。

### Spec

PASS（静态）@6911549，0项缺陷。发送前核对原账本、冻结合同、第5次请求字节SHA；独立阶段最多一次，换RunId不能重试。原STOPPED、5次费用及模型身份保留，新增费用仍计共享预算。成功DIAGNOSTIC_COMPLETED/metrics=null，失败沿原停止取证结算，无范围外修改。审阅无运行或留出/#189读取。

两轴各0项未决；归档文档提交不改变受测源码。实现与测试由Codex按用户授权完成，不等同于用户逐行手写或生产收益。

## 单次真实记录

本次入口与离线证据提交时尚未执行真实诊断；运行完成后在本节追加独立RunId、SHA/base、实际请求数、响应/脱敏失败、token/耗时和累计预算。无论结果如何停止归档并归还窗口，不继续72题、留出/#189、完整门禁或合入。
