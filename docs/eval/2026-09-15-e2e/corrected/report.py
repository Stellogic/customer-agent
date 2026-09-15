import csv
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path('D:/customer-agent')
OUT=ROOT/'docs/eval/2026-09-15-e2e'
CORRECTED=OUT/'corrected'
LOCAL=ROOT/'.local/eval-20260915-corrected'
RAW=ROOT/'.local/gate-evidence/issue230-real-eval-20260915-corrected'
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
data=read(CORRECTED/'data.json')
initial=read(OUT/'data.json')
cases=data['cases']
calls=data['attempts']
metric=data['metrics']
total_calls=len(calls)+len(initial['attempts'])
total_tokens=data['ledgerTotals']['knownTokens']+initial['ledgerTotals']['knownTokens']
total_cost=data['ledgerTotals']['knownEstimatedCostMicros']+initial['ledgerTotals']['knownEstimatedCostMicros']
stamp=datetime.fromisoformat(data['browserStats']['startTime'].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8)))
def seconds(n): return '未观测' if n is None else f'{n/1000:.3f}'
table='\n'.join(f"| {c['id']} | {c['evidence'].get('scenario',{}).get('title','')} | {c['status']} | {seconds(c['durationMs'])} | {seconds(c['timing']['confirmationToTerminalMs'])} | {c['usage']['attempts']} | {c['usage']['knownTokens']} | {c['usage']['knownEstimatedCostMicros']/1e6:.6f} |" for c in cases)
role_table=[]
for role,label in [('intake','受理'),('action','行动选择'),('judgment','业务判断'),('communication','客户回复')]:
    selected=[a for a in calls if a['role']==role]
    timing=data['roleLatency'][role]
    role_table.append(f"| {label} | {len(selected)} | {sum(a.get('inputTokens') or 0 for a in selected)} | {sum(a.get('outputTokens') or 0 for a in selected)} | {seconds(timing.get('meanMs'))} | {seconds(timing.get('p50Ms'))} | {sum(a.get('estimatedCostMicros') or 0 for a in selected)/1e6:.6f} |")
