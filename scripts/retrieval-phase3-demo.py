"""真实 Dense/Cross-Encoder + 模拟决策模型 + 真实 TheLook；不是准确率评测。"""
import json
import os
import duckdb
from local_agent.semantic import ROOT,Query
from local_agent.service import AgentTools
from local_agent.agent_loop import AgentLoop
from local_agent.retrieval_service import get_retrieval_service
from local_agent.query_templates import QueryTemplateCache
from local_agent.reranking import rerank


def main():
    os.environ['OWN_AGENT_RETRIEVAL_MODE']='hybrid-required'
    os.environ['OWN_AGENT_RERANK_MODE']='required'
    tools=AgentTools(ROOT/'data/own-agent')
    service=get_retrieval_service(tools)
    question='2026年9月平均每张订单的金额是多少'
    cold=service.retrieve(question)
    warm=service.retrieve(question)
    assert cold['trace']['dense']['status']=='ready'
    assert cold['trace']['reranker']['status']=='ready'
    assert warm['trace']['reranker']['cache_hit'] is True
    _,exact=rerank(question,cold['hits'],{'order_count@1'},False)
    _,ambiguous=rerank(question,cold['hits'],set(),True)
    assert exact['reason']=='exact' and ambiguous['reason']=='ambiguous'

    def model(context,remaining):
        observations=context['observations']
        if not observations:
            discovery=context['query_context']['discovery']
            assert discovery['trace']['reranker']['status']=='ready'
            return {'action':'tool','tool':'resolve_semantics','arguments':{
                'metric_ids':[c['metric_id'] for c in discovery['candidates']],
                'expected_asset_version':discovery['index_version']}},{'live':False}
        if len(observations)==1:
            definitions=observations[0]['result']['metrics']
            chosen=[key for key,spec in definitions.items() if spec['unit']=='source_amount/order']
            assert len(chosen)==1,definitions
            return {'action':'tool','tool':'run_query','arguments':{
                'metric_id':chosen[0],'start':'2026-09-01','end':'2026-10-01'}},{'live':False}
        return {'action':'finish','message':'按权威语义计算平均下单金额；不是实收。','evidence_ids':['e2']},{'live':False}
    loop=AgentLoop(tools,model)
    answer=loop.start(question)
    assert answer['status']=='COMPLETE',answer
    actual=answer['answer']['evidence'][0]['result']['rows'][0][0]
    with duckdb.connect(tools.release()['database'],read_only=True) as db:
        expected=db.execute('''SELECT
            (SELECT sum(cast(i.sale_price AS DECIMAL(18,4))) FROM raw.order_items i
             JOIN raw.orders o ON i.order_id=o.order_id
             WHERE cast(timezone('UTC',o.created_at) AS DATE)>=DATE '2026-09-01'
               AND cast(timezone('UTC',o.created_at) AS DATE)<DATE '2026-10-01') /
            NULLIF((SELECT count(*) FROM raw.orders
             WHERE cast(timezone('UTC',created_at) AS DATE)>=DATE '2026-09-01'
               AND cast(timezone('UTC',created_at) AS DATE)<DATE '2026-10-01'),0)''').fetchone()[0]
        first=tools.plan(Query(metric_id='order_count@1',start='2026-09-01',end='2026-09-08',limit=73))
        second=tools.plan(Query(metric_id='order_count@1',start='2026-09-08',end='2026-09-15',limit=19))
        assert second['template_cache']['status']=='hit'
        assert first['template_cache']['template_id']==second['template_cache']['template_id']
        r1=tools.execute(first['plan_id'],first['approval_hash'])
        r2=tools.execute(second['plan_id'],second['approval_hash'])
        e1=db.execute("SELECT count(*) FROM raw.orders WHERE cast(timezone('UTC',created_at) AS DATE)>=DATE '2026-09-01' AND cast(timezone('UTC',created_at) AS DATE)<DATE '2026-09-08'").fetchone()[0]
        e2=db.execute("SELECT count(*) FROM raw.orders WHERE cast(timezone('UTC',created_at) AS DATE)>=DATE '2026-09-08' AND cast(timezone('UTC',created_at) AS DATE)<DATE '2026-09-15'").fetchone()[0]
    assert abs(float(actual)-float(expected))<1e-9
    assert r1['rows']==[[e1]] and r2['rows']==[[e2]]
    report={'mode':'real local neural models; scripted Agent; real TheLook',
        'question':question,'cold_discovery':cold,'warm_discovery':warm,'answer':answer,
        'reconciliation':{'actual':actual,'expected':expected,'pass':True},
        'skip_checks':{'exact':exact,'ambiguous':ambiguous},
        'template_rebinding':{'first_plan':first,'second_plan':second,'first_result':r1,'second_result':r2,
            'independent_counts':[e1,e2],'pass':True},'cache_stats':QueryTemplateCache(tools.home).stats()}
    output=ROOT/'docs/retrieval-phase3-live-demo.json'
    output.write_text(json.dumps(report,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
    print(json.dumps({'status':answer['status'],'value':actual,'raw_check':True,
        'reranker':cold['trace']['reranker']['status'],'warm_score_cache':warm['trace']['reranker']['cache_hit'],
        'two_window_counts':[e1,e2],'template_hit':True,'output':str(output)}))


if __name__=='__main__':
    main()
