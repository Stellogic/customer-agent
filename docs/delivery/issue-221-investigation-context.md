# #221 调查类型与证据选择上下文

基于 origin/main@ca0977a。Graph 已持有 Spring 的 issue_kind，但原最终行动请求只传客户原话，模型没有权威工单类型。

单次合成适配器诊断 issue217-action-diagnostic-20260905a（整合提交 cad8d6d）返回合法 JSON，模型使用物流状态、支付/退款状态适用性，未声明延迟时长和订单资格。Spring 的 LOGISTICS_DELAY 政策明确需要后两项；因此该选择不满足该工单类型的证据要求。本诊断并非前轮浏览器422响应原文，也未复现另一轮 INVALID_JSON，不将三种观察混为同源。

修改只把 Spring 已确认的工单类型传入最终选择请求，并解释 JSON 对象格式和既有适用性枚举含义。提示版本为 investigation-action-v4，输出schema仍为v3；模型仍独立选择引用与适用性，宿主不补齐遗漏，Spring政策不变。模型、额度、重试也不变。#217、#219 为独立修复，整合复验时包含它们。

复用现有Graph回归验证默认与非默认工单类型被传入；复用现有HTTP MockTransport回归验证类型位于权威事实区，与客户原话分离。新回归、静态预检与最终完整门禁目前NOT_RUN；按用户要求先推送进行集中审查。真实完整主链路仍未通过，不宣称模型质量已经改善。

格式要求参考 [DeepSeek Responses API](https://api-docs.deepseek.com/api/create-response/) 与 [JSON Output 提示说明](https://api-docs.deepseek.com/guides/json_mode/)；原请求已使用json_schema，本次不降低结构或业务校验。

## 聚焦验证与真实链路观察

`issue221-context-focused-b` 的 Agent 静态检查通过（Ruff、Pyright 0 errors），整合工作树 pytest 466 passed / 3 skipped；54 项相关回归通过。产品代码在统一提交前与该整合提交核对一致，#174 工具测试独立保留。

单次 `issue221-live-20260905a` 测试整合提交 `403947f4bb13ab77187c8dbfaa15805e47ce41bf`：受理确认与单工单断言通过；调查行动 7 次、判断 1 次、回复 1 次，已知 7158 token。Spring 代次状态为 COMPLETED，未记录结论拒绝；浏览器仍未出现自动解决候选而超时，整场失败。COMPLETED 不等同于最终工单未转人工，也不等同于发布验收通过。聚合原始观察见 `issue-221-live-observation.json`。

随后源码核对发现 #223：模型摘要被写为 CUSTOMER 原话，且表单固定订单前缀与纯问句白名单不匹配。旧真实轮次未保留正文，不能断言这是该轮唯一原因。#223 在同一 PR 修复并用真实受理 API 与 Spring/PostgreSQL smoke 验证，避免继续不变配置的付费抽样。
