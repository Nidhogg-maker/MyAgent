"""四阶段集成验收：真实本地模型/数据、隔离生命周期、可选真实LLM冒烟。"""
import argparse
import json
import os
import shutil
import uuid
from urllib.parse import quote
import duckdb
import httpx
from local_agent.semantic import ROOT,Query
from local_agent.service import AgentTools
from local_agent.agent_loop import AgentLoop
from local_agent.runtime import HarnessRuntime,SessionStore
from local_agent.retrieval import KnowledgeRetriever
from local_agent.retrieval_service import get_retrieval_service
from local_agent.structure import GraphService
from local_agent.dense_retrieval import publish_index,read_snapshot,LocalEmbeddingProvider

QUESTION='2026年9月平均每张订单的金额是多少'


def lifecycle(tools,identity):
    import local_agent.retrieval as lexical_module
    import local_agent.semantic_context as semantic_module
    directory=ROOT/'data'/('acceptance-lifecycle-'+uuid.uuid4().hex)
    directory.mkdir()
    assert directory.resolve().parent==(ROOT/'data').resolve()
    source=directory/'source'; (source/'knowledge').mkdir(parents=True)
    shutil.copyfile(ROOT/'knowledge/business.json',source/'knowledge/business.json')
    shutil.copytree(ROOT/'skills/warehouse-anomaly-attribution/references',source/'skills/warehouse-anomaly-attribution/references')
    index=directory/'index'; index.mkdir()
    _,base,_,_=read_snapshot(ROOT/'data/retrieval-index')
    pointer=json.loads((ROOT/'data/retrieval-index/active.json').read_text())
    shutil.copytree(ROOT/'data/retrieval-index'/pointer['folder'],index/pointer['folder'])
    shutil.copyfile(ROOT/'data/retrieval-index/active.json',index/'active.json')
    old_roots=(lexical_module.ROOT,semantic_module.ROOT)
    old_index=os.environ.get('OWN_AGENT_DENSE_INDEX')
    try:
        lexical_module.ROOT=semantic_module.ROOT=source
        os.environ['OWN_AGENT_DENSE_INDEX']=str(index)
        lexical=KnowledgeRetriever(tools); provider=LocalEmbeddingProvider(identity)
        initial=publish_index(tools,lexical,provider,index)
        assert initial['delta']['encoded']==0
        runtime=HarnessRuntime(tools,store=SessionStore(directory/'sessions.sqlite'))
        session=runtime.store.create(runtime.binding(),{'query_input':{'metric_id':'order_count@1','start':'2026-09-01','end':'2026-10-01'}})
        path=source/'knowledge/business.json'; business=json.loads(path.read_text(encoding='utf-8'))
        original=dict(business['cases'][0]); business['cases'][0]['note']+=' 隔离生命周期验收：更新说明v2。'
        path.write_text(json.dumps(business,ensure_ascii=False),encoding='utf-8')
        try: GraphService(tools).query('metric:average_order_value@1')
        except ValueError: stale_stopped=True
        else: raise AssertionError('Stale graph was accepted')
        updated=publish_index(tools,lexical,provider,index)
        assert updated['delta']['encoded']==1
        try: runtime.authorize(session)
        except ValueError: old_session_stopped=True
        else: raise AssertionError('Old session survived asset change')
        business['cases'].pop(0); path.write_text(json.dumps(business,ensure_ascii=False),encoding='utf-8')
        removed=publish_index(tools,lexical,provider,index)
        folder,_,docs,_=read_snapshot(index)
        assert original['id'] not in {d['id'] for d in docs}
        assert any(t['id']==original['id'] for t in json.loads((folder/'tombstones.json').read_text()))
        assert removed['delta']['encoded']==0 and removed['delta']['removed']==1
        business['cases'].append(original); path.write_text(json.dumps(business,ensure_ascii=False),encoding='utf-8')
        restored=publish_index(tools,lexical,provider,index)
        assert restored['delta']['encoded']==1 and restored['delta']['tombstones']==0
        return {'scope':'copied business assets; production Registry/knowledge untouched',
            'base_snapshot':base['snapshot_id'],'initial':initial['delta'],'updated':updated['delta'],
            'deleted':removed['delta'],'restored':restored['delta'],'stale_stopped':stale_stopped,
            'old_session_stopped':old_session_stopped,'source_fixture_retained':str(directory),'pass':True}
    finally:
        lexical_module.ROOT,semantic_module.ROOT=old_roots
        if old_index is None: os.environ.pop('OWN_AGENT_DENSE_INDEX',None)
        else: os.environ['OWN_AGENT_DENSE_INDEX']=old_index


