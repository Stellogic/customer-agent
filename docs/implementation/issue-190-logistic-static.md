# Issue #190 A方案静态实现与待运行清单

关联 #190 / PR203；预登记方法提交 `963ee0fe99ccfc7c855ec16be5420d99056a54e6`。用户接受的是一次有限可行性验证，不是A必然通过的承诺。本阶段只编辑源码、数据、测试源码与文档；#165持有窗口，未运行依赖安装/锁生成、格式、lint、类型检查、测试、构建、特征、模型、拟合或任何评测，也未查询锁。

## 实现边界

- Java `KnowledgeAnswerabilityFeatures` 在既有权限、版本、发布状态、scope和代次过滤后提取四特征，开发接口与产品调用同一实现。两路20候选和RRF Top-5不变；Python不复制分词、SQL或RRF实现。
- `/api/internal/knowledge/development-candidates` 只在 `knowledge-development` profile **且** `baseline.knowledge.development-probe-enabled=true` 时存在，默认compose不开启。沿用Spring会话及知识读取capability，不是绕过权限的接口；返回字段明确为候选，不能用来冒充产品接受结果。
- 新策略独立保存在 `knowledge-answerability-logistic.json`，当前为 `PENDING_CALIBRATION`，缺参数时仍503。旧 `knowledge-retrieval-policy.json` 的唯一余弦参数原样保留但不再作为新策略回退，历史48/64题证据不动。
- `knowledge_answerability.py` 固定StandardScaler+L2 logistic、四特征/C/solver及一次拟合；仅训练组拟合统计量。只在校准组选择预定质量约束下的唯一门槛，没有可行值返回INFEASIBLE且proposal为空。不自动应用参数或开启下一阶段。
- Spring线性分数与Python顺序计算一致；测试源码提供明确的手算尺度/系数和等号边界，拟合入口也比较库decision_function与导出计算。未来留出还比较真实产品结果与导出策略，不能只用Python重算充当端到端验证。
- `knowledge_answerability_run.py` 提供本票专用prepare/collect/fit/audit阶段。prepare只新建目录，collect通过实际Spring目录和检索验证完整分区正文/版本/范围再取特征；不会写数据库或改已发布知识。fit只读取训练/校准报告与留出seal元数据，不读留出正文；audit不拟合/选参。CLI不会调用冻结评测。

## 数据与独立交接

训练144题/6主题、校准72题/3主题已人工编写到 `agent/src/baseline_agent/knowledge_answerability_v1/`，36篇原始文档的事实段落定义随JSON保存。每主题6直接+6改写+6缺失+6前提不匹配，标注理由不进入特征。manifest记录原文件SHA256，文件级Git属性保留这些JSON原字节；实际目录分块数和模型质量未运行。

负例要针对所在分区的全部合并语料核对，不把跨实体或新条件外推当成有来源答案；这也是静态Spec数据审查范围。主题隔离、来源以及新72题的schema/seal交接见[独立留出交接](issue-190-holdout-handoff.md)。协调另行安排无历史作者及独立审阅，本任务不制作、不查找或阅读其内容。当前尚未收到有效seal；封存成立前不申请运行。

## 依赖决定

