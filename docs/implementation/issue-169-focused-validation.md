# #169 独立模块聚焦验证记录

> 历史验证范围：本记录对应提交 `575d10a2b7fa39b94d55e19890d6c6f251d593a1` 的独立模块。后续 [rag-layered-v2 静态修订](issue-169-rag-layered-v2.md)未运行测试或检查，不能继承本记录作为新解析语义的通过证明。

## 状态与范围

2026-08-31，在用户明确同意解除本票聚焦验证禁令、协调重新分配独占窗口后执行。
基线 main：`c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`；起始 HEAD：`44a473f8d92ff9a2aab83787044eb43effe4a173`。
本轮仅调整六个既有独立源码/测试文件的格式、Python 注释和一处测试写法，没有改变产品逻辑、DTO 或公共协议。

**FOCUSED_VALIDATED：前端 7 项、Java 6 项、Python 28 项，共 41 项通过。**
这替代此前三个独立模块的“所有运行验证 NOT_RUN”状态，但不是完整门禁通过或 Issue 完成交付。
HTTP、检索适配与回复编排、真实授权、内容安全和事实冲突处理仍未接线；#190 原有集成阻塞持续有效。

## 持锁执行与修复

全部执行使用仓库 `Enter-TestGateLock` / `Exit-TestGateLock`，同一宿主进程持锁且在 finally 释放。
没有修改锁脚本、锁身份、依赖清单或公共验证入口。早期权限拒绝发生在创建进程前，不算测试失败或已取得锁；取得明确同意后经正常审批启动。

| Run ID | 实际结果 |
| --- | --- |
| `issue169-20260831-focus1` | 前端格式化完成；限定 tsconfig 漏包含既有 `src/vite-env.d.ts`，类型检查因 CSS 声明缺失失败。未启动测试。只修复忽略目录的验证配置。 |
| `issue169-20260831-focus2` | 前端格式、限定类型、ESLint、7 项组件测试通过；Python 格式化完成后 lint 发现中文注释标点与常量 setattr 写法问题，尚未运行 Python 类型/测试。 |
| `issue169-20260831-focus3-java` | Google Java Format 1.35.0 AOSP 格式化及格式复查通过；JDK 25.0.2 编译独立源码通过；JUnit 6 项通过。 |
| `issue169-20260831-focus4-python` | 修复后两个文件格式无变化、Ruff lint PASS、Pyright 0 errors / 0 warnings、pytest 28 项通过。 |

Python 修复保留中文说明，改写会触发 RUF002/RUF003 的标点。冻结 DTO 的负向测试由常量 `setattr` 改为直接赋值，并在该行以 `pyright: ignore[reportAttributeAccessIssue]` 标明故意违反只读属性；仍以 `FrozenInstanceError` 断言运行时拒绝修改，没有放宽实现或关闭全局规则。

最终日志为 `LOCK_RELEASED issue=169 runId=issue169-20260831-focus4-python result=PASS`、`TEST_GATE_FREE`。
已成功通知协调任务并归还窗口，不占锁等待静态审查或文档收尾。

## 验证环境与命令

前端使用 Node **24.19.0**、TypeScript **6.0.3**、Vitest **4.1.0** 和仓库 ESLint 配置。依赖从离线缓存以 `ignore-scripts` 安装；首次 npm.cmd 安装器实际使用 Node 22.15.0 并报告引擎警告。后续格式、类型、lint、Vitest 均由已确认的 Node 24.19.0 直接执行，未运行安装脚本；没有把安装阶段计为匹配 Node 版本的验证。

从 frontend 目录执行：

```text
node node_modules/prettier/bin/prettier.cjs --write src/components/CustomerKnowledgeSources.tsx src/components/CustomerKnowledgeSources.test.tsx src/components/CustomerKnowledgeSources.css
node node_modules/typescript/bin/tsc --project ../.local/issue169-tsconfig.json
node node_modules/eslint/bin/eslint.js src/components/CustomerKnowledgeSources.tsx src/components/CustomerKnowledgeSources.test.tsx
node node_modules/vitest/vitest.mjs run src/components/CustomerKnowledgeSources.test.tsx --maxWorkers=1
```

限定 tsconfig 继承仓库配置，只包含组件、组件测试、test-setup.ts 和 vite-env.d.ts。Vitest 使用仓库原配置；7 项通过，耗时 136.28 秒，其中模块导入 110.17 秒、测试执行 290 毫秒。没有运行整个前端类型检查或浏览器验收。

Java 复用本地 `gradle:9.3.1-jdk25` 镜像，仅作为 JDK 容器使用；没有运行 Gradle 或镜像构建。容器 `--network none --rm`，只挂载本 worktree；退出后按本次精确名称确认并清理自有容器，无业务服务或新建卷/网络。
JUnit console standalone **6.0.3** 与 AssertJ **3.27.7** 从 Maven Central 取得，版本对应仓库 gradle.lockfile；复用已有 Google Java Format **1.35.0**。
编译只包含 `KnowledgeCatalogModels.java`、`KnowledgeCitationProjection.java`、`KnowledgeCitationProjectionTest.java`，使用 `javac --release 25 -encoding UTF-8`。
JUnit console 以 `--select-class com.stellogic.customeragent.knowledge.KnowledgeCitationProjectionTest --fail-if-no-tests` 执行，6 项成功、0 skipped、0 failed，耗时 603 毫秒。未验证整个后端编译、Checkstyle、Spring、数据库或 Gradle 生命周期。

Python **3.13.13** 复用既有离线环境，PYTHONPATH 明确指向本 worktree 的 agent/src；从本 worktree agent 目录执行：

```text
ruff format src/baseline_agent/knowledge_retrieval.py tests/test_knowledge_retrieval.py
ruff check src/baseline_agent/knowledge_retrieval.py tests/test_knowledge_retrieval.py
pyright --pythonpath <既有Python3.13解释器> src/baseline_agent/knowledge_retrieval.py tests/test_knowledge_retrieval.py
python -m pytest -q tests/test_knowledge_retrieval.py
```

28 项通过、耗时 0.10 秒；所有输入均为测试中的合成 JSON，不发 HTTP 请求，不调用模型或检索引擎。
本地原始证据保留于忽略目录 `.local/issue169-focus1.log`、`issue169-focus2.log`、`issue169-focus3-java.log`、`issue169-focus4-python.log` 与 `.local/java169/reports`。执行入口为 `.local/issue169-focused.ps1`、`issue169-java.ps1`、`issue169-java.sh`，不作为新的公共验证框架。

## 未执行与真实贡献

**NOT_RUN**：真实 #190 检索/质量评测、模型请求、HTTP/公共入口集成、业务全栈、全项目格式/lint/类型检查、Gradle check、完整后端构建、浏览器验收、`scripts/check.ps1`。CI 未触发，Draft PR 未转 Ready，未合入、未关票。
贡献为既有独立模块的聚焦执行证据及普通工程修复，不是检索引擎实现、真实回复安全证明或产品接入完成。

## 增量静态双审查

固定比较 `git diff --cached 44a473f8d92ff9a2aab83787044eb43effe4a173`，审查九文件 226 新增／87 删除；两个独立审查者只读核对差异和上述四份运行日志。
Standards **PASS，0 项发现**；Spec **PASS，0 项发现**。本段仅补记结论，未改变已测试或已审查的实现。
