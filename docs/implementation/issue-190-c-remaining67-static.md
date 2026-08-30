# Issue #190 尚未调用67题的静态诊断准备

2026-08-31；[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [Draft PR203](https://github.com/Stellogic/customer-agent/pull/203)。**CODE_READY_NO_TESTS：本轮只有静态实现、测试源码与审查，无测试/格式/类型/模型运行，无付费许可。** 不以此前受测SHA的PASS替代新增代码验证。

## 唯一范围与冻结清单

只准备原固定合成开发集第6至72项，共67题，保留原顺序。第一项 `weaving-paraphrase-3`，最后一项 `rainfall-negative-12`。不重新调用前5题、不换题、不改Top5正文或重新检索。

[请求清单](../../agent/src/baseline_agent/knowledge_sufficiency_remaining_v1.json)仅从原开发归档复制既有ID/序号，不制作新题、不计算特征、不读取留出/#189；静态清单SHA为 `d9e11464642afb0de4fe2b4cf170f62b298284f681f2f7843e5e53c349e13bf1`，通过单独.gitattributes按字节保存。它绑定原归档SHA、数据集SHA及prompt/schema/config的原有hash。固定请求构造器/序列化复用现有代码，未修改。

逐请求字节SHA**本轮未通过运行构造器生成，未验证**。获准离线阶段须从冻结清单和原构造器物化完整67项请求hash并留证；实际阶段开始前也会将完整有序的 `{query_id, request_sha256}` 列表写入独立phase和报告，每次预留前核对下一个ID/hash，禁止重排、漏过失败题或额外请求。这里冻结的是输入来源/合同/ID与顺序，不冒称已有67次真实请求的原报文。

## 独立阶段，不恢复旧阶段

- 新固定phase：`remaining67_diagnostic_once`；opt-in：`issue-190-remaining67-diagnostic-once`；入口：原 `scripts/knowledge-sufficiency.ps1 -DiagnoseRemainingOnce`。与第5次诊断开关互斥，无任意数据路径、起始下标或一般续跑参数。
- 首次进入必须校验共享账本完整状态与[单次诊断b后的快照](evidence/issue190-c-fifth-diagnostic-20260831b/cost-ledger.json)一致，SHA `0bd04be15c1c6e1eeb96f96cdadf994aa14b5a0f2d894e38c3426193896b40f8`。缺失账本、丢费用历史、原phase变化等立即停止，不初始化替代账本。
- 原 `seen_development` 继续STOPPED、5请求/4合法完成/72计划、metrics=null。`fifth_request_diagnostic_once` 保持终结，单题诊断成功不替换原第5次结构失败/NOT_CAPTURED。新阶段至多67次调用，不并入原开发完成数。
- 保持串行、原响应解析/有界取证、模型身份漂移检查、预留和usage结算逻辑。第一个非法结构/证据、供应商/余额/超时、漂移、未知usage或预算不足即停止，无自动重试。
- 新phase一旦开始，成功、失败、中止都不允许以新RunId重开。成功仅为DIAGNOSTIC_COMPLETED，metrics始终null，quality_evaluation=false；不计算剔除失败后的质量分数，不据此解阻下游。

即使67题全部诊断完成，三阶段仍分别为原开发5次（含结构失败）、单题诊断1次、补充诊断67次；全局73次API不等于73个独立质量样本。不能拼接单题成功去替换旧失败，再把完整开发集标作质量PASS。

## 预算与未来运行前置

沿用原共享累计≤6元，最近已保存上界0.010773元、未结算0。按已冻结高峰未缓存价格输入3元/百万token、输出9元/百万token及1048576输入边界/256输出帽，单次最坏预留仍3.148032元；首请求加已结算为3.158805元≤6元。收到可信usage后保守结算并释放差额，未知usage保留预留并停。不能因为阶段新增而清零费用；也不以67倍最坏预留要求所有请求预先可完成。

作为原4096输入/256输出假设的预算预测，67次新增上界估计为0.977664元，含当前历史约0.988437元；这不是输入帽、实际报价或完成保证。真实运行前仍须重新核对官方价格/上下文与共享预算。价格依据沿用[前阶段已核对记录](issue-190-c-fifth-diagnostic.md)，本轮未执行价格预检或真实调用。

未来离线窗口须同步main、检查迁移占用，受共享锁执行实际PowerShell→uv→Python三模式参数回归、C聚焦/必要组件、格式/类型，并物化/归档请求hash。离线PASS、最终源码与合同提交回读之后，真实窗口仍须协调单独授权。BUSY立即停报、RECOVERY_REQUIRED升级，每次释放通知；本轮未查询或占用锁。

## 新增测试源码与未验证项

新增离线测试源码覆盖：67项顺序/禁止前5题、完整临时账本历史与原两phase不变、全程metrics=null、67次上限及新RunId阻止再次调用；中途非法结构、漂移、未知usage、供应商错误的首次失败停止/结算；清单重排和预算不足拒绝。已有实际入口回归源码扩为普通/第5题/剩余67题三模式，仍主动无key，在argparse之后、账本/HTTP之前停止。

**以上新增回归未运行，格式/类型/组件均未验证，未生成新模型结果。** 本轮仅静态复制请求清单并保存实现/测试源码，没有安装下载、校准、拟合、冻结评测或模型调用，也没有修改共享账本。旧失败与真实证据均保留；当前不是GATE_READY或正式完成。

本票贡献边界仍为Codex按用户授权执行学习项目代码与实验；新增实现与测试设计不能包装成已验证正确性、生产规模或用户逐行手写。

## 静态双轴审查

完成固定提交的Standards / Spec审查后补记结论；任何静态PASS都不代替本轮尚未获准的运行验证。
