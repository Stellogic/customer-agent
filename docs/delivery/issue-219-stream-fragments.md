# #219 客户回复合法流分片修复

基线 origin/main@ca0977a。承接 #217 真实调查已越过行动/判断、客户回复仍失败的阻塞；保持独立产品修复。

单次合成回复适配器诊断收到 HTTP200，594ms 后在 `_read_streamed_response` 的正文前缀检查抛出 INVALID_OUTPUT。仅保存函数/行号/异常类和审计分类，没有模型正文，因此不猜测本次实际触发的正文规则。

在同一源代码上使用既有合法无补偿回复和 MockTransport，仅将 SSE 分别切在 body 起始与 ORDER-C129 中间。`issue217-reply-fragments-red` 两项均在相同前缀检查失败：2 failed in 0.27s。这证明了合法流分片也会被误拒，不声称所有真实回复失败都已同源定位。

最小修复为：正文尚无字符且 JSON 字符串未闭合时继续等待；位于当前前缀末尾的订单号，只在它仍是授权订单号的前缀时允许继续。Python 与 Spring 使用相同的中间前缀规则。JSON 字符串闭合后，先按完整正文校验再发布；完整空正文、带分隔符的错误订单或已偏离授权订单的字符仍拒绝。普通回复继续增量发布，最终 schema、证据及完整正文约束保留。未换模型或提示，未新增重试。

回归复用现有流式响应工厂，验证合法分片最终正文与全部已发布增量拼接相同、没有空增量或重复，并保留最终空正文和错误订单拒绝。`issue219-reply-fragments-green`：61 passed in 0.72s；唯一警告为只读测试挂载无法写 pytest 缓存，不影响结果。

沿用 #217 已验证的三行 test 阶段 Node/npm 复制（固定版本与前端一致），解除 Pyright 的首次动态下载阻塞；base/runtime 不增加 Node。`issue219-static-20260905a`：Ruff format/lint PASS，Pyright 0 errors/0 warnings，pytest 458 passed、3 skipped（34.68秒）。两个运行均精确清理自身镜像并释放共享锁，没有供应商调用。

PR #220 由 Draft 转 Ready 触发一次集中 AI 风险审查。批量处理两项有证据的发现：Spring 原规则仍拒绝合法订单前缀；Python 解析器丢失正文字符串结束状态，可能先发布不完整的错误订单号再拒绝。后者独立红测为 1 failed、25 deselected（0.36秒），旧实现实际发布了 `订单 ORDER-C1`。

修复后的聚焦回归 62 passed；`issue219-review-static` 的 Ruff format/lint PASS、Pyright 0 errors/0 warnings、pytest 459 passed、3 skipped（35.89秒），后端 Gradle check（含 Checkstyle、Spotless、测试）PASS。Standards / Spec 初审与本批增量确认均 PASS。运行没有供应商调用，精确清理自身镜像并释放共享锁。

同时增加真实 Spring API / PostgreSQL smoke：合法订单前缀返回 202，偏离授权订单的后缀返回 422，同序号正确后缀仍返回 202；读回拼接正文、分片序号和两条客户增量事件。此 smoke 尚待最终完整本地门禁执行；最终门禁与合并读回集中记录于本票 PR。离线验证不等于真实模型语义或 #217/#174 验收；原 confirmed=false 和历史未知用量继续保留，后续按独立冻结运行处理。
