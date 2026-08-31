# #170 HUMAN 辅助最小消费者契约

2026-08-31，与 #169 负责人直接确认。契约尚未接入实际 HTTP API，也不是后端授权已完成。独立客户端组件/纯状态现已在协调授权窗口完成 **25 项聚焦测试及必要检查 PASS**；真实调用链仍 NOT_RUN。基线 `origin/main@c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`，保留既有 Draft PR #209。

依据：只读 PR #208 `6e343df0367cd81382d71cb327fc07eddb0a512a` 的 `docs/implementation/issue-169-agent-retrieval-contract-proposal.md` 和 `KnowledgeCitationProjection.java`；随后只读核对已提交的共用纯解析/DTO 固定 SHA `a248aca70405c53592c4df6e624bd84d60337806` 的 `agent/src/baseline_agent/knowledge_retrieval.py` 及消费者对齐记录，字段和受控码一致。#169 唯一拥有该模块，本分支未复制或导入其未合入实现；本文不另定义检索响应类型或解析函数。#190 认可的包内授权检索接缝尚未实现，原内部 API 权限不变，冻结 c5 不改。

## 已确认的 HUMAN 约定

| 项目 | 约定与归属 |
| --- | --- |
| 服务端请求绑定 | #170 负责 ticketId + assignmentId + requestId + 辅助类型；principal 从 SUPPORT 会话取得，不能信任请求体 supportId。HUMAN 不复活或伪造 Agent generation。 |
| 稳定请求 | 同一请求重试保持 requestId 和参数；换输入/类型使用新 requestId。同 ID 异参或异类型返回 REQUEST_CONFLICT。#170 后端未来保存输入摘要并核对历史回执；当前纯 UI 只保留一个活动请求，不建立缓存/历史请求表。 |
| 授权时机 | 发起、取结果、返回浏览器均验证当前 SUPPORT 主体、HUMAN、ACTIVE assignment 且 assignmentId 匹配。慢检索期间不持工单业务锁，结果接受前重新检查。工作台原 details 权限本身不足以证明 HUMAN。 |
| worker 知识调用 | 未来经 Spring 从既有辅助请求解出工单、客服与允许范围，消费 #169 唯一共用适配；模型不能指定权限范围或 URL。#170 不调用内部知识页面 API。 |
| 撤权 | #169 纯解析把 401/403/授权资源404归 ACCESS_DENIED；未来 #170 边界收到后撤销对应 assignment 的客户端状态、草稿与后续重试，不泄露资源存在。相同 assignment 的旧请求拒绝仍说明当前责任失效；不同 assignment 的迟到拒绝不得清新领取。 |
| 普通失败 | 无答案、索引、Embedding、检索、输入或知识校验失败不撤销有效 assignment，也不清除人工编辑。回复生成模型失败与 Embedding MODEL_UNAVAILABLE 区分。 |

这里确认的是最小语义；未新增路由、SQL/迁移、后端鉴权、持久化、worker 或 HTTP/LLM 调用。输入裁剪、稳定请求存储、历史异参校验、引用归属及内容安全仍属未来集成，不以当前纯 UI 代替。

## 当前自有纯状态和面板

`frontend/src/components/support-assistance/supportAssistanceState.ts` 是 #170 唯一客户端状态模块，不是共用 Agent DTO：

- `SupportAssignment` 保存客户端 `sessionKey`（仅主体切换标识）、ticketId、assignmentId；不含令牌、supportId 或 generation。
- `AssistanceRequest` 保存上述 assignment、requestId 与四类 `kind`。纯状态只保留一个活动请求；不生成 ID、不存摘要、不发送或重试请求。
- `authorize` 接收宿主重新验证过的当前责任；null 表示失权/重同步。`start` 开始一个显示中的请求，同 ID 同类型重放保留当前请求和已接受回执，同 ID 改类型作为调用方错误快速失败（REQUEST_CONFLICT），不是 HTTP 映射。
- `complete` 只接受当前 assignment/requestId/kind 的结果；替换请求后的迟到结果或失败均忽略。一个活动请求只接受首份终态，避免迟到副本覆盖；重新检索使用新 ID。
- `accessDenied` 与普通失败分开，针对当前 assignment 撤销所有内容并阻止后续 start；旧 assignment 的拒绝忽略。只有宿主重新验证并发出 authorize 后才可恢复。
- 面板只接收此状态；assignment 的三元组作为 React key 清除旧草稿与勾选。切换请求保留人工编辑，普通辅助失败仍允许编辑。组件按钮保持“开发中”，尚无调度连接。

`AssistanceView` 仍是经 Spring 授权/内容复核之后的 UI 展示需求，不是接收 wire payload 的解码类型，不可把 #169 Agent DTO 原样送入浏览器。引用显示补充 updatedAt/startLine/endLine，仅渲染白名单字段，不显示路径、分数、候选和模型配置。

## 与 #169 对齐的消费映射（接线尚未实现）

#169 独占 `agent/src/baseline_agent/knowledge_retrieval.py` 的纯 `parse_knowledge_response(status_code,payload)`、不可变 DTO 与错误归类；#170 不复制 Python 模块或另做 JavaScript 检索响应解析。其服务端/Agent 受控结果只消费正式 results，不把内部候选当答案；indexGeneration 只是知识索引代次，不能作为 HUMAN 授权。

| #169 结果/受控码 | 未来 #170 到当前 UI 的映射 |
| --- | --- |
| AVAILABLE | 必须再经当前 assignment、请求归属、引用及内容复核后形成 ready 展示；检索命中不直接成为辅助答复。 |
| NO_ANSWER | empty；保留人工草稿。 |
| ACCESS_DENIED | accessDenied 事件；清授权与草稿，不进行越权重试。 |
| INDEX_STALE / CALIBRATION_REQUIRED | error/index；不使用缓存，也不据配置状态自行解除 #190 阻塞。 |
| MODEL_UNAVAILABLE | error/embedding；与 #170 自己的生成模型 error/model 分开。 |
| RETRIEVAL_UNAVAILABLE | error/retrieval。FUSION_UNAVAILABLE、超时和异常载荷的归类仅由 #169 做。 |
| REQUEST_CONFLICT / INVALID_QUERY | error/request；告知检查输入和请求身份，不自动重发。 |
| INVALID_KNOWLEDGE_CITATION / KNOWLEDGE_CONFLICT / UNSAFE_KNOWLEDGE | error/conflict；不展示不可信引用/答复，人工编辑保留。 |

以上表是双方已确认的交接约定，不是新增第二套运行中的映射实现。浏览器不读取原始 HTTP 错误，不显示异常正文；最终后端辅助响应字段与路由另待授权接线。

## 源码与未验证项

纯状态测试覆盖稳定请求重放、异类型拒绝、旧请求迟到、撤权停止、重新领取及旧 assignment 拒绝隔离；组件测试覆盖实际 state 到草稿清屏、引用元数据展示、普通失败保留编辑及两类模型失败提示。两份测试共 **25 项在 Node24.19.0 下 PASS**；目标格式检查、ESLint 和前端类型检查 PASS。首轮 Node22 与格式失败、第二轮格式修复及锁释放事实详见 [聚焦验证记录](../delivery/issue-170-static-predevelopment.md)。

本次获准持锁聚焦运行已结束并报告 LOCK_RELEASED，未运行构建、Docker、浏览器、模型、评测或完整门禁。真实消费仍需 #190 冻结质量 PASS、完整门禁、合入关票及协调明确放行，再同步 main、补齐后端链路与增量双 CR。CI 关闭，外部审查不阻塞。任何已收到且有证据的问题仍正常修复。
