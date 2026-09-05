# #217 调查输出额度修复

基线 `origin/main@ca0977a`，独立分支 `codex/issue-217-output-limits`。本票承接 #174 真实调查 OUTPUT_TRUNCATED，不将产品修复混入 PR #214。

只区分请求输出需求：普通动作保留128 token，SUBMIT_CONCLUSION 使用独立1024 token额度，可配置范围512至2048。证据schema、引用校验、提示、模型、重试次数与循环总预算不变。1024是针对带证据结构的初始修复值，尚不能声称真实截断已消失。

回归复用既有 MockTransport 请求与合法证据响应，普通动作验证原128不变，结论含/不含知识查询均验证1024。旧实现运行结果为2 failed、17 passed：两项均明确报告128 != 1024。该断网测试只证明请求配置，不证明模型质量。

`issue217-output-red` 的清理函数对未构建镜像执行删除时遇到原生命令错误，提前退出。权威锁已空闲，但状态回读 RECOVERY_REQUIRED，仅发现本轮镜像 `customer-agent/agent-test:gate-issue217-output-red`。未自动删除残留或再次运行测试。临时聚焦脚本下一次应只删除本轮实际构建的镜像，且在嵌套finally中释放锁。

Standards / Spec 双轴静态审查均 PASS，未发现阻塞；不替代运行验证。临时聚焦脚本已准备只删除本轮实际构建镜像，并用嵌套finally保证执行锁释放，尚未运行该脚本。

修改已准备提交 Draft PR；修正后的绿测、格式/类型、真实复验与最终完整门禁均未运行，未合入、未关票。此次无DeepSeek调用。测试仍需等待 RECOVERY_REQUIRED 残留由协调处理，不绕过恢复状态。

## 2026-09-05 接续进展

上文保留9月4日停止时的历史状态。接续时已核实最新主线仍为 ca0977a，PR #218 的产品修复仍为35468f7，无需重做。

原残留精确镜像已确认没有容器引用并清理。`issue217-output-green` 修复后回归19 passed（0.94秒），本轮镜像清理完成。Ruff format/lint通过；Agent test目标在Pyright首次安装Node时卡于代理下载，尚未进入全量pytest。已停止本次专用buildx进程并从构建历史确认结束，不能将其记作测试失败或通过。

宿主显式本地代理可读取Node公开文件，但Clash仅监听127.0.0.1:7897，Docker Desktop的手动代理指向host.docker.internal:7897，容器经内置代理返回CONNECT EOF。修改Desktop代理并重启会影响正在运行的基线补偿执行器，正在等待用户确认。未改变全局代理、未重启引擎、未触发供应商调用。

产品差异与临时单场景runner的Standards/Spec静态复核通过。启动清理采用先确认独立project为空、再记录本轮创建所有权，覆盖部分启动失败。真实方案见[冻结记录](issue-217-live-freeze.md)。单场景真实验证、最终完整门禁均NOT_RUN；PR仍为Draft，Issue仍开放。本次未新增账本条目，历史12笔PENDING保留。
