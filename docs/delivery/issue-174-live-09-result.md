# #174 第9轮真实验收结果

状态：INCOMPLETE。受测 HEAD b115982e442ddc33b12f803abe8f5b7ddcbeb435，基线 474e6068ca1f562a60d67518bba1619a1a3582ef。L174-01 浏览器通过（10.9 秒），两次调查一项 COMPLETED、一项 HANDED_OFF；场景后发现拒绝即停止，后四场景 NOT_RUN。

Spring 审计事件为 AGENT_COMMAND_REJECTED_INVALID_EVIDENCE_APPLICABILITY（1 次）。本地受控元数据显示被拒绝结论风险场景为 DUPLICATE_CHARGE，HTTP 422；不是供应商请求失败。FACT_CONFLICT 是当前 graph 对此类 422 的归类，不能据此断言订单事实相互矛盾。观察器记录的 conclusionEvidenceCount=2 来自顶层 evidenceRefs（回复引用），不是 sufficiency evidence 声明数量。没有保存完整证据声明，无法回溯具体缺失或误绑定的适用性项，不能将候选原因当作已证实根因。

行动 14 次、判断 2 次、客户回复 2 次均 HTTP 200，usageTrusted=true。已知 14779 token；加上 3 次受理操作代理计数为 21 逻辑调用/21 尝试，受理精确 provider usage 仍未持久化。程序费用上界 0.113578 元不是平台实扣；整轮 1 元继续 PENDING。当前共 28 笔预留；历史用户核对上界 2 元加后续 17 笔预留 9.9 元为 11.9 元，累计授权 12 元内保守未预留 0.1 元，不是账户余额。

首次启动在 Docker 未运行的预检阶段退出，没有发出模型请求，账本确认未留下 run09 预留；恢复 Docker 后才执行本次唯一付费运行。旧失败与预留保留，禁止重跑 run09。资源清理后权威锁回读 TEST_GATE_FREE。#174 最终完整门禁 NOT_RUN，PR #214 保持 Draft，#174/#226 未关闭。

见[运行报告](issue-174-live-report-09.json)、[正式指标](issue-174-live-09-formal-metrics.json)、[调用前冻结](issue-174-live-09-freeze.json)。调用前冻结保持不变，当前目录禁用再次执行。
