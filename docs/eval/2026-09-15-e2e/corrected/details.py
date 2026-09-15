import json
from pathlib import Path

root=Path('D:/customer-agent/docs/eval/2026-09-15-e2e')
data=json.loads((root/'corrected/data.json').read_text(encoding='utf-8'))
lines=['# 修正版逐例详情','', '数据来源为本次真实浏览器附件、数据库只读快照和供应商计量。所有订单均为合成测试数据；以下正文为模型在本轮实际发布的内容。','']
for c in data['cases']:
    ev=c['evidence']; db=ev['business']; s=ev['scenario']
    lines.extend([f"## {c['id']}：{s['title']}",'',f"- 结果：**{c['status']}**；整例 {c['durationMs']/1000:.3f} 秒。",f"- 输入：{s['description']}",f"- 订单：`{ev['reference']}`；延迟 {s['delaySeconds']} 秒；其他事实见 scenarios.json。",f"- 模型请求 {c['usage']['attempts']} 次，{c['usage']['tokens']} token，估算 {c['usage']['estimatedCostMicros']/1e6:.6f} 元。",''])
    for t in db['tickets'] or []:
        generation=next(g for g in db['generations'] if g['ticket_id']==t['id'])
        lines.extend([f"### 工单 `{t['id']}`",'',f"类型 `{t['issueKind']}`；处理模式 `{t['handlingMode']}`；代次 `{generation['status']}`；人工原因 `{t['reason']}`。",'', '**实际公开回复**',''])
        replies=[m for m in db['messages'] or [] if m['ticketId']==t['id'] and m['author']=='AGENT']
        if replies:
            for reply in replies:lines.extend(['> '+reply['body'].replace('\n','\n> '),''])
        else:lines.extend(['本例按预期直接交人工，没有生成 Agent 业务正文；固定人工通知不计作生成回答。',''])
        facts=[f for f in db['facts'] or [] if f['generation_id']==generation['id']]
        lines.extend(['**同代次权威事实**','','| 类型 | 值 |','| --- | --- |'])
        for f in facts:lines.append(f"| {f['fact_type']} | {f['fact_value'].replace('|',' / ')} |")
        commands=[x for x in db['commands'] or [] if x['generationId']==generation['id']]
        lines.extend(['','**已持久化工具/命令顺序**','', ' → '.join('`'+x['operation']+'`' for x in commands),''])
    lines.extend(['**逐模型请求**','','| 编号 | 角色 | 耗时ms | 输入token | 输出token | HTTP | 结算 |','| ---: | --- | ---: | ---: | ---: | ---: | --- |'])
    for a in data['attempts']:
        if a['caseId']==c['id']:
            r=a['attempt'];lines.append(f"| {a['number']} | {a['role']} | {r['durationMs']} | {a['inputTokens']} | {a['outputTokens']} | {r['providerHttpStatus']} | {a['status']} |")
    lines.extend(['', '**浏览器步骤**','', ' → '.join('`'+p['name']+'`' for p in ev['phases']),'', f"[本例截图](screenshots/{c['id']}.png)",''])
(root/'corrected/逐例详情.md').write_text('\n'.join(lines),encoding='utf-8')

review='''
## 回复质量人工复核与剩余边界

人工对照本轮7条实际Agent正文、同工单权威事实和页面状态；不使用付费裁判模型，不把结构化通过率当回答质量分数。

| 场景 | 事实/状态一致性 | 说明充分性与表达 |
| --- | --- | --- |
| 23小时查询物流 | 不予补偿与不足24小时一致，没有越权承诺 | 回复偏泛，没有直接讲出已读取的时长/物流状态；追加“资料没有通用规则”仍未充分回答用户要查的状态。这是本轮最明显的答复质量改进点 |
| 24小时 / 72小时 / 73小时 | 正文均说明等待人工审批、尚未执行；页面分别展示10元券、20元券、9.90元模拟部分退款 | 审批阶段表达清楚；具体金额主要由页面卡片承担，正文没有展开计算依据 |
| 已取消 / 已有补偿 | 按不支持场景交人工，无新增提案 | 两例未生成业务正文，只检验正确交人工及刷新恢复，不计入“回答正确率” |
| 已全额退款的重复扣款疑虑 | 清楚区分已支付/已全额退款与尚不能确认重复扣款；本次未新执行退款 | 对用户问题有直接回应，人工后续边界明确 |
| 同订单拆票物流正文 | 待审批与无执行一致，订单没有串用 | 开头仍提及同订单重复扣款，可进一步聚焦当前物流票；不据此认定串票或越权 |
| 同订单拆票支付正文 | 与已支付、未全额退款、仅疑似重复扣款一致，没有宣称已退款或已查实 | “尚未完成全额退款”可能让用户误以为退款流程已启动；事实字段只说明未全额退款，措辞可更精确 |

全部7条正文未发现与本轮权威状态直接矛盾或声称已执行新补偿；这不是7/7语义充分性通过。尤其23小时样本，业务断言通过但说明质量仍有改善空间。完整原文与工具读取顺序见[逐例详情](corrected/逐例详情.md)。

### 这次证明了什么

- 本轮8个合成场景在真实模型与产品链路下满足冻结的业务/恢复断言；9张工单、4份待审批提案，0次补偿执行。
- 同订单两问题在一次确认后产生两张票，分别恢复并由客服领取支付票读取事实后释放。
- 31笔模型请求的持久账本与独立指标完整对齐；无新未知用量。不能据此证明所有异常断流路径都已验证。

### 仍未覆盖

- 正式批准与执行补偿、UNKNOWN对账、并发吞吐、真实生产订单及大样本质量分布。
- 非整小时时长通过完整Agent链路；当前Graph仍限制精确整小时。若以后要支持，应先统一小时与秒的字段含义。
- “物流没收到”与“延迟”的开放式语义边界；本次纠正了预期，没有改变现有分类规则，也没有证明该分类在所有表达下都符合用户意图。
- 首轮被断言提前截断的步骤不会由修正版追溯补记为通过；两轮数据分别保留。

本次到评测完成为止，不顺手修改产品或新增架构。下一步如改善演示效果，优先处理物流回复解释不够具体的问题，并复用这些数据做小规模对照。
'''
report=root/'README.md'
report.write_text(report.read_text(encoding='utf-8')+review,encoding='utf-8')
print('Per-case evidence and semantic review saved')
