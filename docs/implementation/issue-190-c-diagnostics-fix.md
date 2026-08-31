# Issue #190 C失败取证最小修复与离线验证

2026-08-31；[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [Draft PR203](https://github.com/Stellogic/customer-agent/pull/203)。本阶段只修复实验失败取证，**不是C方法质量通过，也不是正式交付**。

## 修复边界

仅修改 `knowledge_sufficiency_run.py` 和已有离线契约测试。对已经通过固定响应外层、单个output_text检查后的 `INVALID_DECISION_JSON`、`INVALID_DECISION_SCHEMA`、`INVALID_EVIDENCE`，在原错误抛出前保存 `decision_diagnostic`。数据进入原调用observation，沿原finally结算和账本持久化路径留存；没有通用日志框架或额外请求。

- 文本先替换当前API key的原文/JSON转义形式，再截取最多4096字符；保存完整脱敏文本SHA-256、脱敏字符数和是否截断。hash不冒称原始未脱敏报文hash。
- 保存JSON能否解析、顶层Python类型名；对象最多记录16个字段，每个脱敏名称最多64字符，仅记录值类型而不展开值。`field_count`保留原字段数量。
- 只保存固定合成回放的判定文本，不复制HTTP错误正文、请求头或整个供应商响应。这不是通用PII脱敏能力，不能据此外发真实客户/内部业务资料。
- 原解析、判定、错误码和停止行为不变；可信usage仍结算，未知usage仍保留预留，无重试。prompt/schema/配置/开发资产、BGE/RRF、共享账本规则和默认产品均未修改。

原[a轮真实中止证据](issue-190-c-development-attempt-a.md)保持不变：第5次原文 `NOT_CAPTURED`，5次请求、4/72完成、metrics=null；费用累计上界0.009084元、未结算0。本修复不能追回原文，也未修改或重置实际共享费用账本。

## 运行证据与失败对照

base均为 `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。RunId统一前缀 `issue190-c-diagnostics-20260831`：

| 后缀 | 受测起始HEAD / 工作树说明 | 结果 | 阶段耗时 |
| --- | --- | --- | ---: |
| a | `91feec4`＋未提交新增回归测试；原实现未改 | 10 PASS / 1 FAIL，预期RED：缺少decision_diagnostic | 3.9269869秒 |
| b | `02fb174`，期间Ruff格式化 | 12聚焦PASS；格式/lint PASS；类型1错误：外层异常分支payload可能未绑定；组件未运行 | 19.3210323秒 |
| c | `b7050fa`，期间仅Ruff换行 | 12聚焦PASS；Agent全目录Ruff lint/79文件格式检查、Pyright 0 errors；31相关离线组件PASS | 38.7290216秒 |

c轮聚焦pytest耗时0.96秒，相关组件pytest耗时14.96秒；二者包含相同12项C测试，不宣传成43项独立测试。31项组件由12项C测试及19项既有DeepSeek离线契约组成。新增两项回归使用合成畸形响应，验证非法结构留证、凭据脱敏、截断边界、metrics=null、可信usage结算及一次请求后停止；不重放已见开发题。

c轮格式化结果提交为 **`9301bc55ee9ba47a434072c5659c8b9e381a51c2`**，仅将长参数表达式换行。格式化之后的类型、lint及31项组件覆盖该源码；运行记录如实保留起始HEAD和 `working_tree_changed=true`，不伪造为干净HEAD运行。随后文档归档提交不是新受测SHA。

[原始日志/XML及索引](evidence/issue190-c-diagnostics-20260831/index.json)保存a/b/c全部失败和通过记录、源码文件hash以及本次调用的preflight脚本副本。只替换日志里的本机worktree路径，索引同时记录原始/归档SHA；RED日志中的credential字面量仅为离线合成测试值。脚本副本供审计，其原位置为仓库 `.local/`，不作为新增运行入口。

环境：Windows、本worktree已有CPython3.13.13虚拟环境；未安装/下载依赖。离线子进程清空真实key/实验开关，设置HF离线、既有certifi证书路径和 `NO_PROXY=*`，后者仅用于避免本机离线HTTP测试的代理初始化开销，不改产品客户端/TLS。工具精确版本、CPU峰值/内存、账单实付未采集。三阶段真实模型调用0次、付费API新增费用0元；不是总机器成本。

每次均持仓库共享锁，finally释放后仅一次宿主只读确认FREE，并成功发送LOCK_RELEASED。c轮结束已归还窗口；之后仅静态双轴审查与归档，不再启动运行。未运行真实C/72题、留出/#189、最终完整门禁，未切默认策略或合入。

## 审查与下一步

Standards / Spec 针对 `91feec4...9301bc5` 独立静态复核。本次实现由Codex按用户授权完成，不等同于用户逐行手写或生产效果。

### Standards

PASS（静态）@9301bc5，0项缺陷。取证仅覆盖已通过响应外层检查的三类判定错误；先脱敏再截断至4096字符，字段诊断限16项、名称限64字符，未扩展为通用框架。原错误继续抛出，可信usage仍由原finally结算，不重试、不生成质量指标；prompt、schema、判定和共享预算均未修改。新增测试覆盖非法结构留证、截断边界及结算与单次调用行为。审阅未运行检查、查询锁或读取留出及#189内容。

### Spec

PASS（静态）@9301bc5，0项缺陷。取证仅覆盖已通过响应封装检查的三类判定失败；先脱敏再截断，正文上限4096字符、字段摘要上限16项，保存脱敏全文哈希。原错误继续抛出，可信usage仍由原finally结算；未改变判定、预算或重试规则。新增离线用例覆盖非法结构、非法JSON、脱敏边界、结算及单次调用。未改历史NOT_CAPTURED记录或冻结合同。审阅未运行验证、模型或读取留出/#189。

两轴分别0项未决问题，不存在需修复的最高严重度项；该静态PASS不是C质量PASS。

修复仅使未来失败可诊断，不提供恢复/绕过STOPPED账本入口。下一次真实验证的题数、预算继承和停止边界仍由协调另行决定；不能因取证修复或账面余额擅自续跑。
