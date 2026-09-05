# #219 客户回复合法流分片修复

基线 origin/main@ca0977a。承接 #217 真实调查已越过行动/判断、客户回复仍失败的阻塞；保持独立产品修复。

单次合成回复适配器诊断收到 HTTP200，594ms 后在 `_read_streamed_response` 的正文前缀检查抛出 INVALID_OUTPUT。仅保存函数/行号/异常类和审计分类，没有模型正文，因此不猜测本次实际触发的正文规则。

在同一源代码上使用既有合法无补偿回复和 MockTransport，仅将 SSE 分别切在 body 起始与 ORDER-C129 中间。`issue217-reply-fragments-red` 两项均在相同前缀检查失败：2 failed in 0.27s。这证明了合法流分片也会被误拒，不声称所有真实回复失败都已同源定位。

最小修复为：正文尚无字符且 JSON 字符串未闭合时继续等待；位于当前前缀末尾的订单号，只在它仍是授权订单号的前缀时允许继续。Python 与 Spring 使用相同的中间前缀规则。JSON 字符串闭合后，先按完整正文校验再发布；完整空正文、带分隔符的错误订单或已偏离授权订单的字符仍拒绝。普通回复继续增量发布，最终 schema、证据及完整正文约束保留。未换模型或提示，未新增重试。

回归复用现有流式响应工厂，验证合法分片最终正文与全部已发布增量拼接相同、没有空增量或重复，并保留最终空正文和错误订单拒绝。`issue219-reply-fragments-green`：61 passed in 0.72s；唯一警告为只读测试挂载无法写 pytest 缓存，不影响结果。

沿用 #217 已验证的三行 test 阶段 Node/npm 复制（固定版本与前端一致），解除 Pyright 的首次动态下载阻塞；base/runtime 不增加 Node。`issue219-static-20260905a`：Ruff format/lint PASS，Pyright 0 errors/0 warnings，pytest 458 passed、3 skipped（34.68秒）。两个运行均精确清理自身镜像并释放共享锁，没有供应商调用。

PR #220 由 Draft 转 Ready 触发一次集中 AI 风险审查。批量处理两项有证据的发现：Spring 原规则仍拒绝合法订单前缀；Python 解析器丢失正文字符串结束状态，可能先发布不完整的错误订单号再拒绝。后者独立红测为 1 failed、25 deselected（0.36秒），旧实现实际发布了 `订单 ORDER-C1`。

修复后的聚焦回归 62 passed；`issue219-review-static` 的 Ruff format/lint PASS、Pyright 0 errors/0 warnings、pytest 459 passed、3 skipped（35.89秒），后端 Gradle check（含 Checkstyle、Spotless、测试）PASS。Standards / Spec 初审与本批增量确认均 PASS。运行没有供应商调用，精确清理自身镜像并释放共享锁。

同时增加真实 Spring API / PostgreSQL smoke：合法订单前缀返回 202，偏离授权订单的后缀返回 422，同序号正确后缀仍返回 202；读回拼接正文、分片序号和两条客户增量事件。该 smoke 已在 `issue219-final-20260905a` 通过。该次完整门禁在 b88351f 通过（23分钟），包括 59 个主浏览器场景及并行、时钟和会话阶段；资源已精确清理。它只能证明此旧提交，不用于以下新增修正的最终交付。

新提交的自动审查提供了闭引号单独分片的进一步复现：旧代码在引号到达前已发布 `订单 ORDER-C1`。`issue219-quote-red` 为 1 failed（0.21秒）。因此未闭合正文现在只暂存末尾仍可能属于授权订单号的部分，其前面正文继续发布；完整订单或后续文字到达后正常续发，错误正文关闭时先拒绝。回归同时验证订单号首字母与中段切分、闭引号单独分片；没有把普通回复改成全量缓冲。

`issue219-quote-green`：聚焦 64 passed（0.25秒）；Ruff format/lint PASS、Pyright 0 errors/0 warnings、Agent 全量 461 passed、3 skipped（33.44秒），Standards / Spec 本批增量确认均 PASS。最终完整门禁与合并读回集中记录于本票 PR。离线验证不等于真实模型语义或 #217/#174 验收；原 confirmed=false 和历史未知用量继续保留，后续按独立冻结运行处理。

自动审查进一步发现 Python 缺少 Spring 既有的短订单前缀终态检查。`issue219-short-prefix-red` 使用 ORD、ORDER、ORDER- 三个闭合正文，旧适配器均未拒绝：3 failed（0.25秒）。补充与 Spring 等价的长度至少 3、单词边界、授权订单残缺尾部检查，统一返回固定 ORDER_REFERENCE_SCOPE 分类。`issue219-prefix-parity`：聚焦 67 passed（0.23秒），Ruff format/lint PASS、Pyright 0 errors/0 warnings、Agent 全量 464 passed、3 skipped（39.90秒）。Standards / Spec 集中对照中间前缀与完整订单规则后均 PASS。此批尚未启动最终完整门禁，没有新增供应商调用。