训练组固定 `scikit-learn==1.7.2`，dev包含该组以供日后类型/契约检查，在线runtime的`--no-dev`不包含训练组。官方发布元数据列出Python3.13支持，许可证为BSD-3-Clause；使用该已固定版本避免stable API漂移。[发布方元数据](https://pypi.org/project/scikit-learn/1.7.2/) / [官方API](https://scikit-learn.org/1.7/modules/generated/sklearn.linear_model.LogisticRegression.html)

`uv.lock` **尚未生成更新**，不手工伪造传递依赖锁；相关格式/类型/构建全部未验证。获得窗口后先受锁正常生成锁、核对开发/运行依赖隔离并提交，再进行聚焦检查。当前源码不能被描述为已通过`uv --frozen`或完整门禁。

## 后续操作约束（不是运行授权）

入口 `scripts/knowledge-answerability.ps1` 所有阶段先持共享锁，要求干净已提交源码、唯一RunId和有效seal；`uv run --frozen --group calibration`不隐式重新生成锁。独占报告路径 `.local/gate-evidence/<RunId>/answerability-<phase>.json` 已存在则拒绝覆盖。不同RunId是证据标识，不代表新一轮拟合获准；只有预登记的一次拟合与一次选择获准后才能执行。

prepare把指定分区渲染到本RunId目录。运行负责人再以唯一Compose项目/镜像/端口启动隔离数据库，在启动前将该目录只读挂载并用 `BASELINE_KNOWLEDGE_RESOURCE_PATTERN=file:/development-knowledge/*.md` 指定语料，显式启用开发profile/开关。**三个分区使用分别新建的隔离数据库**，不替换或清理基线库，不改已应用迁移，不在同一目录代次混装分区。此脚本不负责Docker生命周期；调用者按原测试锁说明校验命名空间并清理自己拥有的资源。

fit额外要求当前源码的`safety-report`：`head_sha`为实际受测SHA，`checks`中authorization/current_version/scope/numeric_parity均须PASS。它是运行负责人汇总真实隔离PostgreSQL负向检查和跨语言数值契约结果的证据索引，不是手填通过的捷径；须附RunId、具体命令、日志/原始结果路径与哈希，未跑或任何失败均不能填PASS。正常内容集中的零违规不替代故意含旧版本/越权/越范围候选的负向回归，单元mock也不替代真实PostgreSQL。

按预登记顺序：依赖与相关聚焦检查 → 独立权限/版本/范围/数值回归 → 分区语料准备与训练/校准特征采集 → 一次拟合/唯一门槛选择 → 保存报告并提交参数 → 独立运行者一次留出采集/产品对照/audit。校准INFEASIBLE、任一执行错误或留出FAIL均停止，不自动换B、不循环跑冻结集。留出成功只表示可申请下一授权，不自动执行#189或完整门禁。新完整门禁前还需同步main并重新核对未发布迁移编号。

每个受锁运行结束必须释放自身锁，单次只读回看状态并通知协调LOCK_RELEASED；不可冒称FREE或抢占窗口。当前静态阶段没有持锁或释放事件。

## 可信记录

本阶段新增运行次数0、付费模型API调用0元；新增测量指标、训练耗时、下载量、峰值内存均未采集。216题为Codex生成的合成开发资料，不是用户流量；代码和文档也不代表用户逐行手写。上一阶段真实FAIL仍为唯一有效质量结论，新方法未验证。双轴静态审查结果待附；即使PASS也只允许CODE_READY_NO_TESTS，不允许GATE_READY、合入或关票。

## 本轮双轴静态审查

固定比较963ee0f...4bf8c6dc07793ec07794cf1926fa69c4ec3d7c11。首轮Spec指出留出打开前缺少已提交策略验证、一个训练负例范围歧义、浏览器旧策略ID断言；均已修复。修复只来自源码/独立开发文本，不涉及任何冻结结果或留出内容。

### Standards

PASS，0项阻塞发现。硬过滤先于共用特征，默认关闭的开发接口、未校准失败、一次拟合及不可行停止符合规范；留出入口检查已归档拟合报告及产品策略与proposal完全一致。仅静态阅读。

### Spec

PASS，0项新增缺陷。三项发现均闭环；训练144题/校准72题已全文静态标注复核，主题和四类配额保持，annotationReview可标PASS。INFEASIBLE保留模型系数但没有可应用策略。未执行验证、未读取留出或冻结题。

两轴各0项未解决发现；最严重项均无。此后提交仅记录审查和manifest审阅状态。阶段状态CODE_READY_NO_TESTS，源码/数据/测试源码不是运行证据。协调现另授予依赖/格式/类型/聚焦与组件窗口：须先同步main、核对迁移并守锁；拟合、校准、留出、189评测、最终完整门禁与合入仍未授权。

2026-08-31阶段验证前已同步main c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472；main已应用V41__order_compensation_allowance.sql，本票尚未发布的向量迁移因此顺延为V42。只重命名本票迁移，已应用V41及所有主线迁移不改；历史阶段所记V41是当时基线状态。
