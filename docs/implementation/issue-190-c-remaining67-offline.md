# Issue #190 剩余67题离线预检与请求字节清单

2026-08-31；[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [Draft PR203](https://github.com/Stellogic/customer-agent/pull/203)。**本阶段离线PASS；真实67题仍未运行或获准，非质量PASS/正式交付。**

后续另获授权的[真实诊断记录](issue-190-c-remaining67-attempt-a.md)在第44次证据契约失败时停止；本页保留当时离线阶段的状态与证据，不覆盖真实中止结果。

## 运行身份和验证覆盖

RunId：`issue190-c-remaining-offline-20260831a`。开始前fetch的main/base为 `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`，已合入迁移最高V41，本分支未发布V42无新编号冲突，未改迁移。起始干净HEAD `1a9dac4455193cf32b4ae8a997dcb68a639a449a`。

| 检查 | 实际结果 |
| --- | --- |
| PowerShell入口语法 | PASS |
| 实际pwsh→uv→Python入口 | 普通开发、第5题诊断、剩余67题诊断三模式均通过argparse，在MISSING_API_KEY处预期停止；API=0 |
| C聚焦测试 | 23 PASS，pytest 2.59秒 |
| Agent全目录Ruff lint/格式 | PASS，79文件格式检查通过 |
| Agent Pyright | 0 errors / 0 warnings |
| 相关离线组件 | 42 PASS，pytest 16.69秒，包含上述23项C测试及19项既有DeepSeek离线契约 |
| 冻结构造器物化请求hash | 67项，原第6–72项顺序；HTTP=0、模型=0 |
| 阶段总耗时 | 55.7541624秒，非模型延迟或生产性能 |

Ruff仅修改Python runner和测试的排版，随后格式、lint、类型、42项组件及请求物化均在该排版后执行。保存排版的源码提交为 **e44998256d5b352641873e48f8dfabd7de1d5c44**。原phase记录保留起始HEAD及 `working_tree_changed=true`，不伪造为干净e449982运行；排版无行为或冻结方法变化。三模式入口与聚焦发生在排版前，后续组件覆盖相同语义源码。归档文档提交不是新受测SHA。

[全部日志/XML/元数据索引](evidence/issue190-c-remaining-offline-20260831a/index.json)保存原始与归档SHA；日志/XML只替换本机worktree路径，JSON按原字节保存。包含preflight和物化脚本副本，实际执行位置为本worktree `.local/`，副本仅供审计，不作为新增产品入口。

## 物化后的有序请求清单

本阶段用原 `development_rows`、`contract`、`request_body`，与实际runner相同的 `json.dumps(..., ensure_ascii=False, separators=(",", ":")).encode("utf-8")`，仅构造第6–72项。没有执行BGE、检索、特征计算、拟合或HTTP，也未写共享费用账本。

- 输入ID/顺序清单SHA：`d9e11464642afb0de4fe2b4cf170f62b298284f681f2f7843e5e53c349e13bf1`，与静态提交不变。
- [67项请求字节hash清单](evidence/issue190-c-remaining-offline-20260831a/materialized/request-list.json)SHA：**cfe20b1dec60b08f4624d7c931c7cdadda10b11a2f0bf1645aa09a5cf01fd622**。
- 清单记录冻结来源/合同hash及每项query_id、request_sha256；[物化元数据](evidence/issue190-c-remaining-offline-20260831a/materialized/materialization.json)记录起始HEAD/base、各请求UTF-8字节长度和本地物化耗时。字节长度不是计费token估算。

这份文件是未来真实请求的离线字节hash依据，不是67次已发请求证据。实际阶段仍须由原构造器产生相同顺序请求，启动前保存独立phase完整请求表，每次按表预留/核对；不得换题、重排或补调用前5题。

## 历史、预算与窗口

阶段结束只读核对共享账本SHA仍为 `0bd04be15c1c6e1eeb96f96cdadf994aa14b5a0f2d894e38c3426193896b40f8`，与单次诊断b后完全相同：累计已结算费用上界0.010773元、未结算0，本轮新增付费0。原开发STOPPED/5请求/4完成/metrics=null、旧NOT_CAPTURED与已终结单次诊断均未改变，没有新增真实remaining67 phase。

本轮运行复用Windows/已有CPython3.13.13虚拟环境；没有安装或下载。测试子进程清空真实key，HF/UV离线，使用已有certifi及仅进程范围NO_PROXY；MockTransport仅用于离线契约，不是模型回退。精确工具版本、CPU/内存峰值、机器成本未采集，API新增0元不等于机器成本0元。

运行脚本finally释放自有锁，结束后仅一次宿主只读回读FREE并成功发送LOCK_RELEASED，窗口归还。之后仅静态审查与归档；未启动真实67题、留出/#189、产品切换、最终完整门禁或合入。

## 增量双轴审查

固定差异 `1a9dac4...b9a5684`；此前1252495功能静态双轴PASS继续作为对应源码证据，不替代本次新增运行记录。

### Standards

PASS（静态）@b9a5684，0项缺陷。排版增量未见语义变化。日志支持三模式入口、23项聚焦、42项组件及格式/类型通过；文档准确区分起始SHA、排版后源码与归档提交，保留working_tree_changed=true。物化器复用固定构造和序列化，仅输出有序请求hash及元数据，不创建HTTP客户端或修改账本。离线PASS未被表述为真实67题或质量通过；审阅未新增运行、查询锁、发送HTTP或读取留出/#189。

### Spec

PASS（静态归档）@b9a5684，0项缺陷。源码增量仅排版，无语义或预算变化。日志支持三模式入口、23项聚焦、42项组件及格式/lint/types通过；文档准确区分起始SHA与排版后覆盖。67项清单保留原序及冻结资产hash，物化脚本不创建HTTP客户端或费用账本。材料明确新增费用0、累计上界0.010773元，原历史不变；离线PASS不代表模型质量或交付通过。审阅未运行、查询锁或读取留出/#189。

两轴各0项未决；本节仅补记审查，不产生新运行证据。

只有工程离线预检完成；67题即便未来诊断成功仍metrics=null，不把分阶段筛除失败后的分数当质量门或下游解阻依据。代码/实验由Codex按授权执行，不能包装为用户逐行手写或生产收益。
