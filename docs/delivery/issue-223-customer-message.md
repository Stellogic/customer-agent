# #223 受理原话与自动解决判断

工单摘要与客户原话原先共用 description；合法的模型改写可能让白名单问题失去资格，也可能掩盖真实诉求。内部 CreateCustomerTicket 现在分开 description 与 customerMessages：摘要仍作为工单描述，有序 CUSTOMER 消息逐条保存受理 transcript 中有序客户原话（排除当前确认动作）；跟进工单沿用其客户新消息。

调查沟通上下文和自动解决政策读取工单 CUSTOMER 消息，摘要仅在没有客户消息的历史记录中兜底。争议检查读取完整原文，问题匹配仅去除与当前权威订单完全一致的表单固定前缀“订单 <reference> 的物流延迟问题：”。原有问题白名单、补偿和证据校验不变。

回归覆盖摘要/原话分开写入、调查上下文使用原话、表单前缀以及补偿负例。新增 smoke 通过真实 v4 受理 API 提问、单独补充“请立即补偿”、确认，并逐条读回工单原话；随后用该原话和非白名单摘要验证 Spring 结论是否生成候选。该确定性 smoke 不调用真实模型，不能代替 #174 真实发布验收。

交付合并至 PR #222，统一包含 #217 输出额度、#219 流分片、#221 调查类型上下文、#223 原话来源。最终完整门禁尚待运行；GitHub 自动审查按用户要求不作为阻塞。


## 聚焦与静态验证

`issue223-component-b`：Agent Ruff / Pyright 通过，pytest 465 passed、3 skipped（34.24 秒）。消息边界增量后的 `issue223-component-c`：后端 `gradle check` 通过（含格式、Checkstyle、测试），变更 Python 文件格式和 Ruff 检查通过。两个专用运行的容器及精确镜像标签已清理。Standards / Spec 已分别确认增量修复；最终完整本地门禁尚待运行。

首次完整门禁 `issue221-final-20260905a` 在已新增的 smoke 原文断言处失败：去重按钮通过 transcript 记为 CUSTOMER 的“作为新问题继续创建”混入真实发言。查询现限定首条原话或能匹配实际 customer_intake_message 的记录，并保留 ordinal 顺序和当前确认排除。失败记录保留，未签发通过证据；本轮专属资源及精确镜像标签已清理、锁 FREE。修正后重新验证，不复用失败轮次。

`issue223-component-d` 的后端格式、Checkstyle、测试全部通过，变更 Python 静态检查通过；Standards / Spec 分别确认真实消息来源修正。随后在新提交运行完整门禁。

第二轮完整门禁 `issue221-final-20260905b` 已通过原话读回正例，但受理补充触发 STATE_CONSISTENCY：FixedFakeIntakeModel 把补充内容重写为既有 issue.summary，违反 Spring 保留 currentIssues 前缀的契约。一行修正使摘要仅在首次识别时生成；真实模型路径未改。

定向运行 `issue223-intake-focused`：受理模型 13 项测试通过（0.52 秒），Ruff 通过；隔离 Spring/Agent/PostgreSQL 实际受理、确认、调查两条路径均通过：无补充时一条客户原话且候选存在，单独补偿补充时两条客户原话且无候选。没有调用真实供应商。专属容器、卷、网络和精确镜像标签已清理。本次确定性主链路已验证，最终完整门禁使用新提交重跑。
