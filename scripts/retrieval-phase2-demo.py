"""真实 E5 向量 + 真实 TheLook + 模拟决策模型；不是 LLM 准确率评测。"""
import json
import os
import duckdb
from local_agent.semantic import ROOT
from local_agent.service import AgentTools
from local_agent.agent_loop import AgentLoop
from local_agent.retrieval_service import RetrievalService


def main():
    os.environ['OWN_AGENT_RETRIEVAL_MODE'] = 'hybrid-required'
    tools = AgentTools(ROOT/'data/own-agent')
    question = '2026年9月平均每张订单的金额是多少'
    discovery = RetrievalService(tools).retrieve(question)
    assert discovery['trace']['dense']['status'] == 'ready'
    assert any('dense' in h['ranks'] for h in discovery['hits'])
    def model(context, remaining):
        if not context['observations']:
            assert context['query_context']['discovery']['trace']['dense']['status'] == 'ready'
            definitions = context['query_context']['semantic_context']['metrics']
            ids = [key for key, spec in definitions.items() if spec['unit'] == 'source_amount/order']
            assert len(ids) == 1, definitions
            return {'action':'tool', 'tool':'run_query', 'arguments': {
                'metric_id':ids[0], 'start':'2026-09-01', 'end':'2026-10-01'}}, {'live':False}
        return {'action':'finish','message':'以权威定义计算平均下单金额。','evidence_ids':['e1']}, {'live':False}
    loop = AgentLoop(tools, model)
    answer = loop.start(question)
    assert answer['status'] == 'COMPLETE', answer
    actual = answer['answer']['evidence'][0]['result']['rows'][0][0]
    with duckdb.connect(tools.release()['database'], read_only=True) as db:
        expected = db.execute('''SELECT
          (SELECT sum(cast(i.sale_price AS DECIMAL(18,4))) FROM raw.order_items i
             JOIN raw.orders o ON i.order_id=o.order_id
             WHERE cast(timezone('UTC',o.created_at) AS DATE)>=DATE '2026-09-01'
               AND cast(timezone('UTC',o.created_at) AS DATE)<DATE '2026-10-01')
          / NULLIF((SELECT count(*) FROM raw.orders
             WHERE cast(timezone('UTC',created_at) AS DATE)>=DATE '2026-09-01'
               AND cast(timezone('UTC',created_at) AS DATE)<DATE '2026-10-01'),0)''').fetchone()[0]
    assert abs(float(actual)-float(expected)) < 1e-9
    ambiguous = RetrievalService(tools).retrieve('销售额')
    assert ambiguous['status'] == 'CLARIFY'
    report = {'mode':'real local neural embeddings; scripted decision model; real TheLook',
        'question':question, 'discovery':discovery, 'answer':answer,
        'reconciliation':{'actual':actual,'expected':expected,'pass':True},
        'ambiguity_status':ambiguous['status'],
        'observations':loop.show(answer['session_id'])['observation_summary']}
    output = ROOT/'docs/retrieval-phase2-live-demo.json'
    output.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
    print(json.dumps({'status':answer['status'],'value':actual,'raw_check':True,
        'dense': discovery['trace']['dense']['status'], 'output':str(output)}))


if __name__ == '__main__':
    main()
