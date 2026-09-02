# #169 runtime-f 隔离清理事故

2026-09-01，运行 `issue169-runtime-20260901f` 时，执行器新增的 Python 静态预检被错误地放在设置 `COMPOSE_PROJECT_NAME` 之前。预检因从仓库根目录检查导致的导入分类差异失败；finally 无条件执行 `docker compose down --volumes --remove-orphans`，使用了默认 `customer-agent-baseline`。

原始 `cleanup.log` 证明 baseline 的容器、网络及 `customer-agent-baseline_postgres-data` 卷被删除。卷内运行数据可能丢失，未验证存在可恢复备份。原 `phase.json` 的 cleanup=PASS 仅检查未启动的本票项目为空，是错误的成功标记；原文件在 `phase.json` 和 `phase.original.json` 保持原样；追加 `phase.corrected.json` 显式标注隔离事故。不能把该运行记为资源清理PASS。

这是执行器编排错误，不是产品测试失败。已立即停止后续所有测试/构建/Compose/模型，通知协调任务处理baseline影响与恢复；没有擅自重建或宣称数据已恢复。实际模型调用0，未改变费用账本，锁已释放。

执行器修复候选：在任意可能失败的步骤之前指定本票项目；每条Compose命令显式传递固定`-p`；只有启动过本票服务才执行本票Compose清理；预检返回agent目录以遵守同一配置语义。恢复运行前还需静态复核和协调处理，当前修复未经运行验证。

## 精确触发与暂停

触发命令：`pwsh -File .local/issue169-runtime.ps1 -RunId issue169-runtime-20260901f -Browser`。

工作目录：`C:\Users\lizhuo\.codex\worktrees\c0f3\customer-agent`。源码HEAD `915fb683ae7abc0ddabdd40f7297fc35d1f4afb7`，基线 `e34b60113a3bbcfe28a4fcd247900127ffbd234a`，包含未提交改动。执行器是未提交的 `.local/issue169-runtime.ps1`；事故时脚本没有独立冻结SHA，不能把HEAD当成该脚本版本。失败的预检从仓库根目录执行 `ruff.exe check --config agent/pyproject.toml agent/tests/issue169_customer_knowledge_acceptance.py agent/tests/issue169_customer_answer_run.py`，退出1；随后finally执行了未带-p的`docker compose down --volumes --remove-orphans`。

协调已独立确认baseline容器/网络/卷不存在，并明确暂停连续窗口。仅允许静态最小执行器修复、独立CR和准确证据保存；禁止Docker写入、重建、prune、镜像清理及模型调用。当前没有已知且已核验的baseline数据卷备份线索；未扫描密钥、未做任何恢复写入。修复脚本副本仅为静态审查产物，不是允许执行的恢复脚本。

## 静态修复审查结果

独立 Standards / Spec 最终均静态PASS。首轮除原项目隔离错误外发现两项P1：清理失败可保留总体PASS并删去恢复记录；证据/清理异常可跳过最终报告与锁处理。修复候选要求专用pwsh自行持锁，每条Compose显式指定本票项目，未启动不执行Compose清理，证据与清理分离捕获；清理失败标FAIL、保留既有owner记录并退出77，由进程退出释放互斥量，后续仍由原门禁残留识别机制判定是否需要恢复。只有清理确认成功才调用正常Exit并打印LOCK_RELEASED。

静态复核的脚本副本 `runner-fix.ps1` SHA-256：`371557CBD74E44353117CC498E9FAD4FCF77B9CE5A56AD75B1AA9904744CBA84`。此SHA只标识修复候选，不标识事故发生时脚本。修复未执行、未运行语法/格式/类型/测试或Docker；双CR不是恢复放行。协调暂停持续有效。
