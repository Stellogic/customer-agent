# #169 客户回答层执行前协议

协议 `rag-layered-v2-answer / issue169-customer-answer-v1`，2026-09-01。协调明确批准新增客户专用合成集：#189原64题的36有答案与12无答案均属内部身份，不能直接改身份重算。本集不修改原题、标签、历史成绩或内部权限；不是 #189 旧集 PASS。

## 冻结输入与分母

完整问题、支持段落、标签理由和8个独立边界见同名 JSON。18个明确来源命题各有两种问法，共36条有答案；12条无答案，语义分母固定48。编号以 JSON 顺序展开，不抽样、不删除失败。段落从标题后的首个非空正文段落算1。公开语料为正常产品目录下的 customer-delivery-help-v1、customer-conversation-help-v1、customer-privacy-help-v1；都只包含一般信息补充/沟通/隐私提醒，无内部操作或资格金额规则。它们通过正常目录索引、BGE和共享适配检索，不在评测调用中塞入标准答案。

所有样本使用合成 customer-demo 的独立 AGENT 工单，绑定已有可核验的正常订单。问题写入真实客户上下文；事实从 Spring 的受控调查能力读取。知识请求走本票 generation/operation 鉴权端点、固定 CUSTOMER_PUBLIC，不调用内部检索页面接口。48条针对产品 `DeepSeekResponsesCustomerCommunicationModel.compose` 同次判断/回答路径，最终仍交 Spring 正文/回执/当前版本校验。Agent 自主查询决策另以真实 graph 个案检查，不将直接调用回答接缝冒称完整48次自主调查。

## 已冻结的模型协议

- 原有产品 `customer-knowledge-communication-v1` / `customer-reply-v2`，实际 `_build_request`，不新增独立充分性调用，不读取模型结果后修改 prompt 或选参。
- `deepseek-v4-flash`，`https://api.deepseek.com/responses`，stream=true、reasoning.effort=none；输出必须严格符合 JSON Schema，请求按供应商官方 `text.format` 的 `type/name/schema` 三键发送，不附加未文档化的 `strict` 字段；不新增 temperature 参数。知识分支完全缓冲，接受前不发布正文delta。
- 知识输出上限1536 tokens，正文≤1500字符、引用≤5；整体公开正文≤2502字符。没有单引文24字限制，截断/解析失败不当资料不足。
- 产品默认连接3秒、读取12秒、每次compose整体15秒；每次compose最多2次provider尝试，每题最多2次compose（一次受控修正），因此每题最多4次provider尝试，全部共用原累计费用账本。Python格式检查和Spring拒绝共用一次修正机会，不能为修正重检索。外层验收不增加第三次compose；失败保留，供应商/未知usage/余额/预算故障立即停止后续付费调用。
- 结构失败保持 fail closed；审计只记录首个失败的字段路径、required/type/enum/const/additionalProperties/长度/数量等类别、期望与实际 JSON 类型。仅 schemaVersion、intent、knowledge.status 允许记录最多64字符的合成枚举值；不记录正文、引文、凭据、Authorization 或完整供应商输出。
- 48条最多96个回答 logical calls / 192次provider attempts；另预留最多3个自主graph个案、每例既有8次action上限及2次communication，共30个logical calls。该数量只是上界，累计费用准入优先，不能保证预算内全部完成。

## 费用准入

唯一累计账本为 `D:\customer-agent\.local\issue190-sufficiency\cost-ledger.json`。执行前读回289条SETTLED、620805微元，无PENDING；总上限5000000微元，绝不重置。每次实际provider请求前原子写入PENDING；有未结算预留立即停止；可信usage按高峰非缓存输入3元/百万token、输出9元/百万token保守结算，不预支缓存或夜间折扣。未知usage保留预留并上报。

2026-09-01复核[官方人民币价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)：Flash仍是1M上下文，最高输入3元/百万、输出9元/百万。每次请求按“UTF-8请求字节数×3 + 本次最大输出token数×9”微元预留；UTF-8 BPE输入token数不会超过请求字节数，因此该输入预留仍是保守上界，同时避免把模型支持的1M理论上下文误当成每次实际请求。可信usage返回后以实际token数结算；usage未知时保留整笔预留并停止。输入4096 token的粗估每次26112微元，48次约1.253376元，**只是预测而非账单或完成保证**。任一次累计已结算加预留超过5元即停止，不缩题或降低门槛。SDK无额外暗重试；重试每次独立记账。

## 评分与边界

结构、引用、语义分别报告数量/原始48分母；最终可接受结果须检索、模型、解析、Spring接受均成功。SUPPORTED 的引用真实只证明文本出现，语义仍人工逐题对照 required_meaning 和授权正文：涵盖问题所需含义，未添无依据规则或个案事实，才算有依据回答。无答案成功须明确资料不足/必要追问，且未给猜测规则；不能仅用 status 枚举自评。

正确拒答/全部预测拒答≥0.90，正确拒答/12≥0.85；分母为0不PASS。结构失败的语义标未评估而非错误；HTTP拒绝、检索/供应商/解析故障单列，不能算正确拒答。整集未执行完不能整体PASS；不得用已有对题率掩盖未运行样本。逐题人工语义评审在所有模型输出固化后进行，不回灌prompt。

8边界独立记录：授权、撤权、旧版本、索引过期、片段注入、业务冲突、公开字段、桌面/窄屏断线恢复。边界所需恶意/过期fixture只存在隔离验收事务，明确不是正常知识语料，不扩大权限或注入产品假答案。真正并发用PostgreSQL锁屏障检查；单元mock不当并发证明。页面检查真实Spring快照/SSE，测试源码中的渲染fixture不代替浏览器验收。

## 冻结与执行条件

真实调用前把本协议、完整数据和语料清单提交，独立Spec只读审查标签/客户权限/分母，Standards审查调用预算与实现。运行记录绑定该提交、prompt/schema源码和数据/语料SHA-256（必要的冻结证据，不新增产品哈希协议）。当前状态为 **PRE_CALL_REVIEW，模型0调用**。后续结果另追加，保留本协议和所有失败；不得把本文件当执行完成。
