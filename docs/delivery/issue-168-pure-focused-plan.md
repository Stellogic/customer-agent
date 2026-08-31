# #168 纯逻辑离线聚焦验证记录

> 历史实测，仅覆盖下述 `0ec0fb7`。后续 [rag-layered-v2 静态增量](../eval/issue-168-layered-v2-contract.md) 未运行测试，不能沿用此处 11 项 PASS；原始日志与失败记录不变。

状态：**OFFLINE_FOCUSED_PASS，仅限本票两模块及 11 个既有纯逻辑测试。** 最初只获准静态准备；随后协调任务明确移交独占窗口，允许持锁最小环境准备、聚焦测试、必要预检与修复复验。最终受测代码 HEAD 为 `0ec0fb7f0e29a9bd5388651c02b3f375ec9a4653`。没有加载模型或进行真实检索/ONNX 质量评测，没有完整门禁或正式交付结论。

## 最小范围

| 现有测试文件 | 静态计数 | 能验证的内容 |
| --- | ---: | --- |
| `agent/tests/test_knowledge_ablation.py` | 6 个测试函数 | 报告初始状态、三路逐题编排及独立汇总、部分失败证据、查询标识检查、RRF-only 原样委派、PARTIAL/NOT_RUN/ERROR 标注 |
| `agent/tests/test_knowledge_consistency.py` | 5 个测试函数 | 小向量差异、排序逆序、版本/单边拒答差异、有限数检查、L2 归一化判断 |

静态选择 11 个既有测试，实际 pytest 收集并通过 11 个，0 失败、0 错误、0 跳过；没有新增测试。消融 6 个，一致性 5 个。

不选择 `test_knowledge_onnx.py`、`test_knowledge_resources.py`、真实 `knowledge_evaluation` 或任何冻结质量/模型契约执行器。此次不导出/加载 ONNX，不加载 BGE，不运行资源子进程，不调用 Spring、数据库或对话模型。

导入依据：`baseline_agent/__init__.py` 仅含文档字符串；`knowledge_consistency` 只有标准库；`knowledge_ablation` 的第三方评分器是显式运行入口内的延迟导入，而两个 RRF 测试在调用前用 monkeypatch 替换该导入。因此测试不执行 #190 的 `run_query/metrics`。消融测试会**只读本 worktree 的 #189 JSON** 来取得查询与阈值、计算内容哈希，不改写资产，不将查询发送给模型或检索系统；这不是冻结质量评测。若窗口连读取冻结题都不允许，删除命令中的消融测试文件参数，仅运行 5 个一致性测试。

## 环境选择与实际使用

- 静态准备时当前 worktree 无 `agent/.venv`。
- 不用 PATH 中的 MSYS Python 3.12，也不用 Codex 附带的 Python 3.12。
- 基础解释器：`C:\Users\lizhuo\AppData\Local\Programs\Python\Python313\python.exe`，CPython `3.13.13`。
- 静态准备发现全局 pytest 为 `9.1.1`，因此获批后没有拿它替代仓库版本：用基础解释器在本票 `.local/issue168-pure-venv` 新建隔离环境，仅安装仓库已声明的 pytest `8.4.2`、ruff `0.16.2`、pyright `1.1.411` 及其轻量传递依赖。没有修改共享环境、`pyproject.toml` 或 `uv.lock`，没有安装模型框架。
- 这两份测试仅需标准库和 pytest；使用 pytest 自带的 `tmp_path/monkeypatch`，不需 pytest-asyncio、torch、transformers、onnx、numpy 或项目的网络/Agent 依赖。
- 依赖准备通过基础 Python 的 `venv --without-pip` 和 `pip --isolated --python <本票python> install --no-cache-dir --index-url https://pypi.org/simple pytest==8.4.2 ruff==0.16.2 pyright==1.1.411` 完成。只下载开发工具 wheel；后续测试离线运行，pyright 复用已有 Node。该最小环境不是完整 `uv.lock` 环境，不能替代完整门禁。

## 复验命令与执行边界

以下是本次聚焦命令的可读复现形式。实际执行使用本票 `.local/issue168-pure-window.ps1` 包裹现有 `Enter-TestGateLock -Issue 168` / `Exit-TestGateLock`，每轮进入一次、不轮询，finally 归还。命令不是新的正式门禁入口；未来再次执行仍需协调窗口，日志只写本票 `.local`。

