# #219 客户回复合法流分片修复

基线 origin/main@ca0977a。承接 #217 真实调查已越过行动/判断、客户回复仍失败的阻塞；保持独立产品修复。

单次合成回复适配器诊断收到 HTTP200，594ms 后在 `_read_streamed_response` 的正文前缀检查抛出 INVALID_OUTPUT。仅保存函数/行号/异常类和审计分类，没有模型正文，因此不猜测本次实际触发的正文规则。

在同一源代码上使用既有合法无补偿回复和 MockTransport，仅将 SSE 分别切在 body 起始与 ORDER-C129 中间。`issue217-reply-fragments-red` 两项均在相同前缀检查失败：2 failed in 0.27s。这证明了合法流分片也会被误拒，不声称所有真实回复失败都已同源定位。

最小修复为：正文尚无字符时继续等待；位于当前前缀末尾的订单号，只在它仍是授权订单号的前缀时允许继续。完整空正文、带分隔符的错误订单或已偏离授权订单的字符仍拒绝。普通回复继续增量发布，最终 schema、证据、完整正文及 Spring 业务校验不变。未换模型或提示，未新增重试。

回归复用现有流式响应工厂，验证合法分片最终正文与全部已发布增量拼接相同、没有空增量或重复，并保留最终空正文和错误订单拒绝。`issue219-reply-fragments-green`：61 passed in 0.72s；唯一警告为只读测试挂载无法写 pytest 缓存，不影响结果。

沿用 #217 已验证的三行 test 阶段 Node/npm 复制（固定版本与前端一致），解除 Pyright 的首次动态下载阻塞；base/runtime 不增加 Node。`issue219-static-20260905a`：Ruff format/lint PASS，Pyright 0 errors/0 warnings，pytest 458 passed、3 skipped（34.68秒）。两个运行均精确清理自身镜像并释放共享锁，没有供应商调用。

Standards/Spec、集中 AI 风险审查、最终完整本地门禁与合并读回集中记录于本票 PR。离线验证不等于真实模型语义或 #217/#174 验收；原 confirmed=false 和历史未知用量继续保留，后续按独立冻结运行处理。
