# #190 reranker 离线验证

2026-08-31；[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [PR203](https://github.com/Stellogic/customer-agent/pull/203)。**离线工程 PASS，不是模型、独立质量或交付 PASS。** 固定源码 `04d7ee9c7129e00741db22f04ccc72492253738e`，同步 base `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。本轮未修改模型清单、分数、唯一界限选择、开发数据、原 RRF 顺序或产品默认策略。

| RunId | 结果 | 范围/耗时 |
| --- | --- | --- |
| `issue190-reranker-offline-20260831a` | 工程 FAIL | `5582f83`；聚焦4/4通过，lint报10处中文注释标点；3.42秒。后续阶段未运行，不是模型失败 |
| `issue190-reranker-offline-20260831b` | 离线 PASS | 同一HEAD带标点/格式修改；聚焦4/4、相关组件32/32、类型0错误，lint/格式通过；47.92秒。不是最终干净HEAD证据 |
| `issue190-reranker-offline-20260831c` | 离线 PASS | 最终`04d7ee9`、工作树无改动；聚焦4/4、相关组件32/32、类型0错误，lint/格式通过；26.18秒 |
| `issue190-reranker-entry-20260831a` | 入口 PASS | 同一最终HEAD；真实PowerShell→uv→Python及有效锁，传入含空格且不存在的模型路径；4.83秒 |

入口为本轮必要工程修正：增加只读 `preflight` 模式，检查原固定开发源hash/72题数量、记录参数，状态仅 `PREFLIGHT_ONLY`、`completed_queries=0`、`metrics=null`。不调用prepare、构造模型或评分，也不占用共享development阶段记录。模型目录仍不存在。未读取留出或189题目；72只作源契约核对，不计算质量。

格式/lint覆盖两份reranker源码及其测试；类型检查覆盖现有agent配置范围。32项相关组件来自reranker、既有answerability纯逻辑和sufficiency离线契约。人工分数/Mock只用于工程测试，不代表模型质量、权限重测或线上收益。未修改依赖、锁脚本、DB迁移或业务接口。

Standards / Spec 增量静态审查均 PASS @`04d7ee9`，0项未解决发现。每次进程结束释放自身锁后只读确认一次，四次均为当时FREE，均已通知协调；最终入口结束主动归还窗口，不持锁等待归档。全部失败/通过记录保留于[证据目录](evidence/issue190-reranker-offline-20260831/index.json)。日志仅将工作树绝对路径替换为`<WORKTREE>`，保留源文件和归档文件双hash。附带的聚焦启动脚本是b/c版本，a版本未单独保存，其实际阶段顺序以a原始phase/log为证。原始文件仍在本地对应RunId目录，未改写。

环境：Windows 11 build 26200、Python3.13.13、torch2.10.0+cpu、transformers4.57.6、safetensors0.7.0（读取包版本，不加载模型）。未准备新依赖，模型下载/加载/开发评分/独立验证/189/完整门禁均NOT_RUN；真实API调用0，新增付费0，未读取或修改共享活账本，历史预算不重置。内存/CPU资源峰值未采集。

后续需协调授权，再按[固定方案](issue-190-reranker-static.md)分别执行：

```powershell
$uvPath = (Resolve-Path ./.local/tools/uv/uv.exe).Path
pwsh ./scripts/knowledge-reranker.ps1 -Phase prepare -RunId <授权RunId> -Uv $uvPath
pwsh ./scripts/knowledge-reranker.ps1 -Phase development -RunId <授权RunId> -Uv $uvPath
```

实际机器若uv不在PATH，`-Uv`须给绝对路径（入口运行时会切换到agent目录）；本轮通过时使用已有工具绝对路径。模型未运行意味着尚无可行参数；离线PASS不解阻#190或下游。代码与证据由Codex生成/整理，不代表用户逐行手写或生产贡献。
