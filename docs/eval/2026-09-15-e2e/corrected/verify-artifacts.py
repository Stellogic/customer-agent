import csv
import json
from pathlib import Path

root=Path('D:/customer-agent')
out=root/'docs/eval/2026-09-15-e2e'
data=json.loads((out/'corrected/data.json').read_text(encoding='utf-8'))
metrics=data['metrics']
calls=data['attempts']
assert data['counts']=={'PASS':8,'FAIL':0,'NOT_RUN':0}
assert data['result']['productAcceptance'] is True
assert len(calls)==metrics['knownProviderAttempts']==metrics['providerAttempts']==31
assert len({a['attemptId'] for a in calls})==31
assert sum(a['inputTokens']+a['outputTokens'] for a in calls)==metrics['tokens']==36096
assert sum(a['estimatedCostMicros'] for a in calls)==metrics['estimatedCostMicros']==394812
assert sum(c['usage']['attempts'] for c in data['cases'])==31
assert not data['unattributedAttemptNumbers']
for a in calls:
    assert a['status']=='SETTLED'
    assert a['estimatedCostMicros']==9*a['inputTokens']+27*a['outputTokens']
    assert a['attempt']['providerHttpStatus']==200
    assert a['attempt']['failureClassification'] is None
    assert a['caseAttributionMethod']=='ticket-or-intake-id'
for c in data['cases']:
    phases=[p['name'] for p in c['evidence']['phases']]
    assert 'checks_passed' in phases
    assert sum(name.startswith('refreshed_') for name in phases)==c['evidence']['scenario']['expectedTickets']
    assert not c['evidence']['browserErrors']
    assert c['evidence']['business']['executions']==0
assert 'support_claim_read_release' in data['cases'][-1]['evidence']['phases'][-2]['name']
for filename,n in [('cases.csv',8),('attempts.csv',31)]:
    with (out/'corrected'/filename).open(encoding='utf-8-sig',newline='') as f:
        assert len(list(csv.DictReader(f)))==n
assert len(list((out/'corrected/screenshots').glob('*.png')))==8
cleanup=json.loads((out/'corrected/cleanup.json').read_text(encoding='utf-8-sig'))
assert all(cleanup[k]==0 for k in ('containers','networks','volumes','images'))
key=None
for line in (root/'.env').read_text(encoding='utf-8-sig').splitlines():
    if line.startswith('DEEPSEEK_API_KEY='):
        key=line.split('=',1)[1].strip().strip('"').strip("'")
if key:
    for path in out.rglob('*'):
        if path.is_file() and path.suffix not in ('.png',):
            assert key not in path.read_text(encoding='utf-8-sig'), f'Real secret found in artifact: {path.name}'
result={'status':'PASS','checks':['31 unique calls match metrics and ledger','36096 tokens and 394812 micro-CNY reconcile','31 calls attributed by authoritative IDs','8 passed cases with refresh checks','split support claim/read/release completed','8 screenshots present','no browser errors','no compensation executions','owned resources absent','no actual configured provider secret in text artifacts'],
        'newProviderCalls':0}
(out/'corrected/verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