```powershell
$issue168Root = 'C:\Users\lizhuo\.codex\worktrees\7d39\customer-agent'
$issue168Python = Join-Path $issue168Root '.local/issue168-pure-venv/Scripts/python.exe'
$issue168Out = Join-Path $issue168Root ('.local/issue168-pure-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $issue168Out | Out-Null
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:PYTEST_ADDOPTS = ''
$env:PYTEST_PLUGINS = ''
& $issue168Python -I -B -m pytest -q `
    -c "$issue168Root/agent/pyproject.toml" `
    --noconftest -p no:cacheprovider `
    "--basetemp=$issue168Out/tmp" `
    "--junitxml=$issue168Out/results.xml" `
    "$issue168Root/agent/tests/test_knowledge_ablation.py" `
    "$issue168Root/agent/tests/test_knowledge_consistency.py" `
    *> "$issue168Out/pytest.log"
$issue168ExitCode = $LASTEXITCODE
Get-Content -LiteralPath "$issue168Out/pytest.log"
Write-Output "ISSUE168_PURE_EXIT_CODE=$issue168ExitCode"
```

`-I` 排除用户 site 和环境 PYTHONPATH；pytest 仍按显式指定的本票 `pyproject.toml` 中 `pythonpath = ["src"]` 导入本票源码。`-B` 不写 pyc；关闭第三方插件自动加载、环境注入和 conftest 收集，避免扩大到其他测试/服务。关闭 pytest 缓存，临时文件、JUnit 和日志只写新建的本票运行目录。不调用 uv/pip/Docker/Compose，不触及 #190 源码、虚拟环境或依赖清单。

协调执行入口必须检查并传播 `$issue168ExitCode`，非零不得报告 PASS；这里不使用 `exit`，以免跳过外层锁释放与记录。目录名须保持本次独有，已有目录时不要重用 pytest 的 `--basetemp`。

## 结果解释与保留前置

| 运行 | 测试 | 格式/lint/type | 整轮状态 |
| --- | --- | --- | --- |
| `issue168-pure-20260831a` | 11 passed in 0.31s | 格式化 4 文件；lint 13 条中文标点规则；类型 5 条 Optional 下标诊断 | FAIL，保留失败证据 |
| `issue168-pure-20260831b` | 11 passed in 0.31s，JUnit 0 failures/errors/skipped | 4 files already formatted；ruff All checks passed；pyright 0 errors / 0 warnings | PASS，受测代码 `0ec0fb7` |

修复没有增加防御性判断：将循环内的 `mode_report` 标注为非空字典，仍由 `active` 引用同一对象供异常记录使用；其余为 ruff 排版与注释/文档字符串标点。测试断言、指标计算及 PARTIAL/NOT_RUN/ERROR 契约不变。两个独立代理对 `527a3b9...0ec0fb7` 分别给出 Standards PASS / Spec PASS，均 0 项发现。

首轮包含未提交的格式化变化；最终复验在已提交 `0ec0fb7` 上以 format --check 执行，未修改受测文件。phase 中 `base_sha=c19a7eb...` 仅是当时本地 origin/main 引用，不表示本分支已同步/合入该 main，也不作为完整门禁新鲜度证据。JUnit suite time 与 pytest 终端 wall time 统计范围不同，保留原值不混算。

证据：[`首轮 phase`](evidence/issue168-pure-20260831a/phase.json)、[`首轮失败 lint`](evidence/issue168-pure-20260831a/lint.log)、[`首轮失败 types`](evidence/issue168-pure-20260831a/types.log)、[`复验 phase`](evidence/issue168-pure-20260831b/phase.json)、[`复验 JUnit`](evidence/issue168-pure-20260831b/results.xml)、[`复验 pytest`](evidence/issue168-pure-20260831b/focused.log)。每目录另存环境、格式、lint、类型原始日志。

两轮均已实际释放锁。b 轮 `LOCK_RELEASED` 已送达协调任务；a 轮首发遇到协调压缩错误，保留原回报并通过可让出控制的等待，五分钟后仅补发一次，补发已确认成功。等待期间未持锁，没有把首发失败当送达。

通过只意味着编排/状态/纯数值逻辑在该环境通过，**不意味着真实中文检索、PyTorch 基线、ONNX 数值/排序/资源质量 PASS**；mock 输出只是测试输入，不能进入模型评测证据。真实检索/ONNX 集成仍等待 #190 正式交付及公共接缝；没有运行 ONNX/资源测试、模型下载/加载/推理、真实检索、付费模型、Docker/Compose、构建、完整门禁或 CI，没有合并关票。
