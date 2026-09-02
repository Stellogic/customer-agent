# #190 分层检索实现与验证记录

2026-09-01；[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [PR #203](https://github.com/Stellogic/customer-agent/pull/203)。正式采用 [rag-layered-v2](../eval/rag-layered-v2.md)，当前实现职责与下游接缝见 [接口说明](issue-190-layered-interface.md)。用户确认的规格与 9 张票同步证据见 [变更快照](evidence/issue190-rag-layering-20260831/index.json)。#166 原职责未变、#189 原交付及冻结资产保留，两票没有重开。

## 当前可证实的结果

RunId `issue190-layered-runtime-20260831c`；干净受测 HEAD `359c3eda59c66ea46beb6b6e8cfc2513b4725bea`，base `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。三端规范组件、真实 Spring/PostgreSQL 检索及 5 项浏览器聚焦 PASS；这不是最终完整门禁。阶段 419.4299 秒，检索评测 69.1864 秒，浏览器 10.2 秒。

| 检索层指标 | 实测 | 正式门槛 |
| --- | ---: | ---: |
| 完成数 | 64/64，失败/未运行各 0 | 完整集合 |
| Recall@5 | 0.9444444444 | ≥0.90 |
| MRR@5 | 0.8680555556 | ≥0.75 |
| 错版本/越范围/未授权 Top5 命中率 | 各 0 | 各 0 |

Recall/MRR 按协议在有答案子集统计，不把 64 题全部当有答案。原集合内容 SHA256 `d2d5efdae565395c1dc722e14f66077558575152e23c5c8fbea58b7ebcfd2fe5`，未改题、标签或编码协议。固定 BGE revision `7999e1d3359715c523056ef9478215996d62a620`；编码确定性、归一化、指令及截断契约 PASS。环境：Docker/WSL2、Python 3.13.14、torch 2.10.0+cpu、transformers 4.57.6、safetensors 0.7.0、PostgreSQL 18.6、pgvector 0.8.6。

本轮 `answer_quality=NOT_EVALUATED`，不把格式、引用真实性与语义充分性混为一个成绩。旧拒答指标和旧 FAIL 仍有效；新职责划分不构成旧方法变好或旧成绩重算。没有读取独立封存留出，没有根据本轮逐题结果调参。回答层由 #169/#170 在同一次实际回答调用中另行验收。

Agent 全量离线测试 308/308；前端 164 通过、3 个既有跳过（非本票新增），格式/类型检查通过。后端 Gradle check 在此前 runtime-a 已执行通过，runtime-c 复用相同源构建缓存；不是再次运行所有后端用例。8 个目标均由规范镜像构建入口检查；报告的 `Reused=false` 指未复用同 RunId 镜像，不代表 Docker 构建层没有缓存。浏览器覆盖桌面/窄屏、真实撤权、索引失效、排名前排除 25 条高分草稿及退役版本、无答案问题仍可返回合法候选；loading/empty/模型错误的 UI 路由夹具不冒充真实模型行为。

## 工程试错与修复，不删除失败

| RunId 后缀（均前缀 issue190-layered-） | 结果与实际范围 | 秒 |
| --- | --- | ---: |
| preflight-20260831a | 聚焦 2 项、格式/类型 PASS；格式器改变工作树，不能称干净最终 SHA | 25.6422 |
| runtime-20260831a | 后端 PASS；Agent 历史 c6 文件格式检查失败，未进入检索/浏览器 | 146.3300 |
| preflight-20260831b | 聚焦 3 项 PASS；格式后 7 项注释标点 lint 失败 | 7.3426 |
| preflight-20260831c | 聚焦 3 项、离线相关 46 项及格式/类型 PASS；仍为提交前脏树 | 34.5145 |
| runtime-20260831b | Agent 280 通过/28 失败；Docker 缺少历史证据夹具，非模型质量失败 | 94.0518 |
| runtime-20260831c | 三端组件、完整检索集合与 5 项真实浏览器 PASS | 419.4299 |

修复范围：`34392b7` 增加评测异常的题 ID、HTTP 状态、安全错误码及完成/失败/未运行计数，保持失败时 metrics=null、不重试；历史 c6 文件只修格式及注释，不改 prompt/schema/账本。`359c3ed` 将 7 个旧证据文件按原始字节复制到测试夹具，附来源与 SHA256，仅 Docker test stage 打包；runtime 不包含 tests。新增 dockerignore 排除本机缓存，防止 Windows 编译缓存进入 Linux 镜像。没有以跳过失败、伪模型或新标签消除问题。

runtime-a/b 的临时启动器清理受 PowerShell native strict 模式影响，phase 保留 cleanup_error；a 的自有遗留标签已在后续持锁预检清除。runtime-c 修复本地启动器的清理方式并验证本次容器/卷/网络/镜像全为空。没有修改共享锁脚本、强制释放或清理其他任务资源。每次结束均释放自身锁，只读一次观察当时 FREE 并通知协调；该观察不抹去历史 cleanup_error。

## 证据、审查与贡献边界

- [preflight-a](evidence/issue190-layered-preflight-20260831a/index.json)、[preflight-b](evidence/issue190-layered-preflight-20260831b/index.json)、[preflight-c](evidence/issue190-layered-preflight-20260831c/index.json)
- [runtime-a](evidence/issue190-layered-runtime-20260831a/index.json)、[runtime-b](evidence/issue190-layered-runtime-20260831b/index.json)、[runtime-c 完整输出与原始 64 题报告](evidence/issue190-layered-runtime-20260831c/index.json)
- Standards / Spec 对产品差异及 `359c3ed` 增量均 PASS，0 未解决发现；Spec 曾发现异常报告缺少题级定位，已由 `34392b7` 修复复核。双轴静态 PASS 不代替运行门禁。
- 本文及六份阶段归档再次获得 Standards PASS / Spec PASS（各 0 阻塞）；Standards 核对 35 个归档文件哈希，Spec 仅看汇总/phase/控制台，不读取冻结逐题内容。新增旧 PR 快照只是原样证据，不改变受测源码。
- [PR 旧正文/审查状态原样快照](evidence/issue190-rag-layering-20260831/pr203-before-final.json)，SHA256 `bdcb94b142e85a3ccd1d65fda3cbc0ec7cbb529b272a43b19b5a46bbc23de99e`；更新 PR 的当前结论时不丢弃原阶段叙述。

归档只替换工作树/用户目录/宿主名前缀，逐文件记录原始与归档哈希。runtime-a/b 的原生 Docker 完整控制台未落盘，保留已有 transcript/phase，不能补造；runtime-c 增加外层 Tee 保存完整控制台。浏览器截图写入容器默认 test-results，而启动器复制的是空 artifacts，截图未保留；5 项通过有控制台证据，不声称已归档截图。最终完整门禁待运行，结果以最终受测 HEAD 的正式门禁记录及 PR 回读为准。

本阶段真实付费调用 0、新增 API 费用 0；未修改/重置已有共享预算账本。机器峰值内存、CPU、电费未采集。这里只是本地学习项目与合成评测，不是生产吞吐、客户收益或线上改进。用户作出产品和职责决策，Codex 生成与修改代码、运行验证及整理证据；不能表述为用户逐行手写所有实现。旧试错代码、合同、失败和账本保留，可据实讨论方案局限、部署接缝错误及为何最终选择最小分层方案。
