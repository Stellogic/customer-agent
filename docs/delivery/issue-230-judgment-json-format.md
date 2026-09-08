# 判断输出格式的最小提示修正

2026-09-08核对 [Responses API参考](https://api-docs.deepseek.com/api/create-response/)及[兼容性指南](https://api-docs.deepseek.com/guides/responses_api)：参考列出 text.format 的 json_schema，指南称 format 完整支持。参考未单列 strict 字段，不能据此断言该字段被忽略，也不能将本地 strictSchemaRequested 视为服务端强制约束证明。[JSON Output指南](https://api-docs.deepseek.com/guides/json_mode/)建议明确要求JSON并提供输出示例；它的示例使用Chat Completions，不直接证明Responses的运行行为。

真实 matrix04 已捕获判断输出以代码围栏开头；正文未保存，无法离线重放原始内容。现有代码围栏拒绝测试可复验解析和审计边界，不能证明提示修改能消除真实模型波动。

本次只将 investigation-judgment 提示升为v2：要求一个符合schema的JSON对象，明确不是schema本身、禁止Markdown及外围文字，并给出86400秒与86399秒对应的两种合法结果示例。schema版本仍为v1，业务门槛、模型、接口、解析、重试和预算逻辑不变。

当前无需据此更换供应商。先用已有离线适配器测试确认请求/严格拒绝路径，再冻结一个待审批样本进行真实验证。若仍出现格式违约，停止本轮，不继续反复调提示；再比较官方JSON模式或严格工具调用的接入成本及其他供应商。单样本通过也不代表十样本矩阵完成。

离线验证：29项判断适配器测试通过；规范化Agent首轮发现两处旧提示版本断言，修正后 issue230-judgment-v2-agent02 为579通过、3跳过，格式/静态/类型检查通过。Standards与Spec（含版本断言增量）均PASS。此结果不证明真实模型格式稳定。
