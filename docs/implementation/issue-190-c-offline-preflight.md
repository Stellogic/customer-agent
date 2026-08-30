# Issue #190 C离线预检：通过与失败对照

2026-08-31；关联 [Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [Draft PR203](https://github.com/Stellogic/customer-agent/pull/203)。**本阶段OFFLINE_PREFLIGHT_PASS，不是C模型质量PASS或最终门禁。** 没有真实DeepSeek调用、72题回放、留出/原冻结评测、产品策略切换、合入或下游放行。

开始时fetch确认 `origin/main=c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`，分支已包含该main。此前审查源码 `ec158123` 到交接 `a4093028` 仅增14行文档。最终受测干净SHA **`b9c46a932267bf1264dfbe1ed81950dfc3e17d72`**，后续只归档文档/日志，不把归档提交冒称重新受测。

## 最终离线结果

RunId **`issue190-c-offline-20260831d`**，base为上述c19a7ebe。

| 检查 | 实际结果 | 耗时/范围 |
| --- | --- | --- |
| C离线契约 | 10 passed | pytest 0.84秒；合成MockTransport，不是真模型 |
| 格式 | 3个C文件无改动；全Agent 79文件already formatted | Ruff实际执行 |
| lint | All checks passed | 全Agent实际执行 |
| 类型 | 0 errors / 0 warnings | 全Agent Pyright，显式选择本地venv；17.1567514秒含启动 |
| 必要离线组件 | 29 passed | pytest 15.12秒；C10项＋既有DeepSeek离线契约19项 |
| 整阶段 | PASS，源码无未提交变化 | 41.0488482秒，含诊断与工具启动 |

组件只执行 `test_knowledge_sufficiency.py` 和 `test_deepseek_offline_contract.py`，后者使用本地127.0.0.1供应商桩。没有执行会加载原冻结评测数据的全Agent pytest，也没有Docker/浏览器/完整 `check.ps1`；故不冒称完整组件镜像或正式门禁通过。依赖复用已有本地venv，未安装、下载或生成依赖。

宿主Windows、CPython3.13.13（venv配置）；工具版本未单独打印，依赖锁可在受测SHA回读。没有新增模型API费用，4轮均0次/0元；模型质量样本数0。峰值内存、网络流量、机器/电力成本未采集。

## 保留的失败与最小修复

| RunId后缀 | 受测SHA | 结果 | 整阶段秒数 |
| --- | --- | --- | ---: |
| 20260831a | a4093028 | C10项通过，format/lint通过；types失败 | 9.4270146 |
| 20260831b | b9c46a93 | C10项及format/lint/types通过；组件28过/1失败 | 78.4681001 |
| 20260831c | b9c46a93 | 同上；显式certifi不能解决旧超时用例 | 54.5187248 |
| 20260831d | b9c46a93 | 所有本阶段检查通过，组件29过 | 41.0488482 |

a轮类型失败包含两个问题：新C代码对usage列表作逐项整数/非负检查后，Pyright仍保留None联合类型；另本地调用pyright没有指定已有venv，产生全仓依赖无法解析。修复 `b9c46a93` 只在既有校验后使用 `cast(int)` 收窄类型，并应用标准格式，不改变运行时数值/准入断言。预检命令添加 `--pythonpath <venv-python>`，不改依赖或产品配置。a轮format改变工作树已如实记录，不能把该轮所有工具说成在完全相同字节上执行。

b/c失败是既有 `test_offline_supplier_read_timeout_is_bounded_and_recorded_per_attempt`：模型整体deadline为1秒，而客户端初始化已耗尽预算，因此本地server看到0次请求，未达到断言2次。保留原失败，没有放宽10ms读超时、1秒整体deadline或2次请求断言。

诊断先排除“只指定证书就能解决”：c轮无网络初始化，默认条件1.184486秒、显式certifi仍1.042663秒，组件仍失败。随后静态检查发现HTTPX会为继承的HTTP/HTTPS/ALL代理初始化额外传输；d轮保持certifi一致，只将离线子进程 `NO_PROXY=*`，无网络初始化从1.228812秒降至0.271955秒，原测试和其余28项通过。**这是本次宿主环境的对照证据，不是生产性能收益。** 不修改机器全局代理，不关闭TLS校验，不修改默认产品HTTP客户端，也不把该环境选择自动用于未来真实DeepSeek访问。

## 冻结边界与审查

唯一prompt/schema/config的SHA仍分别为 `38d163c700dbdd5d39872864d781f573d06c05d23439f17044685dda201fd494`、`27ef4d19440b4279ac4b0426eb299e87445a455be5206716ad82c0da6f3733f4`、`11e970eca4aa7ee711af9602f14eea5a5c4ea28efe1e67c74f712843b9cbad45`。原数据/归档不改；本地BGE、RRF与产品 `PENDING_CALIBRATION` 不改。没有新prompt策略、A重拟合或B实现。

增量双CR比较 `a4093028...b9c46a93`：Standards PASS、Spec PASS，均0发现。两轴确认cast仅表达已检查类型，其他变动为格式，不改变usage、预算预留/结算或停止条件。后续预检环境诊断只存入证据，不是产品修复。

## 原始证据、资源和后续

[证据索引及原始/脱敏文件SHA](evidence/issue190-c-offline-20260831/index.json)保留a/b/c失败及d通过的phase、工具日志、JUnit XML；c/d另存实际诊断探针及预检脚本。只替换本机worktree绝对路径；没有路径变化的文件原字节保留。没有打印真实凭据，测试使用的是离线虚构凭据。

每轮都在仓库共享锁内执行，退出finally释放后各只读确认一次FREE，并即时成功通知协调LOCK_RELEASED；未轮询锁、未强制清理。d轮PASS后已明确归还阶段窗口，之后不再测试。测试只创建本机进程/临时文件，没有Compose资源或真实费用账本；临时pytest账本不是#190真实支出。

下一步仅待协调安排真实回放窗口与付费授权：沿用固定72题及唯一合同，串行逐请求预留/可信usage结算，累计≤6元；失败或预算不够即停，不承诺全部题完成。独立留出、#189和最终完整门禁仍需另行协调，不因本阶段PASS启动。

这些代码和记录由Codex按用户范围生成，用户确定范围/方法/预算；不可写成用户逐行手写、生产规模或模型质量达标。