def live_smoke(tools,expected):
    model=os.environ.get('OPENAI_MODEL')
    key=os.environ.get('OPENAI_API_KEY')
    if not key or not model:
        return {'status':'BLOCKED','reason':'local_model_credentials_missing','model':model}
    try:
        with httpx.Client(timeout=10) as client:
            probe=client.get('https://api.openai.com/v1/models/'+quote(model,safe=''),
                             headers={'Authorization':'Bearer '+key})
        if probe.status_code!=200:
            return {'status':'BLOCKED','reason':'model_preflight_rejected','http_status':probe.status_code,'model':model}
        loop=AgentLoop(tools)
        answer=loop.start(QUESTION,max_steps=4,max_searches=3)
        evidence=answer.get('answer',{}).get('evidence',[])
        actual=None
        if answer['status']=='COMPLETE' and evidence:
            actual=evidence[-1]['result']['rows'][0][0]
        passed=actual is not None and abs(float(actual)-float(expected))<1e-9
        return {'status':'PASS' if passed else 'FAIL','model':model,'model_preflight':200,
                'actual':actual,'raw_expected':expected,'answer':answer,
                'observations':loop.show(answer['session_id'])['observation_summary'],
                'scope':'one live LLM happy-path smoke, not accuracy evaluation'}
    except (httpx.RequestError,ValueError,KeyError,IndexError):
        return {'status':'BLOCKED','reason':'live_model_or_response_unavailable','model':model}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--live-llm',action='store_true')
    # 整体验收单独保存回执，避免覆盖阶段报告中的历史运行证据。
    parser.add_argument('--output', type=str, default=str(ROOT/'docs/retrieval-iteration-acceptance.json'))
    args=parser.parse_args()
    os.environ['OWN_AGENT_RETRIEVAL_MODE']='hybrid-required'
    os.environ['OWN_AGENT_RERANK_MODE']='required'
    os.environ['OWN_AGENT_STRUCTURED_MODE']='required'
    tools=AgentTools(ROOT/'data/own-agent')
    discovery=get_retrieval_service(tools).retrieve(QUESTION)
    assert discovery['trace']['dense']['status']=='ready' and discovery['trace']['reranker']['status']=='ready'
    warm=get_retrieval_service(tools).retrieve(QUESTION)
    assert warm['trace']['reranker']['cache_hit']
    def model(context,remaining):
        if not context['observations']:
            definitions=context['query_context']['semantic_context']['metrics']
            chosen=[key for key,spec in definitions.items() if spec['unit']=='source_amount/order']
            assert len(chosen)==1
            return {'action':'tool','tool':'query_relations','arguments':{
                'node_id':'metric:'+chosen[0],'direction':'dependencies','max_depth':4}},{'live':False}
        if len(context['observations'])==1:
            nodes=context['observations'][0]['result']['nodes']
            chosen=[n['metric_id'] for n in nodes if n['kind']=='metric' and n['unit']=='source_amount/order']
            assert len(chosen)==1
            return {'action':'tool','tool':'run_query','arguments':{
                'metric_id':chosen[0],'start':'2026-09-01','end':'2026-10-01'}},{'live':False}
        return {'action':'finish','message':'已校验组件并按权威口径查询；不是实收或因果结论。','evidence_ids':['e2']},{'live':False}
    loop=AgentLoop(tools,model); answer=loop.start(QUESTION)
    assert answer['status']=='COMPLETE',answer
    actual=answer['answer']['evidence'][0]['result']['rows'][0][0]
    with duckdb.connect(tools.release()['database'],read_only=True) as db:
        expected=db.execute('''SELECT
          (SELECT sum(cast(i.sale_price AS DECIMAL(18,4))) FROM raw.order_items i JOIN raw.orders o ON i.order_id=o.order_id
           WHERE cast(timezone('UTC',o.created_at) AS DATE)>=DATE '2026-09-01' AND cast(timezone('UTC',o.created_at) AS DATE)<DATE '2026-10-01') /
          NULLIF((SELECT count(*) FROM raw.orders WHERE cast(timezone('UTC',created_at) AS DATE)>=DATE '2026-09-01'
           AND cast(timezone('UTC',created_at) AS DATE)<DATE '2026-10-01'),0)''').fetchone()[0]
    assert abs(float(actual)-float(expected))<1e-9
    impact=GraphService(tools).query('field:commerce.fct_orders:booked_order_amount','impact',4)
    assert set(impact['affected_metrics'])=={'booked_amount@1','average_order_value@1'}
    metadata=tools.context('average_order_value@1')
    ambiguity=get_retrieval_service(tools).retrieve('销售额')
    assert ambiguity['status']=='CLARIFY' and ambiguity['trace']['reranker']['reason']=='ambiguous'
    partition=get_retrieval_service(tools).retrieve('订单数',partition='orders')
    assert all(h['partition']=='orders' for h in partition['hits'])
    identity=json.loads((ROOT/'data/embedding-identity.json').read_text())
    changes=lifecycle(tools,identity)
    live=live_smoke(tools,expected) if args.live_llm else {'status':'NOT_RUN','reason':'live flag not requested'}
    _,manifest,_,_=read_snapshot(ROOT/'data/retrieval-index')
    report={'status':'PASS' if not args.live_llm or live['status']=='PASS' else 'PASS_LOCAL_LLM_BLOCKED',
        'scope':'four-stage local engineering acceptance; not model accuracy/production scale certification',
        'local_checks':{'dense':True,'reranker':True,'structured_projection':True,'agent_graph_tool':True,
            'query_raw_reconciliation':True,'ambiguity_clarify':True,'partition_before_ranking':True,
            'warm_score_cache':True,'incremental_update_delete_restore':True,'old_session_stopped':True},
        'snapshot':manifest,'discovery':discovery,'scripted_agent':answer,
        'raw_check':{'actual':actual,'expected':expected,'pass':True},'field_impact':impact,
        'metadata':metadata,'lifecycle':changes,'live_llm':live,
        'not_certified':['model accuracy','production ANN/throughput','causal attribution','enterprise SSO','verified coverage watermark']}
    from pathlib import Path
    output=Path(args.output)
    output.write_text(json.dumps(report,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'raw_check':True,'value':actual,'graph_nodes':manifest['delta']['graph']['nodes'],
        'graph_edges':manifest['delta']['graph']['edges'],'incremental_lifecycle':True,'live_llm':live['status'],'output':str(output)}))
    if args.live_llm and live['status']!='PASS': raise SystemExit(2)


if __name__=='__main__': main()
