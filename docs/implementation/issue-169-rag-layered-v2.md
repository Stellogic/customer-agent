# #169 rag-layered-v2：静态承接与回答层边界

## 依据与本轮状态

2026-08-31 读取正式 [#149](https://github.com/Stellogic/customer-agent/issues/149)、[#169](https://github.com/Stellogic/customer-agent/issues/169)、[#190](https://github.com/Stellogic/customer-agent/issues/190) 最新正文，按协调任务 `01a043aa-d724-7353-b6c5-9266277846d6` 派发继续。
main 为 `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`，本轮起始 HEAD 为 `575d10a2b7fa39b94d55e19890d6c6f251d593a1`，保留已有贡献不重做。
#169 原生 blocked_by 中 #150/#159/#161 已 CLOSED，#190 仍 OPEN；不能因规格修订或共享锁空闲自行集成。

本轮仅修订共用 Python 解析的状态/失败语义、相关测试源码及本票契约文档。客户 UI、Java 纯投影不变；不写新 HTTP、Spring adapter、Agent 公共入口、模型调用或通用评测框架。
**本次差异 CODE_READY_NO_TESTS**。上次 41 项聚焦 PASS 仅属于提交 `575d10a`，不覆盖这次行为变更；未重算旧 FAIL、改 #189 资产、重置费用或修改 #190 实验记录。

## #190 实际接缝核对

只读 PR203 固定提交 `5cc9dcb687c190ac8dffbbb54744fb1a318504be`：

- `backend/src/main/java/com/stellogic/customeragent/knowledge/KnowledgeRetrievalService.java` 仍为旧 `requireCalibrated/accepts` 路径，只有内部 `search(principal, query, scope)`，没有 `searchAuthorizedScopes`。
- 同目录 `KnowledgeRetrievalModels.java` 的旧 schema 为 knowledge-hybrid-v1，含 policy；hit 没有 updatedAt。

这两条是历史源码证据，**不能用于声称 rag-layered-v2 已落地或允许集成**。
#190 owner `01a051b6-257f-7230-a04e-a2f6a112e921` 随后交接固定提交 **`802a34310d4c01991ea480082a6025372da016a8`**。已只读核对该 SHA 的 `docs/implementation/issue-190-layered-interface.md`、上述 Service 和 Models，确认以下新版边界；它仍为未正式交付的 PR203 源码，不是本票已获授权可调用的接口：

| 项目 | owner 已明确的新版内容 |
| --- | --- |
| 入口 | 仍是内部 `GET /api/internal/knowledge/search`，不新增客户/Agent HTTP；当前没有包内可信授权范围方法。 |
| 顶层 | schema=knowledge-hybrid-v2；query/generation/revision/lexicalCandidates/vectorCandidates/results，无 policy/answerable。 |
| hit | chunkId/articleId/version/title/applicability/sourceFile/startLine/endLine/snippet/score/lexicalScore/vectorScore；仍无 updatedAt。 |
| results | 排名前硬过滤后的授权 RRF Top-5；分数只排序。空列表仅无匹配资料，不是语义拒答。只消费最终 results，不把内部两路诊断列表当作绕过最终排序的结果。 |
| 范围 | 有效 scope 与员工授权范围交集为空时返回 200 空列表；缺 capability 或客户走内部接口为 403 KNOWLEDGE_ACCESS_DENIED。不是 Agent 获取客户知识的授权入口。 |
| 故障 | 400 INVALID_KNOWLEDGE_QUERY；503 INDEX_STALE/MODEL_UNAVAILABLE/RETRIEVAL_UNAVAILABLE/FUSION_UNAVAILABLE。默认路径解除评分/校准依赖。 |

`updatedAt` 需要与同 articleId/version 的 canonical 元数据一致；不能冒用内部身份去目录 HTTP 补读。此前讨论的包内可信范围入口、#169 受控投影和其事务/授权接线仍待集成阶段落实。不得复制检索实现来填空。

## 唯一共享解析的最小修订

#169 继续唯一拥有 `agent/src/baseline_agent/knowledge_retrieval.py`。其 `agent-knowledge-v1/indexGeneration/results` 是 #169 拟议适配输出，**不是** #190 内部 knowledge-hybrid-v2 原样透传；字段 whitelist、最大五条、身份/版本/片段元数据保持原约定。

- `KnowledgeResultStatus.CANDIDATES_AVAILABLE`：成功响应中有授权片段，未声称足够回答或可公开引用。
- `KnowledgeResultStatus.NO_MATCH`：成功响应中无匹配片段，未形成模型的资料不足说明。
- 删除旧 AVAILABLE/NO_ANSWER 枚举名，不留让消费者继续误用的兼容别名；当前没有已挂载产品消费者。
- 默认失败码不再保留 CALIBRATION_REQUIRED。若收到旧错误，仍失败为 RETRIEVAL_UNAVAILABLE，不能降为 NO_MATCH 或正常拒答。其他已知权限/查询/索引/Embedding/引用失败归类不变。
- 不对单条 snippet 施加 24 字符限制，不截断授权资料来构造假支持。新增的长片段测试数据仅存在测试源码。

已与 #170 owner `01a053ab-74a9-72e3-aeb2-87bc6e09139f` 对齐：其 HUMAN 展示和模型结果区分“无匹配、尚未形成回答判断”与生成后的资料不足说明；其自有 SUPPORTED/INSUFFICIENT_INFORMATION 不能直接由检索状态派生。#170 不复制检索 DTO/解析，assignment/请求绑定、撤权和人工审阅仍归其自有模块。

## #169 同次回答职责

后续客户路径将当前问题、授权片段和独立的 Spring 权威事实交给**负责生成回答的同一次 DeepSeek 调用**，在该输出中形成充分性结论及回答/资料不足说明，可必要追问。默认不增加独立充分性请求，不新增搜索入口，仅因资料不足不自动转人工。传输重试仍属于原调用策略，不能伪装第二个默认判断阶段。

规则陈述必须关联本次授权结果，并校验逐字引文确实来自相应片段；引文真实不等于语义充分。订单、物流、支付、资格、金额和执行结果仅来自 Spring；有冲突时保留权威个案事实并记录知识冲突。权限、版本、当前 generation 和公开回复权仍须由 Spring 复核，校验前不得公开内容或来源。

当前 `customer-reply-v1` 为封闭字段协议，现有 `deepseek_customer_communication_model.py` 也没有知识回答输入/输出分支。**本轮不猜新 JSON 字段或修改这些公共模块**。新回答 schema/prompt 的确切文本、整体输出 token/长度上限及接线方案在真实验证前冻结，不能用现有默认 384 token 或自造数字冒称已确认。无单条 24 字符限制不等于无限输出。

## 回答质量分项记录（执行前待冻结，不是新评测实现）

本票承担自身真实客户知识回答路径的拒答 precision ≥ 0.90、recall ≥ 0.85。沿用 #189 冻结题目、标签、相关条目及数值目标；不读取验收错题调 prompt/选参、不修改标签、不从失败集中挑子集。

| 分项 | 必须记录的证据与失败区分 |
| --- | --- |
| 检索与调用 | 本次授权结果、来源身份/版本、检索失败；真实模型名称/版本、调用与重试、供应商失败。合法候选不算已回答。 |
| 结构合法性 | 解码/解析成功与正式 schema 校验结果；格式失败单列，不计资料不足回答。 |
| 引用真实性 | 引用是否属于本次授权结果、当前版本/范围是否有效、逐字引文是否存在；不得以 ID 存在替代真实引文与授权校验。 |
| 语义充分性 | 回答是否由材料支持、是否遗漏必要条件、是否混入业务猜测；不得由 JSON 合法、引用存在或模型自评自动推导 PASS。无自动判据的项标未验证并保留复核依据。 |
| 资料不足/拒答 | 只有检索、模型、解析成功且回答明确合法地说明资料不足才记正常拒答；明确不足结论却附带无依据规则答案不算合法拒答。 |

报告保留完整冻结样本分母 N：有答案/无答案标签计数、正常支持回答、正常拒答、各阶段失败/未运行及其样本归属，不能删除失败后用成功子集宣称整体验收通过。
以“无答案”为拒答正类，TP 为无答案题的合法拒答，FP 为有答案题的合法但错误拒答，FN 为无答案题未合法拒答（含检索/供应商/解析失败）；precision=TP/(TP+FP)，recall=TP/(TP+FN)。零分母记未定义、不得按 1.0 通过。其他故障仍在完整分母和独立故障表中报告，不能因不落入 precision 分母而抹除；两率通过不替代结构、引用、语义和工程验收。

真实执行前还须冻结：样本/知识内容哈希、源码 SHA、模型、prompt/schema 版本与哈希、总体输出上限、调用/尝试/重试/费用上限、完整记录和分项判定方式。复用已有调用审计与本票专用记录，不新增通用日志框架；累计付费预算不因修订重置。上述待定项当前全部未验证，也不是新云调用授权。

## 当前边界

本轮未运行测试、格式/lint/类型检查、编译/构建、Docker、模型/评测、浏览器或 check.ps1；未申请或占锁，未触发 CI。未真实接入、转 Ready、合入或关闭 #169。
正式接入仍等待 #190 检索层质量实测与完整门禁 PASS、合入 main、关票和协调放行；之后本票独立承担回答质量和完整工程门禁，不将 #173/#174 或回答质量反向变成 #190 的循环前置。

## 本轮静态双 CR

固定比较 `git diff --cached 575d10a2b7fa39b94d55e19890d6c6f251d593a1`，六文件 104 新增／19 删除。两个独立审查者只读核对最新票据快照、固定 #190 接口与增量：Standards **PASS，0 项发现**；Spec **PASS，0 项发现**。本段仅补记结果，未改变被审查实现；全部运行验证仍 NOT_RUN。
