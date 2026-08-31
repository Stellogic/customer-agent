# Issue #190 剩余67题真实诊断：证据重复即停

2026-08-31；[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [Draft PR203](https://github.com/Stellogic/customer-agent/pull/203)。**STOPPED / INVALID_EVIDENCE：实际44次请求、43/67合法完成、后23项未发，metrics=null。** 没有评分、重试或恢复旧开发阶段。

## 固定边界与运行身份

- RunId：`issue190-c-remaining-diagnostic-20260831a`。
- 受测干净HEAD：`62b2c570901f9ad93b57a58a878e300beae973fb`；运行前fetch/base：`c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。源码与已离线验证及增量双CR的e449982一致，之后仅文档/证据。
- 原67项冻结请求清单SHA：`cfe20b1dec60b08f4624d7c931c7cdadda10b11a2f0bf1645aa09a5cf01fd622`。启动前核对归档hash；停止后静态比较确认本次完整67项request_manifest与该清单相同，实际44项恰为其有序前缀，没有补前5题。
- 运行前共享账本为0bd04be…快照，累计费用上界0.010773元、未结算0。独立 `remaining67_diagnostic_once` 追加记录，原开发STOPPED和已终结单题诊断不变。
- 冻结prompt/schema/模型/数据/BGE/Top5和判断规则没有改动。全阶段返回模型均为deepseek-v4-flash，fingerprint均null；未观察到标识漂移，不宣称云权重不可变。

## 触发停止的原文与静态原因

第44次请求是原集第49项 `rainfall-direct-1`，请求SHA `6581e61ddd9c77945d7730a8efdb54b7f21f25ec820cb5a50d5d90e9a06ca35c`；HTTP200、status=completed，response id `1305638c-1a27-4c51-b1b4-81dde9677562`。脱敏诊断完整保存94字符、truncated=false：

```json
{"sufficient":true,"evidence":[{"chunk":1,"quote":"口沿距地面七十厘米"},{"chunk":1,"quote":"承水口保持水平"}]}
```

两段引文都确实位于输入第1片段，顶层布尔和数组结构正确。失败原因是 **chunk编号1重复出现**：冻结prompt明确规定“每个编号只出现一次”，本地解析器用seen集合按同一规则拒绝第二条。JSON schema约束条目形状/数量/类型，但未表达按chunk字段唯一；因此此次可以符合结构schema，同时违反prompt及本地证据契约。不是JSON解析错误或两段引文不存在，也没有据此放宽校验、合并条目或补发请求。

本次有原文证据，可确认这一条违反既有非重复证据契约；它不证明候选召回、业务充分性判断或总体方法质量达标/不达标。原第5次的NOT_CAPTURED依然是独立历史缺口，不能用此次原文替代。

## Tokens、费用与耗时

| 项目 | 实际记录 |
| --- | ---: |
| 本阶段请求 / 合法完成 / 计划 | 44 / 43 / 67 |
| 未发请求 | 23 |
| 输入 / 输出 / 总token | 20602 / 816 / 21418 |
| 缓存命中输入 / reasoning token | 11264 / 0 |
| 最后失败响应输入 / 输出 | 458 / 39 |
| 本阶段新增已结算费用上界 | 69150微元＝0.069150元 |
| 全局累计已结算费用上界 | 79923微元＝0.079923元 |
| 未结算预留 | 0 |
| Python阶段耗时 | 45.42077820000122秒 |
| wrapper阶段耗时 | 48.8106544秒 |

运行本地时间2026-08-31T05:31:28.9449491+08:00至05:32:17.7594620+08:00，核价UTC日期2026-08-30。开始前再次核对[官方价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)和[官方Flash上下文配置](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash/raw/main/config.json)：仍按高峰未缓存输入3元/百万token、输出9元/百万token、1048576输入边界/256输出帽逐次预留3.148032元，可信usage结算释放差额。`20602×3＋816×9＝69150`微元；费用上界不是账单实付，未利用缓存/低峰优惠预支预算。所有44次usage均可信并结算，最后一次失败也结算1725微元。

环境沿用现有Windows/CPython环境及已有依赖；未安装下载模型、没有检索或拟合阶段。机器成本、峰值内存、账单实付未采集；阶段耗时不是生产吞吐量或延迟分位数。

## 原始证据、历史与窗口

[原始结果/launch/完整共享账本快照及索引](evidence/issue190-c-remaining-diagnostic-20260831a/index.json)按原字节保存并记录SHA，launch.log为空；失败原文在Python报告/账本的decision_diagnostic中，全文脱敏hash为 `f2e9c78849c04c44d4da9cc3d1e00ee1cf6a5f19b6c620f9dd8e551a7cedd981`。没有保存凭据、真实客户或内部业务资料。

索引静态比较确认原开发phase、原单题诊断phase和前6次全局调用记录完全不变。全局现在50次API调用，但原开发仍5请求/4完成/metrics=null；单题诊断与本阶段分别记录，不能合并补齐失败后计算质量PASS。

首次错误后立即停止，独立phase记为STOPPED，不能换RunId续跑。进程结束finally释放自有锁，单次宿主回读FREE并成功通知LOCK_RELEASED，窗口已归还。之后只有静态证据归档；无第二次运行、23题续跑、留出/#189、产品切换、下游解阻、最终完整门禁或合入。

本次实现/实验由Codex按用户授权执行；不把43条合法结构判定包装为43题答对、生产收益或用户逐行手写。后续是否调整诊断契约或验证边界由协调决定，本阶段不自行继续。
