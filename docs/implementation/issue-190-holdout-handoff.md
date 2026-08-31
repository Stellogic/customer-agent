# Issue #190 未见留出制作交接（仅结构与排除边界）

协调独立安排无本任务历史的数据作者与审阅者。本实现任务不制作、不阅读留出主题内容/正文/问题/标签；这里仅交接格式和已使用主题，不能将训练问句或历史冻结报告转给留出作者。

已制作的训练组：`ceramic` 青岚陶艺釉烧、`darkroom` 银桥暗房冲洗、`espresso` 石岸咖啡萃取、`joinery` 榆舟木工榫接、`sourdough` 麦丘发酵面包、`choir` 松声合唱排练。校准组：`weaving` 棉汀织机整经、`leather` 栎原皮具缝制、`rainfall` 溪标雨量观测。禁止复用这些主题/正文/问句；也排除旧48题的图书借阅、温室养护、展馆寄存、泳道预约、露营器材、天文馆参观，以及#189物流/退款/补偿审批主题。仅分享排除类目，不分享原题。

计划未见留出3个全新主题，每主题24题：6直接正例、6低词面改写正例、6所问属性/条件缺失负例、6实体/前提不匹配负例，共72题。每主题4篇短文，六条事实分布在四篇中；每事实支持一个直接问句和一个改写问句。正文每事实单独一段，使用现有目录分块；不要求复用任何特定正负句式。事实可以是非生产的虚构教学约定，来源须明示合成；负例不能从其他两个留出主题的正文获得答案。

## 数据文件结构

文件为UTF-8 JSON，单个分区一个文件；不要传给实现者查看具体内容。实现者只接收封存manifest元数据。

```json
{
  "schema": "knowledge-answerability-data-v1",
  "split": "holdout",
  "source": "独立作者与审阅方式、合成来源说明",
  "topics": [{
    "id": "lowercase-new-topic",
    "title": "新主题标题",
    "articles": {"a": "文档标题", "b": "文档标题", "c": "文档标题", "d": "文档标题"},
    "facts": [{"article": "a", "text": "一段完整支持事实", "direct": "直接问题", "paraphrase": "低词面重合问题"}],
    "negatives": [{"kind": "missing", "text": "问题", "reason": "为何整个留出语料库不支持"}]
  }]
}
```

以上只展示对象形状；每主题实际需6条facts、12条negatives（missing/mismatch各6），4个article必须均使用。id限定小写字母数字短横线，文档article键固定a/b/c/d。单段事实少于800字符，问题1–200字符；不嵌入知识元数据或Markdown控制结构。数据检查、特征计算与测试须等运行授权，不能以封存为由启动模型。

后续受锁准备程序把每主题四篇文档渲染为目录Markdown：固定版本 `development-v1`、PUBLISHED/current、scope INTERNAL；每事实空行分段。标签通过article及原始支持段落解析至真实目录片段，不自造Java chunk哈希。训练/校准/留出分别使用自己的完整分区语料和隔离数据库，绝不混装。

## 实现任务只可接收的封存元数据

```json
{
  "schema": "knowledge-answerability-holdout-seal-v1",
  "datasetSha256": "实际封存原始JSON文件的64位SHA256",
  "topicCount": 3,
  "queryCount": 72,
  "authorContext": "记录无历史作者身份/任务ID",
  "reviewerContext": "独立审阅者身份/任务ID",
  "annotationReview": "PASS",
  "topicIsolation": true,
  "implementerHasReadContent": false,
  "sealedAt": "实际封存时间"
}
```

作者与审阅者应不同，均不接收冻结题/分数、模型输出、拟合参数；记录正文访问清单。标签审阅针对合并后的全部留出语料，而非只看单主题；歧义在任何模型运行前解决并重新封存。实现者不需要topic名称、文件路径或正文；由独立运行者在参数和源码固定后使用封存原件完成一次评测。seal不是访问控制，若发生提前阅读，改为已见状态并告知协调，不能伪称盲测。

训练/校准manifest路径：`agent/src/baseline_agent/knowledge_answerability_v1/manifest.json`。其中哈希仅为静态文件归档，不是特征计算或质量验证。两分区合计216题/36篇原始文档的计划配额，实际目录分段/质量均未运行。新的72题留出当前未包含在仓库中；封存条件成立之前不申请运行。
