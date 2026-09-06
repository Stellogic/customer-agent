# #174 第10轮真实验收结果

状态：INCOMPLETE。受测 HEAD 0ca2a67b9fb5eb26211b7593a55c7537ec00db35，基线 474e6068ca1f562a60d67518bba1619a1a3582ef。L174-01 浏览器通过（11.0秒），两项调查一项 COMPLETED、一项 HANDED_OFF；后四场景 NOT_RUN。

行动接缝的一次最终响应被解析器归为 SCHEMA_MISMATCH。该请求 HTTP 200、responseStatus=completed，输入1700、输出294、总1994 token；没有 OUTPUT_TRUNCATED，不能据此提高输出上限或断言具体字段错误。14次行动、1次判断和1次回复共16次模型请求均HTTP200；Spring拒绝计数为空。由于一项调查提前在行动阶段失败，不能把未再出现上轮Spring拒绝当作问题已修复。

usageTrusted=true，已知17103 token，包含3次受理操作代理计数后为19逻辑调用/19尝试。程序费用上界0.118541元不是平台实扣。整轮1元继续PENDING，当前29笔旧预留完整保留；历史核对上界2元加后续18笔预留10.9元共12.9元，累计授权13元内保守未预留0.1元。受理精确provider usage仍未持久化，不用程序估算释放失败轮预留。

未保存原始响应，当前元数据不足以区分解析器的多个SCHEMA_MISMATCH分支。后续离线验证仅补充失败分支的源码行号观察能力，不再凭宽泛错误码改提示或增加付费重试。run10冻结保持，当前目录禁用重跑。真实验收未通过，最终完整门禁NOT_RUN，PR #214保持Draft。

见[报告](issue-174-live-report-10.json)、[正式指标](issue-174-live-10-formal-metrics.json)、[冻结](issue-174-live-10-freeze.json)。

离线诊断验证：使用现有 Agent 测试镜像、禁网真实适配器与合成响应，成功路径不变；注入重复证据引用后，观察器准确记录拒绝分支的源码行号。仅新增整数 actionFailureLine，不保存异常文本、源码、局部变量或原始响应。该注入样本不代表 run10 实际根因。日志 .local/issue174-action-observer-offline.log。验收与离线验证结束后权威锁回读 FREE。
