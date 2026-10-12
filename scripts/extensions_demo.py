"""保存七项扩展的真实本地运行证据，令牌只在进程内使用。"""
import datetime as dt
import json
import sqlite3
from local_agent.semantic import ROOT,Query
from local_agent.service import AgentTools
from local_agent.harness import build_agent

def main():
    tools=AgentTools()
    agent=build_agent(tools)
    task=json.loads((ROOT/'config/diagnosis.example.json').read_text(encoding='utf-8'))
    diagnosis=agent.invoke({'task_input':task})
    partial=agent.invoke({'question':'今天的转化率为什么比昨天低'})
    credential=tools.access.issue('us-analyst')
    restricted=AgentTools(tools.home,token=credential)
    plan=restricted.plan(Query(metric_id='order_count@1',start='2026-09-01',end='2026-10-01'))
    result=restricted.execute(plan['plan_id'],plan['approval_hash'])
    try:
        restricted.plan(Query(metric_id='order_count@1',start='2026-09-01',end='2026-09-02',group_by=('gender',)))
        denial='UNEXPECTED_ALLOWED'
    except ValueError as error:
        denial=str(error)
    history=tools.home/'history.sqlite'
    counts={}
    if history.exists():
        with sqlite3.connect(history) as db:
            counts=dict(db.execute('SELECT entity,count(*) FROM versions GROUP BY entity'))
    report={'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'real_llm_evaluated':False,
            'diagnosis':{'status':diagnosis['status'],'trace':diagnosis['trace'],'skill':diagnosis['skill'],'result':diagnosis['result']},
            'ambiguous_question':{'status':partial['status'],'trace':partial['trace'],'error':partial['error'],'partial_intent':partial.get('retrieval')},
            'restricted_identity':{'subject':restricted.principal,'effective_filters':plan['query']['filters'],'sql':plan['sql'],'result':result,'sensitive_group_denial':denial},
            'lineage':tools.lineage('commerce.fct_orders','booked_order_amount'),
            'observed_history':{'entity_versions':counts,'business_valid_time_verified':False}}
    target=ROOT/'docs/extensions-demo.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    tools.access.revoke(credential)
    print('Extended evidence:',target)

if __name__=='__main__':
    main()
