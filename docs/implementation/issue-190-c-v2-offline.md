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

第二轮RunId `issue190-c-v2-offline-20260831b`，受测干净SHA `7c3759ac58c7b140582da7ae4d79e8b5f1f2ad23`：四模式实际PowerShell→uv→Python入口均通过argv解析并在MISSING_API_KEY前置停止；11聚焦、53组件、81文件格式检查、lint及Pyright（0错误/警告）PASS，耗时59.6588206秒。无真实API，账本hash前后相同。该通过覆盖7c3759a，**不覆盖下述静态修复**。

同SHA静态Standards PASS；Spec指出预登记要求分层记录，而原实现只记整体契约PASS。最小修复为在C-v2观察记录中增加 `json_syntax / decision_schema / evidence_fields / cross_fields / authorized_chunks / verbatim_quotes` 的PASS/FAIL/NOT_EVALUATED，逐层快速失败，不改变合法集合、错误码、原文判断或停止行为；未执行层不能误记PASS。v1不输出新字段，仍按旧限制拒绝重复编号。新测试覆盖分层失败及持久化取证；请求构造、全部四项资产hash和质量阈值未改。该修复待增量双CR及另一个获准离线窗口复验，不能复用7c3759a的预检结论。

两轮结束均finally释放自有锁并单次宿主回读FREE，LOCK_RELEASED均已送达协调；b结束已主动归还阶段窗口，当前不运行。原始日志及JUnit见相应[evidence](evidence/) RunId目录。首轮6.6613063秒不含后续修复时间；静态工作耗时未采集。

共享账本SHA前后均 `c11630710263c473fbf938b60e789b33ef93b776021e258976825fdf47206a50`，累计上界0.079923元、未结算0；本阶段真实请求0、费用0。原50次请求、所有失败及STOPPED记录不变。Windows/现有CPython环境，无安装下载；账单实付、峰值内存未采集。代码由Codex按授权实施，不等于用户逐行手写；离线MockTransport不是模型回退或质量证据。

## Standards

静态PASS @ `31eaa45`，0项缺陷。独立standards_review确认分层检查保持原合法集合/错误码，失败后未执行层为NOT_EVALUATED；v1不新增观察字段；未改变请求合同、阈值、预算或重试。确认文档未将7c3759a的通过冒称覆盖本修复。

## Spec

静态PASS @ `31eaa45`，原唯一报告契约缺口已修复。独立spec_review确认C-v2成功及失败均保存六层状态，供应商/usage失败不误记契约通过，旧合同和历史账本保持。两位审查者均未运行验证、查询锁或读取留出/#189。

两轴最终静态发现均0。**当前交接状态：CODE_READY_OFFLINE_RECHECK_REQUIRED**。待协调重新分配离线窗口后，对31eaa45源码完成格式/类型、12项新版聚焦、旧版与相关组件及四模式实际入口复验；项目最终完整门禁和真实模型阶段仍未授权。上文测试项数量12是待运行用例数，不是已通过数。
