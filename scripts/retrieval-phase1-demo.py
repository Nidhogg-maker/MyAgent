"""真实数据+模拟模型：证明首次检索参与选择，歧义停止，结构约束持续生效。"""
import json
import duckdb
from local_agent.semantic import ROOT
from local_agent.service import AgentTools
from local_agent.agent_loop import AgentLoop
from local_agent.retrieval_service import RetrievalService
from local_agent.semantic_context import SemanticContextResolver


def main():
    service = AgentTools(ROOT/'data/retrieval-phase1-demo')
    release = service.publish(ROOT/'data/thelook.duckdb', ROOT/'warehouse-commerce/target/manifest.json',
                              ROOT/'docs/thelook-dbt-run-results.json')
    question = '2026年9月平均每张订单的金额是多少'
    def model(context, remaining):
        if not context['observations']:
            discovery = context['query_context']['discovery']
            assert all(c['match'] == 'lexical' for c in discovery['candidates'])
            metrics = context['query_context']['semantic_context']['metrics']
            selected = [m for m, definition in metrics.items() if definition['unit'] == 'source_amount/order']
            assert len(selected) == 1
            return {'action':'tool','tool':'run_query','arguments':{
                'metric_id':selected[0],'start':'2026-09-01','end':'2026-10-01'}}, {'live':False,'provider':'scripted-context-consumer'}
        return {'action':'finish','message':'已根据首次检索得到的权威口径计算平均下单金额；不是实收。',
                'evidence_ids':['e1']}, {'live':False,'provider':'scripted-context-consumer'}
    runtime = AgentLoop(service, model)
    answer = runtime.start(question)
    if answer['status'] != 'COMPLETE':
        raise RuntimeError(answer.get('error', answer))
    value = answer['answer']['evidence'][0]['result']['rows'][0][0]
    with duckdb.connect(release['database'], read_only=True) as db:
        expected = db.execute('''SELECT
          (SELECT sum(cast(i.sale_price AS DECIMAL(18,4))) FROM raw.order_items i
             JOIN raw.orders o ON i.order_id=o.order_id
             WHERE cast(timezone('UTC',o.created_at) AS DATE)>=DATE '2026-09-01'
               AND cast(timezone('UTC',o.created_at) AS DATE)<DATE '2026-10-01')
          / NULLIF((SELECT count(*) FROM raw.orders
             WHERE cast(timezone('UTC',created_at) AS DATE)>=DATE '2026-09-01'
               AND cast(timezone('UTC',created_at) AS DATE)<DATE '2026-10-01'),0)''').fetchone()[0]
    assert abs(float(value)-float(expected)) < 1e-9
    def guess(context, remaining):
        return {'action':'tool','tool':'run_query','arguments':{
            'metric_id':'booked_amount@1','start':'2026-09-01','end':'2026-10-01'}}, {'live':False}
    ambiguity = AgentLoop(service, guess).start('2026年9月销售额是多少')
    assert ambiguity['status'] == 'CLARIFY' and ambiguity['runtime']['queries_used'] == 0
    cache = RetrievalService(service)
    first = cache.retrieve('订单数'); second = cache.retrieve('商品件数')
    assert cache.lexical.index_builds == 1 and first['index_version'] == second['index_version']
    structured = SemanticContextResolver(service).resolve(['items_per_order@1'], requested_dimensions=['country','category'])
    assert structured['unresolved'] == ['incompatible_dimension:category']
    report = {'mode':'scripted model; real TheLook; no live model API request',
        'non_alias_question':question,'retrieval_driven_answer':answer,
        'independent_raw_reconciliation':{'actual':value,'expected':expected,'pass':True},
        'ambiguous_query':ambiguity,'structured_discovery':structured,
        'cache':{'index_builds':cache.lexical.index_builds,'index_version':first['index_version']},
        'events':runtime.show(answer['session_id'])['observation_summary']}
    output = ROOT/'docs/retrieval-phase1-live-demo.json'
    output.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
    print(json.dumps({'status':answer['status'],'raw_check':True,'value':value,
        'ambiguity':ambiguity['status'],'queries':answer['runtime']['queries_used'],
        'cache_builds':cache.lexical.index_builds,'live_model':False,'output':str(output)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
