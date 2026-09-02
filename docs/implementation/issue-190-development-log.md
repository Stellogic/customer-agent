# Issue #190：恢复自主开发后的版本记录

2026-08-31，用户明确恢复自主通用优化及合理多轮开发验证，覆盖此前逐轮审批/不得改prompt的调度限制。旧A/C/C-v2阶段仍保持原结束状态和成绩，不改历史、标签、题目或门槛；只使用已见合成开发72题及固定有序Top5。未见留出仍交独立执行者，本任务不读，收敛前不合入。

实现只给现有实验入口增加 `-DevelopmentVersion c3` 参数。版本资产提交后运行，每版本完整72题一次，所有成绩分别保存，不挑题拼分；报告在首个请求前记录完整请求hash清单。不同版本共用原账本，保留原122次调用及全部旧phase；待结算费用、供应商/余额/预算问题立即停，不重置预算、不假回退。普通开发质量失败可按新授权改进下一版本。

## c3：按问题实际要求判断充分性

观察已见8处分歧：主要为口语改写、局部操作问题误拒，以及相似对象间规则误用。通用修改是先通读全部片段，在内部尝试最短有据回答；不附加问题未要求的教程/参数；区分同义表达与不同对象/版本/适用范围。提示无题目ID、答案、主题专名或领域例外。保留Flash、非思考、temperature=0、输出256、既有原文/授权检查；只改prompt和版本元数据，默认产品策略不切换。

