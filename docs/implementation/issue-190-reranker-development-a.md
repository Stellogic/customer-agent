# #190：reranker 开发验证与输入审计（已停止采用）

2026-08-31；[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [PR203](https://github.com/Stellogic/customer-agent/pull/203)。受测 HEAD `9bbeca00b202e077963c0e8832dd2b2b4dae8994`，源码 `04d7ee9c7129e00741db22f04ccc72492253738e`，base `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。源码之间只有文档与证据变更。

## 实际结果

| RunId | 结果 | 实际范围 | 墙钟耗时 |
| --- | --- | --- | --- |
| issue190-reranker-prepare-20260831b | 准备失败，非质量失败 | curl 续传得到 40,761,161 字节后连接关闭（退出 56），权重总计 245,527,557 字节，未完整校验或加载 | 65.38 秒 |
| issue190-reranker-development-20260831a | INFEASIBLE | 72/72 已见合成开发题、360 对评分、73 个预定候选阈值，无可行解；selected=null、metrics=null | 71.86 秒（Python 阶段 67.32 秒） |
| issue190-reranker-input-audit-20260831a | 输入审计 PASS，非质量 PASS | 360 对仅 tokenizer 审计，最长 62 token，原输入与既定 512 token 截断后输入完全一致，changed_pairs=0；未重评分或重选阈值 | 14.85 秒 |

原 prepare-a 失败及部分权重先保留，b 失败也未覆盖。随后用户手动下载，提供了“模型完整校验通过”的终端输出；手动 RunId、完整总耗时未采集。development-a 在锁内重新验证固定 5 文件，日志 `FIXED_FIVE_FILES_VERIFIED`，并确认共享 development 记录此前不存在，才进行唯一一次评分。共享终态 INFEASIBLE 保留，未删除、覆盖或换 RunId 绕过。

模型 `BAAI/bge-reranker-base` revision `2cfc18c9415c912f9d8155881c133215df768a70`，CPU float32 / batch 1 / threads 1；协议 SHA256 `5f9b0bed409771c9d45360e7400775be077e87d5afd48c51c8a49c448bb520e9`。源开发归档 SHA256 `b4ec9872012c90c795b0356a74f9ac3f4f7343bff207a76b16d9185265b06387`，数据 SHA256 `4ba56767f8729ba064f614c856076c30f08e5852bad0255c2bf6b443c31014b6`。完整协议、模型文件哈希、环境和逐项原始评分见归档，不复制权重进 Git。

## 解释与限度

方法是原授权 RRF Top-5 各片段相关性 raw logit 的最大值加唯一阈值选择，不重排候选。36 个有答案和 36 个无答案样本的分数有重叠，73 个预定阈值没有一个同时满足全部旧开发门槛。输入审计排除了这批样本的截断因素；这不等于证明所有工程路径绝无缺陷，也不能推广为所有 reranker 都无效。

没有选“最接近”的阈值，不计算或冒充最终质量 PASS，不进入独立留出或 #189 冻结评测。用户随后批准 [rag-layered-v2](../eval/rag-layered-v2.md)：检索只提供授权片段，同一次 DeepSeek 回答负责充分性；这是产品职责与正式验收变更，不是对该失败补判通过。

三个运行都在共享锁内，结束后释放自身锁并只读一次确认当时 FREE，均已通知协调；输入审计后进入静态阶段并交出窗口。新增付费模型 API 调用 0、费用 0，未读取或修改活预算账本；内存/CPU 峰值、电费未采集。所有数据是已见合成开发数据，不是盲测、生产规模或线上收益；代码与记录由 Codex 生成/整理，不代表用户逐行手写。

## 持久化证据

- [prepare-b 原始失败与文件哈希](evidence/issue190-reranker-prepare-20260831b/index.json)
- [development-a 完整报告、72 行评分及 73 阈值](evidence/issue190-reranker-development-20260831a/index.json)
- [input-audit 原始报告与实际脚本](evidence/issue190-reranker-input-audit-20260831a/index.json)

归档仅替换本机工作树和用户目录前缀；源文件 hash 与归档 hash 同时记录。原始文件与部分模型仍留本地。历史实验代码、配置、旧日志、STOPPED、校准失败和共享预算均保留；默认产品不再依赖这些评分方法。
