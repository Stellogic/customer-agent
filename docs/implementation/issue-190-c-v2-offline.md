# Issue #190 C-v2版本化实现与离线验证

[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [Draft PR203](https://github.com/Stellogic/customer-agent/pull/203)；2026-08-31。实施依据为已接受的[单一合同变更和完整72题计划](issue-190-c-v2-contract-proposal.md)。本阶段只离线验证，不允许真实72题、留出/#189、产品切换、最终门禁或合入。

## 实现边界

- 唯一方法变化：C-v2允许同一编号多条原文摘录，保留精确字段、布尔/数组关系、最多5条、原文1–24字符、编号范围和供应商/usage检查。C-v1资产未改，默认解析仍拒绝重复编号。没有静默修改原始响应。
- 新增显式 `-CV2WholeOnce` / `--c-v2-whole-once`，独立opt-in和 `seen_development_c_v2_once` phase，复用原HTTP/取证/预算实现；不是续跑入口。账本准入绑定最后50次调用的原始快照，缺失/改变历史即停，旧STOPPED不重开。
- 新阶段仅能按冻结顺序逐项发送完整72题，同一阶段即使换RunId也不能重跑。错误即停、未知usage保留预留；共享6元预算不重置。完整72项合法后才计算既定四指标；契约通过与语义通过分开记录，输出混淆计数/分母。所有判断仅属于已见合成开发集。
- 原始摘录全部保留；统计按articleId记录不同引用文章数，不把同一文章的多条摘录或多个chunk计为多个独立来源。不同文章数也不代表内容在事实来源上独立。指标仍按问题和固定检索排名计算，不按摘录数加分。
- 授权/版本来自已固定、hash核验的原检索快照，运行时限制实际输入Top5和INTERNAL范围；离线回放不会重新验证数据库权限过滤，不宣称已通过产品安全或最终质量门。

## 冻结清单

目录：`agent/src/baseline_agent/knowledge_sufficiency_v2/`。版本名为 `context-sufficiency-c-v2`；schema形状未变，但独立归属新版本。模型别名、temperature=0、reasoning=none、输出256、无重试及价格/预算配置保持。质量阈值0.90/0.75/0.90/0.85同时记录于新config，运行前检查与既有指标定义一致。

| 资产 | SHA256 |
| --- | --- |
| prompt.txt | a18bfb7648847dd9b040cdcbb9832e21e50143b9b1496068a1b645c2c4fa9b32 |
| schema.json | 27ef4d19440b4279ac4b0426eb299e87445a455be5206716ad82c0da6f3733f4 |
| config.json | 3716498d23b0ce1586599d7ad6f7ae28bab913414b28607ea1105899a3167212 |
| requests.json，完整有序72项 | 7234a4f5812e976f3e3efc594fc3e2b0760b46b760b0f2a8d403525fbfd5cd91 |

`scripts/materialize-knowledge-sufficiency-v2.py`仅在持锁时调用冻结构造器物化请求hash，不创建HTTP客户端或账本。题目/标签/固定Top5归档不改；旧结果不重新解释或评分。新请求字节因prompt/schema名称版本变化而不同，不能与旧合同混称一次实验。

## 验证进度（待最终离线归档补齐）

已同步main `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`；本次无迁移变更，未发布向量迁移仍V42，main的V36/V37等保持原样。

首轮RunId `issue190-c-v2-offline-20260831a`：从79e07a6的工作树修改启动，受锁物化72项、11项聚焦通过；随后lint因新测试import顺序失败，类型/组件/实际入口尚未执行。仅工程预检失败，不是模型/质量FAIL。用静态导入移动修复，不改方法或数据。原日志保留，后续以新RunId复验。

共享账本SHA前后均 `c11630710263c473fbf938b60e789b33ef93b776021e258976825fdf47206a50`，累计上界0.079923元、未结算0；本阶段真实请求0、费用0。原50次请求、所有失败及STOPPED记录不变。Windows/现有CPython环境，无安装下载；账单实付、峰值内存未采集。代码由Codex按授权实施，不等于用户逐行手写；离线MockTransport不是模型回退或质量证据。
