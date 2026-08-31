# Issue #190：最小可回答性方法的一手资料比较

研究日期：2026-08-31。关联 [Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [PR #203](https://github.com/Stellogic/customer-agent/pull/203)。状态：研究建议，未实施、未验证。本次只读取官方资料并写本文；未读取冻结题、逐题报告或分数，未执行测试、模型、校准、依赖安装或锁查询。已有失败证据及 #189 冻结资产不变。

建议先采用 **A：少量固定检索特征的 L2 logistic 拒答分类器**。理由是它可以复用现有 BGE、pgvector/全文候选和 RRF，不新增大模型或改变排序；优先回答“现有检索信号能否支持一个可泛化的拒答边界”这一较小问题。它不是已证明有效的方案。**B：离线 cross-encoder 相关性辅助**保留为第二候选，不与 A 同时开发，也不在 A 留出失败后自动用同一留出集重选 B。

## 先区分目标

本票所需标签应是“当前权限和版本允许返回的检索证据，是否足以支持问题的回答”，不能简化成“文本是否同主题”。即使一段话与问题高度相关，也可能缺少所问事实；跨段组合充分性也不等于任何单段的最高分。此处是产品任务定义及推论，不是模型卡已经保证的能力。权限、scope、版本等仍由既有硬过滤处理，不让分类器学习或覆盖这些规则。

## A：固定少量特征 + L2 logistic

成熟依据：scikit-learn 的 `LogisticRegression` 提供标准正则化分类器及概率输出，`lbfgs` 支持 L2。库采用 BSD-3-Clause；当前官方稳定文档显示 1.9.0，`penalty` 参数在新版本有弃用变化。因此后续应先固定实际训练依赖版本及 API，本文没有安装或锁定新依赖。[官方 API](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html)、[官方许可证](https://github.com/scikit-learn/scikit-learn/blob/main/COPYING)

ACL 2020 的 selective QA 研究使用单独训练的校准器识别 QA 容易出错的输入，并强调域外数据的重要性。它支持“用独立监督信号学习何时拒答”的方法路线，**不等于论文证明本项目的少量检索特征或 logistic 有效**；论文的 QA 任务及训练模型与本项目不同。[原论文](https://aclanthology.org/2020.acl-main.503/)

建议的最小形式（仍需总体方案预登记）：只用固定的少量聚合信号，如最高稠密相似度、前两名差值、候选在两路召回中的一致性，以及同一既定中文分词器的词项覆盖；不加入题目 ID、领域名、问题模板、拒答关键词清单等内容特征。这些是通用检索不确定性假设，**不是来源证明的最优特征**，也未根据冻结集设计。训练前一次明确公式、缺失候选处理和候选范围，训练后不看验收结果增删特征。仅当总体方案接受时，再确定实际最小子集。

实现取舍：离线训练依赖可与产品运行依赖分离；产品只读标准化统计量、系数、截距、阈值及数据/代码哈希，计算一次线性函数和 sigmoid。训练复用成熟库，不手写优化器。返回的数值应先称判定分数；没有独立可靠性检验时，不向用户宣称它是准确的“可回答概率”。官方指出 logistic 也需条件合适才可能校准良好；额外概率校准的数据还须与训练数据分离。本轮不叠加 isotonic 等第二层拟合，避免小数据再次过拟合。[官方概率校准说明](https://scikit-learn.org/stable/modules/calibration.html)

局限：若可回答与不可回答输入具有相同的这些特征，任何该输入上的分类器都无法区分它们。它不能补回未召回的证据，也不能可靠判断数字条件、否定、跨段事实是否充分。固定 RRF 排名依然可能失败。独立留出不通过应诚实否定当前方法，不能通过领域例外或放宽门槛修补。

## B：离线 BGE reranker-base 作为辅助信号

成熟依据：官方将 cross-encoder 定位为输入 query 与 passage、联合计算相关性分数的第二阶段模型。`BAAI/bge-reranker-base` 为中英模型、278M 参数、官方模型大小约 1.11GB，基座 XLM-RoBERTa-Base。[BGE 官方模型说明](https://bge-model.com/bge/bge_reranker.html)

模型卡标 MIT，提供 Transformers sequence-classification 加载及 CPU 使用示例；输出为无界 relevance logit。sigmoid 仅改变数值范围，不能自行变成当前任务的可回答概率。[官方模型卡](https://huggingface.co/BAAI/bge-reranker-base)

版本与成本：模型历史页本次读取的最新提交短 ID 为 `2cfc18c`（2024-06-24）；这只是研究定位，不能替代未来正式使用时完整 revision、文件清单和哈希的固定。仓库有重复权重/ONNX 格式，不应把仓库总大小作为最小下载量；单 safetensors 显示约 1.11GB，另需 tokenizer/config。宿主 CPU 延迟、内存峰值、实际下载字节及与当前依赖的兼容性均**未验证**。[官方提交记录](https://huggingface.co/BAAI/bge-reranker-base/commits/main)、[官方文件清单](https://huggingface.co/BAAI/bge-reranker-base/tree/main)

若未来选择 B，应只读取既有硬过滤后的固定候选集合，先保持 RRF 输出次序不变，把交叉编码分数用于是否拒答的独立判定；不做全库重排、模型微调或 ONNX 优化。阈值仍必须来自独立开发数据，不能用模型默认零点或 0.5 充当可回答性契约。联合文本编码比 A 有更多语义信息，但更重，且对本任务的充分证据判定仍无保证。Sentence Transformers 官方也明确区分单输出 reranker 与多标签 pair classifier，并提醒迁移至具体任务可能需要微调。[官方训练说明](https://www.sbert.net/docs/cross_encoder/training_overview.html)

## 比较与验证边界

| 维度 | A：小型监督分类器 | B：离线 cross-encoder 辅助 |
| --- | --- | --- |
| 保留固定 BGE/混合检索/RRF | 是 | 是；本候选不替换排序 |
| 新资源 | 离线训练库、少量参数 | 约 1.11GB 权重及配套文件、逐候选推理 |
| 标签需求 | 独立可回答性标签，不能仅用相关性标签 | 同样需要，通用 relevance 不能免除 |
| 可解决问题的假设 | 多个检索信号共同支持拒答边界 | query/passage 交互增加语义信号 |
| 主要失败风险 | 特征无法表达充分性；域漂移 | 相关却不能回答；CPU 成本；仍需校准 |
| 本次运行/调用成本 | 未运行，付费模型调用 0 元 | 未运行，付费模型调用 0 元 |
| 实际训练、推理耗时/内存 | 未采集 | 未采集 |

以上 0 元仅指本次未调用付费模型，不能表示研究工具、网络和机器使用没有成本。本文没有预计通过率，也不把开源基准成绩算成本项目收益。

训练、阈值选择与未见留出的隔离方式及通过条件已在[总体提案](../implementation/issue-190-answerability-proposal.md)中预登记，仍待方法确定后安排实施。提案使用线性判别分数直接比较门槛，省去非必要的sigmoid；这与上文概率形式单调等价，不作概率解释。官方文档明确警告：拟合和调阈值使用相同数据会过拟合；反复依据测试成绩选择设置也会使测试失去独立性。[官方阈值选择警告](https://scikit-learn.org/stable/auto_examples/model_selection/plot_cost_sensitive_learning.html)、[官方交叉验证说明](https://scikit-learn.org/stable/modules/cross_validation.html)

对本票的直接约束是：此前看过的开发留出不能再叫“未见”；#189 原验收集被重复查看后的偏差不能用新命名消除。新方法须先固定，先通过真正隔离的新留出；#189 只在之后作为原样保留的交付回归门，不作为选型、选参或特征工程工具。两者都通过也不能宣称生产泛化已获证明。若独立留出失败，保留结果并停止该候选，不用原验收集决定下一候选。
