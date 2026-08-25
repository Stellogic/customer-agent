# Issue #122：独立客户沟通模型与安全回复 envelope 验证

## 交付范围

- LangGraph 新增独立于调查判断的客户沟通模型接口，输入、输出、失败类型和离线评测均独立定义。
- 普通 CI 固定使用 `FixedFakeCustomerCommunicationModel`，不读取供应商配置，也不调用真实 LLM API。
- 输出冻结为 `customer-reply-v1`，只包含客户可见正文、回复意图、证据引用、转人工标志和被引用订单。
- Graph 在提交调查结论前生成并校验 envelope；沟通模型异常或非法输出复用 `INVALID_MODEL_OUTPUT` 转人工路径，不提交结论、不发送消息。
- Spring 在一个权威事务中同时复核调查结论与客户回复，校验通过后才沿用 `public_message` 与 `customer_public_event` 公开投影，并保留既有解决事件与 SSE 顺序。

## Spring 发送前防线

Spring 控制器要求结论与 `customerReply` 均具有精确字段集合；额外的供应商字段、内部字段或未知 schema 会在进入业务服务前拒绝。业务服务在持有工单权威锁后重新读取并验证：

- 当前 generation 必须是该工单编号最大的 `ACTIVE` generation；
- 工单必须仍为 `AGENT`、`INVESTIGATING` 且客户未表达人工偏好；
- envelope 的订单、意图和证据必须与 Spring 当前权威订单及证据范围完全一致；
- 不允许自动发送转人工 envelope、金额、正向补偿或退款承诺、其他订单引用；本票只启用确定性 fake，Spring 因而进一步要求正文精确匹配按 intent 和当前订单参数化的 `customer-reply-v1` 安全模板，不把开放自由文本的黑名单识别当作权威防线；
- 校验、政策计算、generation 完成、生命周期迁移和公开消息写入位于同一事务，拒绝路径不会调用公开消息投影。

## 确定性验证

2026-08-25 已执行：

- `docker build --target test --tag customer-agent/agent-test:issue122 agent`
  - Ruff format/check 通过；
  - Pyright：`0 errors, 0 warnings, 0 informations`；
  - Pytest：`108 passed`。
- `docker build --target test --tag customer-agent/backend-test:issue122 backend`
  - Java 编译、Spotless、Checkstyle 通过；
  - Gradle `check`：`BUILD SUCCESSFUL`。

测试覆盖独立 fake 评测、结构化 schema、错误证据、沟通失败转人工且不调用结论端点、精确公开字段白名单、金额与未批准承诺、伪造证据、越权订单，以及 stale generation、`HUMAN` 模式、非调查生命周期和客户人工偏好共享的发送授权闸门。`agent/smoke.py` 的全部既有结论调用也已升级为 `customer-reply-v1`，保持规范化全栈 smoke 的调用方兼容。
