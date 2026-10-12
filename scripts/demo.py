"""生成真实结构化 Agent 演示证据；不把它称为自然语言模型评测。"""
import datetime as dt
import json
from local_agent.semantic import ROOT, Query
from local_agent.service import AgentTools
from local_agent.harness import build_agent

def main():
    tools = AgentTools()
    agent = build_agent(tools)
    cases = [
        {'metric_id':'average_order_value@1','start':'2026-09-01','end':'2026-10-01','group_by':['country']},
        {'metric_id':'complete_item_amount@1','start':'2026-09-01','end':'2026-10-01','group_by':['category'],'limit':100},
        {'metric_id':'order_count@1','start':'2026-09-01','end':'2026-09-08','group_by':['category']},
    ]
    outputs = []
    for case in cases:
        state = agent.invoke({'query_input':case})
        outputs.append({'input':case, 'status':state['status'], 'trace':state['trace'],
                        'sql':state.get('plan',{}).get('sql'), 'result':state.get('result'), 'error':state.get('error')})
    compare = tools.compare(Query(metric_id='order_count@1',start='2026-08-01',end='2026-08-08'),
                            Query(metric_id='order_count@1',start='2026-09-01',end='2026-09-08'))
    report = {'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),
              'scope':'Actual official-synthetic TheLook, structured IR; no LLM accuracy claim',
              'cases':outputs, 'comparison':compare,
              'field_lineage':tools.catalog.field_lineage('commerce.fct_orders','booked_order_amount')}
    target = ROOT / 'docs/demo-result.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print('Demo evidence:', target)

if __name__ == '__main__':
    main()
