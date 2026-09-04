# #217 调查输出额度修复

基线 `origin/main@ca0977a`，独立分支 `codex/issue-217-output-limits`。本票承接 #174 真实调查 OUTPUT_TRUNCATED，不将产品修复混入 PR #214。

只区分请求输出需求：普通动作保留128 token，SUBMIT_CONCLUSION 使用独立1024 token额度，可配置范围512至2048。证据schema、引用校验、提示、模型、重试次数与循环总预算不变。1024是针对带证据结构的初始修复值，尚不能声称真实截断已消失。

回归复用既有 MockTransport 请求与合法证据响应，普通动作验证原128不变，结论含/不含知识查询均验证1024。旧实现运行结果为2 failed、17 passed：两项均明确报告128 != 1024。该断网测试只证明请求配置，不证明模型质量。

`issue217-output-red` 的清理函数对未构建镜像执行删除时遇到原生命令错误，提前退出。权威锁已空闲，但状态回读 RECOVERY_REQUIRED，仅发现本轮镜像 `customer-agent/agent-test:gate-issue217-output-red`。未自动删除残留或再次运行测试。临时聚焦脚本下一次应只删除本轮实际构建的镜像，且在嵌套finally中释放锁。

Standards / Spec 双轴静态审查均 PASS，未发现阻塞；不替代运行验证。临时聚焦脚本已准备只删除本轮实际构建镜像，并用嵌套finally保证执行锁释放，尚未运行该脚本。

修改已准备提交 Draft PR；修正后的绿测、格式/类型、真实复验与最终完整门禁均未运行，未合入、未关票。此次无DeepSeek调用。测试仍需等待 RECOVERY_REQUIRED 残留由协调处理，不绕过恢复状态。
