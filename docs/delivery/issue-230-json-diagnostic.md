# 调查判断 JSON 失败诊断

调查判断适配器原来将 HTTP 响应体与模型输出文本的 JSON 解析失败都归为 INVALID_JSON，无法区分具体失败位置。现在沿用现有 validationDiagnostic 审计字段，补充：

- stage：HTTP_RESPONSE 或 OUTPUT_TEXT。
- offset、line、column、textLength：解析位置与文本长度。
- framing：CODE_FENCE、JSON_CONTAINER 或 OTHER，仅表示开头格式特征。

这些信息不会保存响应原文、原始异常消息、提示词或思维链。JSON_CONTAINER 不代表 JSON 合法，CODE_FENCE 也不会触发自动去除围栏或修复；解析与转人工规则、调用次数限制保持原样。HTTP外层无用量时继续未知，模型输出文本错误仍保留供应商已返回的用量。

此前真实失败没有这些字段，不能反推它具体属于哪种格式，也不能由这次诊断增强宣称已经修复模型输出。下一次受控运行需使用新提交并另行冻结计划；本次只执行离线检查，#230仍未通过真实矩阵，#174继续暂停。
