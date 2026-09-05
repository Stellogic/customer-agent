# 客户回复适配器单次诊断冻结

运行标识 issue217-reply-diagnostic-20260905a；源码 d9d81da799673f840350a5d6c6e528666c236a13。

前轮浏览器产品验证停止在 confirmed=false；调查检查点显示行动7、判断1、沟通2、INVALID_MODEL_OUTPUT，未知usage。前轮1元完整预留保留，不复用，不把通过行动外推为#217完整通过。

本次只运行现有 DeepSeekResponsesCustomerCommunicationModel.compose 一次。固定合成订单 ORDER-DIAGNOSTIC-217，物流23小时、IN_TRANSIT、无补偿结论、两条固定证据引用、客户问句“请解释物流状态”。模型deepseek-v4-flash；原提示、schema、流读取、正文校验不变；max_attempts=1，deadline15秒，max_output_tokens384，输入序列化不超过12000字符。无LangGraph业务代次，无工单写入，不冒充浏览器产品验收。

通过sys.settrace仅观察既有模块的异常函数名/行号/类型；不修改返回值、吞错策略或解析过程。仅输出现有审计的HTTP状态、固定分类、token和耗时。密钥只在本轮进程环境；不输出正文、原始事件、输入输出内容或响应ID。若不能缩小问题，停止，不循环抽样。

预算：保留历史十三笔PENDING；用户报告历史实扣上界2元，以及当时至少3.8元可用；核对点后两笔各1元预留仍占用，新诊断只预留0.1元，当前保守剩余1.7元，授权累计保守占用4.1元小于8元。所有估计与风险预留均不当作平台实扣。诊断无论结果如何都保留PENDING，不自动结算或重试。

脚本：D:/customer-agent/.local/issue217-resume/reply-probe.ps1 和 reply-probe.py。先在独占Issue217锁下构建精确runtime标签，再无密钥离线检查固定请求约束，再读取原.env、预留并执行一次。只运行一个带精确名称的 --rm 容器；结束核实容器不存在、删除本轮标签并核对镜像不存在，释放锁。最终完整门禁与Ready仍待产品真实验收问题解决。