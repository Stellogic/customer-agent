# #174 第13轮结果

INCOMPLETE，受测16583622c7de665f141c597621809a95b1faa7c0，基线474e6068ca1f562a60d67518bba1619a1a3582ef。第一场景浏览器通过，但两项调查均转人工，usageTrusted=false后停止，后四场景NOT_RUN。

逐次元数据包含：行动TRANSIENT_PROVIDER_ERROR（无HTTP状态、usage未知）；回复SCHEMA_MISMATCH（HTTP200、usage未知），随后纠正调用CONNECTION_TIMEOUT及PUBLIC_REPLY_PUBLISH_FAILED。不能据此断言首次流schema失败具体字段或暂时性错误的网络根因。报告含受理代理计数18逻辑调用/19尝试，9682已知token；程序观察上界0.092410元不覆盖未知usage，也不是平台实扣。

整轮1元继续PENDING，现33笔预留；历史核对上界2元加后续预留14元共16元，累计16.12元内保守剩余0.12元。本次用户追加的可用3.22元中，单次诊断预留0.1元及run11/12/13各1元全部保留。旧冻结与失败保留，禁用run13重跑，不再发出真实调用。

离线复现另一个明确缺陷：graph已经发布CONTENT_DELTA后遇到模型失败，仍纠正调用并从第0块重新发布。回归实际得到2次compose而预期1次；尚未发布的对照保持2次。候选记录发布尝试，已有片段后失败直接进入既有handoff，不再从头纠正；未发布时原纠正机会保留。该修复防止二次发布失败，不能据此声称供应商错误或首次SCHEMA_MISMATCH已修复。Agent完整组件检查通过：472 passed / 3 skipped，格式、lint、pyright通过。红绿日志为.local/issue174-stream-retry-red.log与.local/issue174-stream-retry-green.log。

固定确认按钮修复此前Backend check已通过；本轮未到第3场景，不能声称完成其真实回归。当前最好一次完整路径证据仍仅为run12前两场景通过。最终完整门禁NOT_RUN，PR #214保持Draft，#174/#226未关闭。

见[报告](issue-174-live-report-13.json)、[指标](issue-174-live-13-formal-metrics.json)、[冻结](issue-174-live-13-freeze.json)。