方法依据：[充分上下文研究](https://research.google/blog/deeper-insights-into-retrieval-augmented-generation-the-role-of-sufficient-context/)区分相关性与足够回答，并采用提示式判定；不借其准确率充当本项目结果。[官方计费](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)本次重核仍按Flash高峰未缓存3元/百万输入、9元/百万输出。共用累计≤6元账本，起点上界0.195579元、未结算0，hash `0800a19d7111b2838d7131734a62cdf6a64be48dcac1fc8c9b44d3435b9646f0`；逐请求预留3.148032元、可信usage结算释放差额，费用不足即停止。

源码/资产提交后受锁做离线契约、实际入口、格式/类型及相关组件检查，双轴CR；之后按已有授权验证完整开发集。每阶段RunId/受测SHA、指标及费用另记于本文件，未知写未采集。模型别名不代表不可变权重；旧#189失败与冻结标准不变，开发PASS也不是独立验证或交付PASS。

### c3 离线预检与审查

RunId `issue190-development-offline-20260831a`：[原始证据](evidence/issue190-development-offline-20260831a/phase.json)。起始代码 `ff4958165453c230e8a3c1aaad3c4081d0b4d305`，base `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。同一持锁进程先格式化三个Python文件，随后14项聚焦、56项相关组件（包含聚焦）、五模式实际PowerShell→Python入口、Ruff及Pyright全部PASS，耗时69.3156588秒。测试覆盖的是格式化后源码；本次提交保留这些纯排版差异，不把起始HEAD表述为字节完全相同的受测源码。

API调用0，费用0；共享账本前后SHA256均为 `0800a19d7111b2838d7131734a62cdf6a64be48dcac1fc8c9b44d3435b9646f0`。进程释放后宿主单次回读FREE并已通知协调。随后协调再次明确恢复自主开发窗口；未重复执行已通过的离线项目。

Standards PASS：独立静态审查 `ff49581`，0缺陷；原有runner/账本复用、历史不覆盖，无新增题目特例。Spec PASS：独立静态审查 `ff49581`及格式增量，0缺陷；72题整批、顺序hash、预算和旧阶段保留符合恢复授权。两项均不是质量通过。以上由Codex实现及Agent审查，不声称用户逐行手写、生产规模或线上收益。真实c3结果尚未运行。

### c3 实际结果与 c4 最小改进

c3 RunId `issue190-development-c3-20260831a`，受测提交 `ff29761d85ef524912447426ef635784a62f7257`，base仍c19a7ebe。3次请求、2/72完成后 `INVALID_DECISION_SCHEMA` 停止，metrics=null，语义质量未评估。[脱敏原始报告及共享账本](evidence/issue190-development-c3-20260831a/)保留第3次输出：模型返回整个JSON Schema定义，缺少sufficient/evidence实例字段；本地拒绝正确，不将其解释成检索或语义质量FAIL。

输入1807、输出165 token，新增保守费用6906微元，累计0.202485元、未结算0；Python6.5674578秒、入口9.958633秒。实返deepseek-v4-flash、fingerprint=null。账本SHA256 `6aaf63e0b38110df34a98138c18ae2c86156a39f2d5310791fbe15a4a9a12693`；无重试，旧122次记录未改，c3独立STOPPED。单次宿主回读FREE并通知协调后继续当前开发窗口。

c4仅在c3提示末尾补充正/负JSON实例形状，明确不输出Schema定义，格式占位必须替换成当前真实片段，绝不把占位当证据。依据[供应商JSON Output指引](https://api-docs.deepseek.com/zh-cn/guides/json_mode/)要求明确输出格式样例；[Responses兼容文档](https://api-docs.deepseek.com/zh-cn/guides/responses_api/)声明支持text.format，但本次实返仍不遵约，因此保留所有本地校验。模型、schema、数值边界、数据及门槛不变。新版完整72题单独验证，不续c3、不拼分。

c4增量Standards/Spec均PASS，0缺陷。`issue190-development-c4-offline-20260831a`：3项版本化离线回归、Ruff/格式/Pyright PASS，23.7218885秒，API=0、账本hash前后相同；复用已通过的入口/旧组件，不无故重跑。运行起始ff29761加本次未提交c4资产/测试增量，随后提交的源码即本次受测内容，不能把起始HEAD当作纯净受测HEAD。原始日志见[evidence](evidence/issue190-development-c4-offline-20260831a/)。

### c4 实际结果与 c5 短摘录提示

`issue190-development-c4-20260831a`，受测SHA `dc6c71250a3d1cbf101720616f7a6039f186f763`，36请求、35/72完成后STOPPED，metrics=null。第36次模型给出25字符真实原文摘录，超过既有24字符合同，evidence_fields FAIL（协调初报误写26，现按原字符串长度更正）；没有静默截断或继续。输入25969、输出749 token，新增84648微元，累计上界0.287133元、未结算0；Python38.6486183秒，入口42.1395718秒。原始报告/共享账本见[evidence](evidence/issue190-development-c4-20260831a/)，旧阶段不变；未计算任何部分样本质量分数。

c5保留c4全部方法与校验，仅补充原文短语优先、不必复制完整长句、长摘录拆成同来源多段，以及逐条检查标点计数。建议长度12是输出指导，不是改动24字符合同或质量门槛。无题目/答案/领域例外；独立完整72题，不续c4、不拼分。没有更改产品策略。

c5增量双轴静态CR均PASS、0缺陷。`issue190-development-c5-offline-20260831a`在dc6c712加当前资产/测试增量上4项回归、Ruff/格式PASS，8.8149764秒；产品源码未变，复用已通过类型/入口/组件。API=0，共享账本hash前后相同。原始日志见[evidence](evidence/issue190-development-c5-offline-20260831a/)。

### c5 开发收敛，冻结候选

`issue190-development-c5-20260831a`，受测SHA `5402bd4c438ff68fc9bbc4a01e55080b12499ce9`，base `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。完整72题逐题一次，六层契约各72 PASS；四项开发指标全部过原门槛，停止开发调参。72题包含36可答、36不可答，2误拒、1误接；每个版本单独评估，未拼接旧结果。

|版本|有效完成/请求|契约|Recall@5|MRR@5|拒答精确率|拒答召回率|
|---|---:|---|---:|---:|---:|---:|
|旧C-v2|72/72|PASS|0.805556|0.703704|0.833333|0.972222|
|c3|2/3|FAIL，Schema回显|null|null|null|null|
|c4|35/36|FAIL，摘录超长|null|null|null|null|
|c5|72/72|PASS|0.944444|0.787037|0.945946|0.972222|
|原门槛|完整72|全部合法|≥0.90|≥0.75|≥0.90|≥0.85|

本轮输入57506、输出1491、合计58997 token，缓存36480、reasoning=0；按高峰未缓存价结算新增上界0.185937元，共享累计0.473070元、未结算0、历史总调用233次（不是233个独立样本）。实际供应商扣款未采集，未拿缓存折扣扩大预算。Python80.3693664秒、入口83.9525823秒；Windows11/CPython3.13.13，实返模型deepseek-v4-flash、fingerprint=null。相比c4归档，原161次调用及全部旧phase逐项相同。

原始报告、请求hash清单、账本及文件hash索引在[evidence](evidence/issue190-development-c5-20260831a/)。保留各轮失败原始输出、SHA/base、RunId和实际费用；未重跑、未改标签/门槛、未读取未见留出或#189新内容、未切产品默认策略。此结果是反复查看后的合成开发集表现，不能证明泛化或生产收益。候选及独立执行接缝见[交接](issue-190-c5-independent-handoff.md)。
