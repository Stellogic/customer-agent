"""仅核对已保存证据，不访问产品或供应商，不改写原 PASS/FAIL。"""
import json
from pathlib import Path

root = Path('D:/customer-agent/docs/eval/2026-09-15-e2e')
data = json.loads((root/'data.json').read_text(encoding='utf-8'))
checks = []
for case in data['cases']:
    ev = case['evidence']
    db = ev['business']
    assert db['executions']==0, case['id']
    if case['id'] in ('at24','at72'):
        expected_amount = 10 if case['id']=='at24' else 20
        assert len(db['tickets'])==1
        assert len(db['generations'])==1 and db['generations'][0]['status']=='COMPLETED'
        assert len(db['proposals'])==1
        proposal=db['proposals'][0]
        assert proposal['status']=='PENDING_APPROVAL' and proposal['method']=='COUPON'
        assert proposal['amount']==expected_amount
        assert proposal['delaySeconds']==ev['scenario']['delaySeconds']
        accepted=[c for c in db['commands'] if c['operation']=='SUBMIT_INVESTIGATION_CONCLUSION' and c['response'].get('accepted') is True]
        assert len(accepted)==1
        assert accepted[0]['response']['proposalStatus']=='PENDING_APPROVAL'
        assert sum(a['event_type']=='COMPENSATION_PROPOSAL_REVISION_CREATED' for a in db['audit'])==1
        replies=[m for m in db['messages'] if m['author']=='AGENT']
        assert len(replies)==1
        assert ev['firstReplyUi'] is not None
        assert '智能客服' in ev['firstReplyUi']['text']
        checks.append({'id':case['id'],'status':'SAVED_EVIDENCE_PASS','checks':['同代次完成','提案类型金额状态','提交命令accepted=true','提案创建审计一次','实际浏览器首个正文状态记录','执行数0'],
                       'notChecked':['本例刷新恢复：原脚本已提前失败，未执行'],'changesOriginalStatus':False})
    if case['id'] in ('under24','over72'):
        facts={f['fact_type']:f['fact_value'] for f in db['facts']}
        assert int(facts['LOGISTICS_DELAY_SECONDS']) != int(facts['LOGISTICS_DELAY_HOURS'])*3600
        assert db['tickets'][0]['reason']=='FACT_CONFLICT'
        assert not db['proposals']
        checks.append({'id':case['id'],'status':'CONTRACT_LIMIT_CONFIRMED','delayHours':facts['LOGISTICS_DELAY_HOURS'],'delaySeconds':facts['LOGISTICS_DELAY_SECONDS'],
                       'note':'冻结计划假设小时向下取整与秒数可并存；当前 Agent 合同要求精确整小时。本次不把该转人工计为模型失败，也不改写原始 FAIL。'})

assert len(data['attempts'])==22
assert sum(c['usage']['attempts'] for c in data['cases'])==22
assert sum(c['usage']['knownTokens'] for c in data['cases'])==data['ledgerTotals']['knownTokens']
assert sum(c['usage']['knownEstimatedCostMicros'] for c in data['cases'])==data['ledgerTotals']['knownEstimatedCostMicros']
for a in data['attempts']:
    assert a['status']=='SETTLED'
    assert a['estimatedCostMicros']==a['inputTokens']*9+a['outputTokens']*27
    assert a['attempt']['inputTokens']==a['inputTokens']
    assert a['attempt']['outputTokens']==a['outputTokens']
result={'method':'离线核对已保存的真实运行附件和持久预算账本；0 新模型请求',
        'originalResultUnchanged':True,'proposalCases':checks,
        'ledgerChecks':{'attempts':22,'tokens':25819,'costMicros':278793,'knownUsageEntries':22,'independentCollectorReconciliation':False},
        'executionCountAcrossAllSnapshots':0}
(root/'recheck.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