timing_table='\n'.join(f"| {label} | {data['timings'][key]['n']} | {seconds(data['timings'][key].get('meanMs'))} | {seconds(data['timings'][key].get('p50Ms'))} | {seconds(data['timings'][key].get('p90Ms'))} |" for key,label in [('intakeClickToResponseMs','受理点击→首次受理响应'),('confirmationToTicketsMs','确认点击→建票响应'),('confirmationToTerminalMs','确认点击→所有调查终态'),('confirmationToReplyUiMs','确认点击→首个正文UI状态'),('intakeClickToTerminalMs','受理点击→所有调查终态')])
ticket_count=sum(len(c['evidence'].get('business',{}).get('tickets') or []) for c in cases)
proposal_count=sum(len(c['evidence'].get('business',{}).get('proposals') or []) for c in cases)
execution_count=sum(c['evidence'].get('business',{}).get('executions',0) for c in cases)
text=f'''# 新一组真实端到端评测报告（2026-09-15）

## 结论

经用户确认纠正评测设计后，**修正版原始结果：{data['counts']['PASS']} PASS / {data['counts']['FAIL']} FAIL / {data['counts']['NOT_RUN']} NOT_RUN，计划8例**。这是单轮修正版结果，首轮记录完整保留，没有跨轮挑选成功样本。

- 修正版：{len(calls)} 次真实 DeepSeek Pro 请求、{data['ledgerTotals']['knownTokens']} token，程序估算 **{data['ledgerTotals']['knownEstimatedCostMicros']/1e6:.6f} 元**。
- 两轮合计：**{total_calls} 次请求、{total_tokens} token、估算 {total_cost/1e6:.6f} 元**，在用户授权1.5元和80次请求范围内。实际供应商扣费未知。
- 修正版实际创建{ticket_count}张工单、{proposal_count}份待审批提案，补偿执行记录{execution_count}。本轮不批准或执行补偿。
- 本地评测结论不等同于生产准确率、模型通用能力或正式PR交付。产品源码保持同一提交，没有用修代码或放松业务资格使样本通过。

## 两轮结果为什么分开

首轮为3 PASS / 5 FAIL / 0 NOT_RUN，22次请求、25819 token、估算0.278793元。其中两例假设秒数与向下取整的小时可并存，违反现有Graph整小时合同；两例使用错误的审计事件断言；一例“没收到”的输入按现有提示优先分类为包裹未收到，违反的是初稿预期。首轮另有独立计量汇总的挂载配置错误，完整模块未运行，但持久账本与逐例业务附件已保留。

这些是本次评测设计/采集问题，**不能算作5次模型失败**。已向用户说明，并获准在原预算内执行纠正轮。详细原始解释见[首轮设计问题与原始结果](首轮设计问题与原始结果.md)。

修正版改用23/73整小时、同代次结论命令的`accepted=true`、明确的物流延迟措辞，并修正采集服务挂载；24/72小时金额、退款事实、人工权限和零执行断言保持。输入有变化，因此不把两轮差异描述为模型质量提升。

## 范围、版本与冻结配置

| 项目 | 实际配置 |
| --- | --- |
| 产品提交 | `{data['result']['head']}`，本地分支 codex/payment-terminal-closure-fix |
| Run ID | `{data['runId']}` |
| 真实链路 | Chromium → React HTTPS页面 → Spring业务接口/SSE → PostgreSQL / LangGraph → 外部DeepSeek |
| 模型 | 受理、行动、业务判断、客户回复均为deepseek-v4-pro；实际请求/响应模型逐次记录 |
| 模型/提示合同 | [plan.json](corrected/plan.json)中的providerVersions、effectiveInvestigationLimits |
| 运行方式 | 8例各一次，单worker，案例retries=0；普通失败继续，未知usage/预算/期限停止后续 |
| 本轮限额 | 1元、58次请求、130000 token、账本创建后45分钟；首轮限额与账本保持原样 |
| 行动循环 | 30000ms，其他预算见冻结plan；不是全链路SLA |
| 开始时间 | 北京时间{stamp.strftime('%Y-%m-%d %H:%M:%S')} |
| 浏览器批次用时 | {data['browserStats']['duration']/1000:.3f}秒，含用例开销，不含构建与清理 |

只通过SQL准备合成订单，未预写工单、回复、调查结果或提案。业务动作从真实页面触发。脚本读取数据库用作断言与证据采集，不模拟产品响应。

## 逐例结果与费用

| ID | 场景 | 结果 | 整例秒 | 确认至终态秒 | 请求数 | token | 估算元 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
{table}

通过条件：正常解释/提案场景须COMPLETED且结论实际接受；取消/已有补偿须合法人工终点且无提案；支付须正确读取支付/退款事实、业务回复后交人工；拆票须两票分别满足合同、刷新可见、客服能领取/看事实/释放。全部场景执行数为0。合法人工终点单独记录，不等同无人接管。

## 真实浏览器阶段耗时

| 指标 | n | 平均秒 | P50秒 | P90秒 |
| --- | ---: | ---: | ---: | ---: |
{timing_table}

- 计时来自浏览器测试进程及页面的真实时钟，确认至终态包含接口、Agent、网络、轮询观测开销；合法人工终点也计入，不能作为“自动回答速度”。
- 首个正文UI通过MutationObserver观察`.conversation .reply-sources`第一次可见；这是React正文状态出现的近似时点，**不是供应商TTFT**。未产生业务正文或未观察到记null，不当作0秒。
- P50用中位数，P90用nearest-rank；本批样本很少，P90可能等于最大值。未测并发吞吐、生产P95或逐token速度。
- Compose沿用固定业务时钟`2026-08-09T14:00:00Z`，所以业务审计/消息时间可能与9月15日真实运行日期不同；不使用这些固定业务时间计算延迟。

## 模型调用与计量完整性

| 角色 | 请求数 | 输入token | 输出token | 平均调用秒 | P50秒 | 估算元 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(role_table)}

- 持久账本：{data['ledgerTotals']['statuses']['SETTLED']} SETTLED、{data['ledgerTotals']['statuses']['PENDING']} PENDING、{data['ledgerTotals']['statuses']['IN_FLIGHT']} IN_FLIGHT；未知usage {data['ledgerTotals']['unknownUsage']}。
- 独立采集：`metricsCollected={str(data['result']['metricsCollected']).lower()}`；providerAttempts={metric.get('providerAttempts')}，knownProviderAttempts={metric.get('knownProviderAttempts')}，logicalCalls={metric.get('logicalCalls')}，missingEvidenceSources={metric.get('missingEvidenceSources')}，unattributedAttemptIds={len(metric.get('unattributedAttemptIds',[]))}。
- 数据导出中的案例归属缺失{len(data['unattributedAttemptNumbers'])}；受理优先按intakeId、调查按ticketId关联。任何降级时间窗口关联均在`caseAttributionMethod`显式标明。
- 调用耗时来自实际attempt.durationMs，包含网络/完整响应读取及适配处理，不能等同纯模型计算。HTTP200不等同业务通过。
- 2026-09-15核对[DeepSeek官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)：Pro高峰非缓存输入9元/百万token、输出27元/百万token。本报告统一使用该保守估算，不应用缓存/闲时折扣；逐请求缓存数据仍保留。
- 首轮独立采集未成功，故两轮累计量采用各自持久账本求和，不能称为两轮均完成独立对账。历史任务的未知费用不在本次两轮累计中，也未被清除。

## 证据入口

| 文件 | 内容 |
| --- | --- |
| [完整数据JSON](corrected/data.json) | 8例输入/受理/阶段时间戳、全文回复、事实/工具顺序、审计/SSE、代次、提案、执行数、逐模型调用与独立metrics |
| [逐例CSV](corrected/cases.csv) | 每例结果、耗时、请求数、token、费用与错误 |
| [逐调用CSV](corrected/attempts.csv) | 每次请求的角色、开始时间、耗时、输入输出/缓存、HTTP、失败分类、结算费用 |
| [阶段时间线CSV](corrected/timeline.csv) | 浏览器操作与可见结果的真实时间戳 |
| [冻结计划](corrected/plan.json) / [纠正说明](corrected/PLAN.md) | 输入、预期、模型、提示/schema、预算、产品提交与改动理由 |
| [已执行测试脚本](corrected/evaluation.spec.ts) | 真页面操作、SQL只读断言、逐例数据附件 |
| [运行器](corrected/runner.ps1) / [统计脚本](corrected/summarize.py) | 可审阅的执行和统计过程；运行器为本轮冻结档案，旧RunId/截止时间不能直接复跑 |
| [图片目录](corrected/screenshots/) | 8例原始页面截图，供人工复核；个别截图可能捕获页面过渡效果 |
| [首轮数据](data.json) / [首轮逐例表](cases.csv) | 初稿失败完整保留 |

宿主原始目录：`.local/gate-evidence/{data['runId']}/`，含Playwright JSON、失败trace、冻结脚本与账本。原始认证会话轨迹仅留本机；仓库产物为合成数据，不含密钥、cookie、授权头。报告中的订单与用户为演示数据。

## 验证与收尾

评测脚本Prettier、ESLint、TypeScript、8例枚举均通过；纠正轮先验证core-metrics模块可加载，再启动真实批次。结果记录`cleanupPassed={str(data['result']['cleanupPassed']).lower()}`、`productAcceptance={str(data['result']['productAcceptance']).lower()}`。本次只新增评测文档/数据，不修改产品代码；未执行产品实现交付的完整check.ps1，未创建/合并PR或关闭Issue，也未改写此前完整门禁中断记录。

具体回复质量复核与剩余问题见下节；即使本轮全部通过，也只能说明这8个合成场景在本次配置下的表现。
'''
(OUT/'README.md').write_text(text,encoding='utf-8')
with (CORRECTED/'timeline.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['场景ID','阶段','Unix毫秒','本例经过毫秒','补充数据'])
    for c in cases:
        for p in c['evidence'].get('phases',[]):w.writerow([c['id'],p['name'],p['at'],p['elapsedMs'],json.dumps(p.get('detail'),ensure_ascii=False)])
for source,destination in [('new-e2e.spec.ts','evaluation.spec.ts'),('runner.ps1','runner.ps1'),('PLAN.md','PLAN.md'),('summarize.py','summarize.py'),('report.py','report.py')]:
    shutil.copyfile(LOCAL/source,CORRECTED/destination)
shutil.copyfile(RAW/'plan.json',CORRECTED/'plan.json')
shutil.copyfile(RAW/'result.json',CORRECTED/'result.json')
(CORRECTED/'screenshots').mkdir(exist_ok=True)
for p in (RAW/'artifacts').glob('*.png'):shutil.copyfile(p,CORRECTED/'screenshots'/p.name)
print(json.dumps({'counts':data['counts'],'totalCalls':total_calls,'totalTokens':total_tokens,'totalCostMicros':total_cost,'ticketCount':ticket_count,'proposalCount':proposal_count},ensure_ascii=False))
