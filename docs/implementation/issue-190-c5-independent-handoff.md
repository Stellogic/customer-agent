# Issue #190 / PR203：c5 独立验证候选

状态：**READY_FOR_INDEPENDENT_VALIDATION**，不是最终GATE_READY或交付PASS。按用户恢复授权完成通用提示优化，c5第一次完整72题开发回放达到原四项门槛后停止选参；后续由协调安排独立执行，实施者不读取未见留出。关联[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [Draft PR203](https://github.com/Stellogic/customer-agent/pull/203)。

## 固定候选

- 真实受测源码/资产：`5402bd4c438ff68fc9bbc4a01e55080b12499ce9`；base `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。后续本轮归档只新增文档/证据，源码不变。
- 资产目录：`agent/src/baseline_agent/knowledge_sufficiency_development/c5/`；prompt SHA256 `86f99ff950f5482cf3b30e9946309f5592c86fc7f30d49b37764afa3fac52ab5`，schema `27ef4d19440b4279ac4b0426eb299e87445a455be5206716ad82c0da6f3733f4`，config `c4f798e19f33b0facad7482ecccc0bd3ab6288bebe66e08411dca093189347e1`。
- 72项开发请求字节SHA清单文件：`evidence/issue190-development-c5-20260831a/requests.json`，文件SHA256 `703585ab58de3c1daa02096373275b4920c8698090a9f2b043ceb0ddcd048d45`。有序内容与发送前写入的报告/账本清单逐项一致；这是开发请求清单，不是未来独立输入清单。
- 模型请求别名deepseek-v4-flash、非思考、temperature=0、输出上限256，逐题一次无自动重试；别名不是不可变权重。开发实返均deepseek-v4-flash，fingerprint未提供；不能宣称确认了底层权重不变。
- 本地固定BGE、硬权限/版本过滤和RRF不变；原#189资产和全部门槛不变。当前main迁移到V41，未发布向量迁移V42，无V36/V37碰撞；没有修改已应用迁移。

## 开发证据及局限

RunId `issue190-development-c5-20260831a`，[原始报告及索引](evidence/issue190-development-c5-20260831a/)。72/72契约合法，Recall@5=0.944444、MRR@5=0.787037、拒答precision=0.945946、recall=0.972222；2误拒、1误接。所有指标只来自本轮，未拼分；开发过程与旧失败对照见[版本记录](issue-190-development-log.md)。

这是已反复查看、允许优化的合成开发72题，并非盲测、生产流量或用户线上效果。原独立静态标注审阅不是人工金标，也不替代独立实测；当前PASS不能解阻下游。没有根据未见留出/#189新题改prompt或选参。新独立结果出来后不能回头把它并入本轮开发成绩。

离线覆盖：14项聚焦、56项相关组件（含聚焦）、五模式实际入口、Ruff及Pyright在版本入口落地时PASS；c4增量3项及格式/类型PASS；c5仅资产与测试参数变化，4项增量及Ruff/格式PASS，复用未变源码已有检查。各次实际受测工作树和起始HEAD区别已记录。独立Standards/Spec审查在入口及c4/c5增量均PASS；不是最终完整门禁。

## 独立执行接缝与资源

复用 `knowledge_sufficiency.contract(development_version="c5")`、`request_body(row, frozen)` 和 `parse_response(..., c_v2=True)`：只发合成问题与授权过滤后的Top5，不发标签/答案/特征；解析保留类型、交叉字段、片段编号范围、逐字原文检查。同编号多摘录不计为多个独立来源。不得静默截断、去重修复非法输出或改判定规则。现有 `-DevelopmentVersion c5` 入口固定读已见开发档案，**不能当作未见留出入口**；独立运行器由协调安排复用接缝并验证，不能把开发数据替代留出。

共享预算账本仍为 `D:/customer-agent/.local/issue190-sufficiency/cost-ledger.json`，当前SHA256 `045bd38d6bc2ed7daa113dd95b09cffbe8f5528e15c0fbb80665e6712b48157a`；累计上界0.473070元、未结算0，预算总额6元不重置。每请求按1,048,576输入与256输出最坏预留3.148032元，可信usage按官方高峰未缓存输入3/输出9元每百万token结算释放差额。必要验证能否全部完成仍不保证；供应商/余额/预算/漂移/未知usage立即停，不造假回退或自动续跑。

本阶段窗口已归还，进程结束后宿主只读确认FREE并已通知协调。后续独立实测、#189冻结质量门、产品接入和最终完整门禁/合入仍待协调安排；不因锁FREE自行启动。Agent实现、模型合成数据和Agent审查的贡献边界如实保留，不等于用户逐行手写或生产规模经验。

归档增量审查（base `5402bd4`）：Standards PASS，0缺陷；Spec PASS，0缺陷。两名独立Agent核对完整数、误拒/误接、受测SHA、费用及非盲测边界与原始报告一致。本次只保存证据/文档，没有新增运行或源码变化。
