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

## 2026-09-05 环境恢复与全量静态检查

用户已明确允许修正 Docker Desktop 代理并重启。已备份设置，仅将 HTTP/HTTPS 代理地址改为 http://127.0.0.1:7897。重启时出现 sailor-ingest.sock 启动错误，用户点击 Quit 后重新启动成功；引擎及原基线执行器恢复。未清理运行中的 socket 或业务数据。

容器代理小文件探测恢复，但 Pyright/nodeenv 的大文件下载仍不稳定。Agent Dockerfile 仅在 test 阶段复用前端固定的 node:24.19.0-bookworm-slim，复制 Node/npm，使 Pyright 使用现成工具。base/runtime、依赖版本与检查命令不变。该增量 Standards/Spec 均 PASS。

issue217-static-20260905e 完整 Agent test 目标通过：111 files already formatted，Ruff lint PASS，Pyright 0 errors/0 warnings，pytest 453 passed、3 skipped（34.17 秒）。本轮专用镜像已移除。此前中断构建仍记作未完成，不将其计入通过结果。下一步为冻结的单场景真实验证及最终完整门禁。

## 2026-09-05 单场景真实观察：未通过

冻结运行 issue217-live-20260905a 已执行一次，testedHead=d9d81da799673f840350a5d6c6e528666c236a13。服务内导入路径核验成功，输出额度确为128/1024。浏览器收到确认接口HTTP201，但 confirmed=false，因而停止；不能将建单确认UI记作通过。

原生检查点同时显示一代调查已启动：行动7次、业务判断1次、客户沟通2次，最终INVALID_MODEL_OUTPUT转人工，没有成功代次。已知5276 token；客户沟通用量缺失，usageTrusted=false。产品原有两次沟通纠正尝试包含在这一次运行中，不是额外复跑。结论额度修复已让本轮进入业务判断，但不能据此声称浏览器结论/回复验收通过，不能证明旧SCHEMA_MISMATCH与OUTPUT_TRUNCATED同源。

报告算式中的0.058809元仅包含已观测部分与受理保守估值，并不是本轮完整费用上界或平台实扣。整轮1元预留保持PENDING；历史十二笔保留，现共十三笔PENDING。原runner异常分支未更新phase，接续协调只将本轮RUNNING改为INCOMPLETE_PENDING_USAGE，未改变金额或attempt状态。没有重复付费运行。

本轮容器、卷、网络、八个精确镜像标签清理回读为空，TEST_GATE_FREE；原基线执行器仍运行。聚合证据见 issue-217-live-20260905a-result.json 与 issue-217-live-20260905a-failure.json；不保留原始模型正文、浏览器截图/trace或密钥。未转Ready、未运行最终完整门禁、未合入或关票。下一步只定位新出现的客户回复失败，不放宽解析或增加自动重试。

## 单次回复适配器诊断

issue217-reply-diagnostic-20260905a已按静态双轴PASS方案执行一次，前置无密钥离线请求检查通过。固定合成输入调用594ms：HTTP200，INVALID_OUTPUT，审计分类SCHEMA_MISMATCH、usageReported=false。sys.settrace仅记录到_read_streamed_response第418行的正文前缀策略拒绝；没有保存正文，因此尚不能判定具体触发哪项正文规则，也不能把该单独诊断等同于前轮每一次沟通失败的证明。

本轮0.1元预留完整保留；当前十四笔PENDING，用户核对点后累计预留2.1元，3.8元可用授权的保守未预留部分1.7元。镜像/容器已按本轮所有权清理，锁回读FREE。下一步用离线合法回复分片复现流处理路径，不追加付费抽样。
