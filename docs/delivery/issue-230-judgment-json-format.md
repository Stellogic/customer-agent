# 判断输出格式的最小提示修正

2026-09-08核对 [Responses API参考](https://api-docs.deepseek.com/api/create-response/)及[兼容性指南](https://api-docs.deepseek.com/guides/responses_api)：参考列出 text.format 的 json_schema，指南称 format 完整支持。参考未单列 strict 字段，不能据此断言该字段被忽略，也不能将本地 strictSchemaRequested 视为服务端强制约束证明。[JSON Output指南](https://api-docs.deepseek.com/guides/json_mode/)建议明确要求JSON并提供输出示例；它的示例使用Chat Completions，不直接证明Responses的运行行为。

真实 matrix04 已捕获判断输出以代码围栏开头；正文未保存，无法离线重放原始内容。现有代码围栏拒绝测试可复验解析和审计边界，不能证明提示修改能消除真实模型波动。

本次只将 investigation-judgment 提示升为v2：要求一个符合schema的JSON对象，明确不是schema本身、禁止Markdown及外围文字，并给出86400秒与86399秒对应的两种合法结果示例。schema版本仍为v1，业务门槛、模型、接口、解析、重试和预算逻辑不变。

当前无需据此更换供应商。先用已有离线适配器测试确认请求/严格拒绝路径，再冻结一个待审批样本进行真实验证。若仍出现格式违约，停止本轮，不继续反复调提示；再比较官方JSON模式或严格工具调用的接入成本及其他供应商。单样本通过也不代表十样本矩阵完成。

离线验证：29项判断适配器测试通过；规范化Agent首轮发现两处旧提示版本断言，修正后 issue230-judgment-v2-agent02 为579通过、3跳过，格式/静态/类型检查通过。Standards与Spec（含版本断言增量）均PASS。此结果不证明真实模型格式稳定。

## 单样本真实验证结果

issue230-real-judgmentv2probe01 受测提交e248958c6952f00ddc395e9f3ccaac20b6ec22f2，仅运行待审批样本1；结果0通过、1失败、9未运行。判断v2此次成功并进入回复，所有四角色返回均通过响应形状检查；这只说明本次未复现JSON错误，不证明格式稳定。

失败发生在结论提交之后：调查保存communication/FACT_CONFLICT并以HANDED_OFF结束。graph.py对此路径将非可修正知识问题的Spring HTTP422统一归为FACT_CONFLICT，现有metrics没有具体拒绝码或待提交回复原文，不能断言模型编造事实、具体字段错误或业务规则误拒。下一步应先补齐受控Spring拒绝码诊断，不继续付费重跑或据此更换供应商。

本轮4次调用、4346 token，全部SETTLED；估算0.047880元，历史累计0.468048元，3元预算估算余额2.531952元。供应商实际账单未知，未完成预留0、缺失证据源0，资源清理通过。未批准或执行补偿。#230仍未完成，#174继续暂停。
