# #174 第12轮结果

INCOMPLETE，受测13cf3010feffbcb324642432022fba357c427bce，基线474e6068ca1f562a60d67518bba1619a1a3582ef。前两场景浏览器通过（11.8秒、18.7秒），三项调查全部COMPLETED，无模型/知识失败或Spring拒绝。

第三场景在创建工单前失败：用户点击确认按钮后HTTP201，但status=READY_TO_CONFIRM、confirmed=false、ticketCount=0；候选订单匹配，待处理订单数和完成订单数均0。后两场景NOT_RUN。App固定按钮发送“确认提交”，Spring在普通受理分支仍调用模型；如果模型返回UNDERSTANDING，便保留READY_TO_CONFIRM。修复复用已有confirm入口处理READY_TO_CONFIRM状态的精确按钮文本，保留内部校验和其他自然语言理解。

27次模型尝试（行动21、判断3、回复3）均HTTP200，22629已知token、usageTrusted=true；含受理代理计数为34逻辑调用/34尝试。程序费用上界0.219898元不是实扣。整轮1元继续PENDING，现32笔预留；历史核对上界2元加后续预留13元共15元，累计16.12元内剩余1.12元。旧冻结、失败与预留保留，禁止重跑run12。

见[报告](issue-174-live-report-12.json)、[指标](issue-174-live-12-formal-metrics.json)。本轮不能记作五场景通过，最终完整门禁尚未执行。
