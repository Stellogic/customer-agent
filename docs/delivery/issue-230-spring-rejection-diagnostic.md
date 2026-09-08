# 核心验收的 Spring 拒绝原因采集

真实 judgmentv2probe01 的判断及回复均通过供应商响应形状检查，但提交结论后被归为 communication/FACT_CONFLICT。该分类不足以区分具体拒绝原因。

JdbcAgentInvestigationService.reject 已把原因写为 AGENT_COMMAND_REJECTED_ 前缀的审计事件；submit 使用 noRollbackFor=ResponseStatusException，保留拒绝审计。HTTP422本身只带通用描述，因此本次复用现有审计，避免新增业务接口或改变拒绝逻辑。

采集器新增顶层 springRejections，只查询本轮专属隔离数据库的匹配审计事件，保存 ticketId、去掉固定前缀的 code、occurredAt；按时间和审计id稳定排列。没有拒绝时为空列表。不采集actor、回复正文、请求或凭据，不将工单级审计推断为代次/调用级证据。

历史验收数据库已经清理，无法补回 judgmentv2probe01 的具体拒绝码。这个改动只改善后续运行诊断，不改变旧失败结果，不证明业务已修复，不增加付费调用。#230仍未完成，#174继续暂停。

验证记录：rejection-red01以4项缺少springRejections字段失败复现遗漏；修正后的9项聚焦测试通过。issue230-rejection-agent01规范化Agent检查为579通过、3跳过，格式/静态/类型检查通过；Standards及Spec均PASS。未运行真实模型或最终完整交付门禁。
