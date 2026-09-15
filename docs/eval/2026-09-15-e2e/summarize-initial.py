import base64
import csv
import json
import math
import re
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path('D:/customer-agent')
LOCAL = ROOT / '.local/eval-20260915'
RAW = ROOT / '.local/gate-evidence/issue230-real-eval-20260915'
OUT = ROOT / 'docs/eval/2026-09-15-e2e'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def stats(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {'n': 0}
    return {'n': len(values), 'meanMs': round(statistics.mean(values), 2),
            'p50Ms': statistics.median(values), 'p90Ms': values[math.ceil(len(values)*.9)-1],
            'minMs': values[0], 'maxMs': values[-1]}

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def rows(suite):
    for spec in suite.get('specs', []):
        for test in spec['tests']:
            for result in test['results']:
                attachments = result.get('attachments', [])
                item = next((a for a in attachments if a['name']=='evaluation-case'), None)
                evidence = json.loads(base64.b64decode(item['body'])) if item and 'body' in item else {}
                yield {'id':spec['title'].split()[-1], 'title':spec['title'],
                       'status':{'passed':'PASS','skipped':'NOT_RUN'}.get(result['status'],'FAIL'),
                       'browserStatus':result['status'], 'durationMs':result['duration'],
                       'startedAt':result.get('startTime'), 'evidence':evidence,
                       'errors':[e.get('message','') for e in result.get('errors',[])],
                       'annotations':test.get('annotations',[])}
    for child in suite.get('suites', []):
        yield from rows(child)

report = read(RAW/'artifacts/playwright.json')
ledger = read(RAW/'ledger.final.json')
metrics = read(RAW/'metrics.json') if (RAW/'metrics.json').exists() else {
    'status':'NOT_COLLECTED',
    'reason':'本轮 runner 误将 frontend/src 挂载到 core-metrics 的 /app/src，遮蔽 Python 包；独立计量汇总未执行。账本和逐例业务快照已保存。',
    'attempts':[],
}
cases = [row for suite in report['suites'] for row in rows(suite)]
attempt_metrics = {a['attemptId']: a for a in metrics['attempts']}
attempts = []
for number, entry in enumerate(ledger['entries'],1):
    measured = attempt_metrics.get(entry['attemptId'], {})
    item = {k:v for k,v in entry.items() if k not in ('session','attempt')}
    item['number'] = number
    item['attempt'] = entry.get('attempt')
    item['intakeId'] = measured.get('intakeId')
    item['caseId'] = None
    item['caseAttributionMethod'] = None
    for case in cases:
        ev = case['evidence']
        ids = (ev.get('confirmation') or {}).get('ticketIds', [])
        intakes = [i.get('intakeId') for i in ev.get('intakeSnapshots', [])]
        if (entry.get('ticketId') and entry['ticketId'] in ids) or (item['intakeId'] and item['intakeId'] in intakes):
            item['caseId'] = case['id']
            item['caseAttributionMethod'] = 'ticket-or-intake-id'
            break
    if item['caseId'] is None and entry['role']=='intake':
        at = datetime.fromisoformat(entry['startedAt']).timestamp()*1000
        matches = [c for c in cases if c['evidence'].get('startedAt',float('inf')) <= at <= c['evidence'].get('endedAt',-1)]
        if len(matches)==1:
            item['caseId'] = matches[0]['id']
            item['caseAttributionMethod'] = 'serial-browser-case-time-window'
    attempts.append(item)

for case in cases:
    ev = case['evidence']
    case['errors'] = [re.sub(r'\x1b\[[0-9;]*m','',e) for e in case['errors']]
    phase = {p['name']:p['at'] for p in ev.get('phases', [])}
    def duration(start,end):
        return phase[end]-phase[start] if start in phase and end in phase else None
    first = ev.get('firstReplyUi')
    case['timing'] = {
        'intakeClickToResponseMs': duration('intake_clicked','intake_response'),
        'confirmationToTicketsMs': duration('confirmation_clicked','tickets_created'),
        'confirmationToTerminalMs': duration('confirmation_clicked','all_terminal'),
        'confirmationToReplyUiMs': first['at']-phase['confirmation_clicked'] if first and 'confirmation_clicked' in phase else None,
        'intakeClickToTerminalMs': duration('intake_clicked','all_terminal'),
    }
    linked = [a for a in attempts if a['caseId']==case['id']]
    complete = all(a.get('inputTokens') is not None and a.get('outputTokens') is not None and a.get('estimatedCostMicros') is not None for a in linked)
    case['usage'] = {'attempts':len(linked), 'attemptNumbers':[a['number'] for a in linked],
                     'allUsageKnown':complete,
                     'knownTokens':sum((a.get('inputTokens') or 0)+(a.get('outputTokens') or 0) for a in linked),
                     'tokens':sum(a['inputTokens']+a['outputTokens'] for a in linked) if complete else None,
                     'knownEstimatedCostMicros':sum(a.get('estimatedCostMicros') or 0 for a in linked),
                     'estimatedCostMicros':sum(a['estimatedCostMicros'] for a in linked) if complete else None}
    if case['status']=='NOT_RUN':
        case['usage']['allUsageKnown'] = None

summary = {'runId':'issue230-real-eval-20260915','result':read(RAW/'result.json'),
           'plan':read(RAW/'plan.json'), 'browserStats':report['stats'],
           'counts':{status:sum(c['status']==status for c in cases) for status in ('PASS','FAIL','NOT_RUN')},
           'unattributedAttemptNumbers':[a['number'] for a in attempts if not a['caseId']],
           'caseLatency':stats([c['durationMs'] for c in cases if c['status']!='NOT_RUN']),
           'timings':{key:stats([c['timing'][key] for c in cases]) for key in cases[0]['timing']},
           'roleLatency':{role:stats([(a.get('attempt') or {}).get('durationMs') for a in attempts if a['role']==role]) for role in ('intake','action','judgment','communication')},
           'cases':cases,'attempts':attempts,'metrics':metrics}
summary['ledgerTotals'] = {
    'source':'persistent-budget-ledger-only; independent-metrics-collector-unavailable',
    'attempts':len(attempts),
    'knownTokens':sum((a.get('inputTokens') or 0)+(a.get('outputTokens') or 0) for a in attempts),
    'knownEstimatedCostMicros':sum(a.get('estimatedCostMicros') or 0 for a in attempts),
    'statuses':{s:sum(a['status']==s for a in attempts) for s in ('SETTLED','PENDING','IN_FLIGHT')},
    'unknownUsage':sum(a.get('inputTokens') is None or a.get('outputTokens') is None for a in attempts),
    'supplierChargeMicros':None,
    'independentMetricsReconciliation':False,
}

OUT.mkdir(parents=True,exist_ok=True)
write_json(OUT/'data.json',summary)
write_json(OUT/'scenarios.json',read(LOCAL/'scenarios.json'))
write_json(OUT/'ledger.json',{k:v for k,v in ledger.items() if k!='entries'} | {'entries':attempts})
with (OUT/'cases.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.writer(f)
    writer.writerow(['场景ID','名称','结果','整例毫秒','确认至终态毫秒','确认至正文UI毫秒','请求数','已知token','估算元','错误'])
    for c in cases:
        writer.writerow([c['id'],c['evidence'].get('scenario',{}).get('title'),c['status'],c['durationMs'],c['timing']['confirmationToTerminalMs'],c['timing']['confirmationToReplyUiMs'],c['usage']['attempts'],c['usage']['knownTokens'],c['usage']['knownEstimatedCostMicros']/1e6,'\n'.join(c['errors'])])
with (OUT/'attempts.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.writer(f)
    writer.writerow(['序号','场景ID','角色','开始时间','结算状态','耗时毫秒','输入token','输出token','缓存token','HTTP','终态','失败分类','估算元'])
    for a in attempts:
        r=a.get('attempt') or {}
        writer.writerow([a['number'],a['caseId'],a['role'],a['startedAt'],a['status'],r.get('durationMs'),a.get('inputTokens'),a.get('outputTokens'),r.get('cachedTokens'),r.get('providerHttpStatus'),r.get('responseStatus'),r.get('failureClassification'),a['estimatedCostMicros']/1e6 if a.get('estimatedCostMicros') is not None else '未知'])
print(json.dumps({k:summary[k] for k in ('counts','unattributedAttemptNumbers','caseLatency','timings','roleLatency')},ensure_ascii=False,indent=2))
print(json.dumps([{k:c[k] for k in ('id','status','errors','timing','usage')} for c in cases],ensure_ascii=False,indent=2))
