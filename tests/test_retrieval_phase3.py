"""重排和语义模板契约；模拟打分不代替真实神经模型验收。"""
import json
import pytest
from test_multi_plan_fact import small_service, BASE
from local_agent.semantic import Query
from local_agent.multi_fact import MultiFactQuery
from local_agent.reranking import rerank
from local_agent.retrieval_service import RetrievalService, QueryContextBroker
from local_agent.query_templates import QueryTemplateCache
from local_agent.dense_retrieval import digest


@pytest.fixture
def rerank_config(tmp_path,monkeypatch):
    path=tmp_path/'reranker.json'
    path.write_text(json.dumps({'model':'test-only','revision':'fixture'}))
    monkeypatch.setenv('OWN_AGENT_RERANK_MODE','auto')
    monkeypatch.setenv('OWN_AGENT_RERANKER_IDENTITY',str(path))
    return path


HITS=[{'id':m,'metric_id':m,'kind':'metric','text':m,'source':m,'score':1} for m in ('a','b')]


@pytest.mark.parametrize('exact,ambiguous,reason', [({'a'},False,'exact'),(set(),True,'ambiguous')])
def test_exact_and_ambiguity_skip(rerank_config,exact,ambiguous,reason):
    class Forbidden:
        def score(*args): raise AssertionError('Should not call model')
    hits,trace=rerank('query',HITS,exact,ambiguous,Forbidden())
    assert hits==HITS and trace['reason']==reason


def test_reranker_reorders_preserves_retrieval_evidence(rerank_config):
    class Fake:
        def score(*args): return [-2.,4.],False
    hits,trace=rerank('query',HITS,set(),False,Fake())
    assert [h['id'] for h in hits]==['b','a']
    assert hits[0]['retrieval_rank']==2 and hits[0]['score']==1
    assert trace['score_type']=='raw_logit_not_probability'


def test_reranker_failure_falls_back_or_stops(rerank_config,monkeypatch):
    class Broken:
        def score(*args): raise RuntimeError('worker_failed')
    hits,trace=rerank('query',HITS,set(),False,Broken())
    assert hits==HITS and trace['status']=='fallback'
    monkeypatch.setenv('OWN_AGENT_RERANK_MODE','required')
    with pytest.raises(ValueError,match='required'):
        rerank('query',HITS,set(),False,Broken())


def test_invalid_score_shape_does_not_drop_candidates(rerank_config):
    class Broken:
        def score(*args): return [float('nan')],False
    hits,trace=rerank('query',HITS,set(),False,Broken())
    assert hits==HITS and trace['status']=='fallback'


def test_reranking_participates_in_broker(small_service,rerank_config,monkeypatch):
    tools,_=small_service
    def scores(self,question,hits,identity):
        return [10. if h.get('metric_id')=='average_order_value@1' else -1. for h in hits],False
    monkeypatch.setattr('local_agent.reranking.LocalReranker.score',scores)
    context=QueryContextBroker(tools).prepare('2026年9月平均每张订单的金额')
    assert context['version']=='phase3'
    assert context['discovery']['candidates'][0]['metric_id']=='average_order_value@1'
    assert context['semantic_context']['metrics']['average_order_value@1']['unit']=='source_amount/order'
    assert not context['values_loaded']


def query(**kwargs):
    return Query.model_validate({'metric_id':'booked_amount@1','start':'2026-09-01','end':'2026-09-15',**kwargs})


def test_template_hit_binds_fresh_dates_values_and_limit(small_service):
    tools,_=small_service
    first=tools.plan(query(filters={'country':'United States'},limit=10))
    second=tools.plan(query(start='2026-09-11',end='2026-09-14',filters={'country':'China'},limit=7))
    assert first['template_cache']['status']=='miss' and second['template_cache']['status']=='hit'
    assert first['template_cache']['template_id']==second['template_cache']['template_id']
    assert first['sql']!=second['sql']
    assert '2026-09-11' in second['sql'] and "'China'" in second['sql'] and 'LIMIT 7' in second['sql']
    result=tools.execute(second['plan_id'],second['approval_hash'])
    assert float(result['rows'][0][0])==90 and not result['template_cache']['results_cached']


def test_template_shape_and_identity_isolated(small_service):
    from local_agent.service import AgentTools
    tools,_=small_service
    first=tools.plan(query())
    grouped=tools.plan(query(group_by=['country']))
    assert grouped['template_cache']['status']=='miss'
    assert first['template_cache']['template_id']!=grouped['template_cache']['template_id']
    other=AgentTools(tools.home,token=tools.access.issue('us-analyst'))
    restricted=other.plan(query())
    assert restricted['template_cache']['status']=='miss'
    assert restricted['query']['filters']=={'country':'United States'}
    assert restricted['minimum_group_size']==5


def test_template_release_independent_but_plan_release_fresh(small_service):
    tools,_=small_service
    first=tools.plan(query())
    path=tools.home/'active.json'
    release=json.loads(path.read_text()); release['release_id']='new-release'
    path.write_text(json.dumps(release))
    second=tools.plan(query())
    assert second['template_cache']['status']=='hit' and second['release_id']=='new-release'
    with pytest.raises(ValueError,match='version changed|release mismatch'):
        tools.execute(first['plan_id'],first['approval_hash'])


def test_corrupt_template_rebuilt(small_service):
    tools,_=small_service
    first=tools.plan(query())
    cache=QueryTemplateCache(tools.home)
    with cache.connect() as db:
        db.execute('UPDATE templates SET payload=? WHERE key=?',('{}',first['template_cache']['template_id']))
    assert tools.plan(query())['template_cache']['status']=='rebuild_corrupt'


def test_forged_expression_still_rejected_by_execute(small_service):
    tools,_=small_service
    first=tools.plan(query())
    cache=QueryTemplateCache(tools.home)
    with cache.connect() as db:
        row=db.execute('SELECT payload FROM templates WHERE key=?',(first['template_cache']['template_id'],)).fetchone()
        payload=json.loads(row[0]); payload['expressions']['booked_amount@1']='COUNT(*)'
        db.execute('UPDATE templates SET payload=?,checksum=? WHERE key=?',
                   (json.dumps(payload),digest(payload),first['template_cache']['template_id']))
    forged=tools.plan(query())
    with pytest.raises(ValueError,match='SQL differs'):
        tools.execute(forged['plan_id'],forged['approval_hash'])


def test_multi_fact_template_keeps_aggregate_before_join(small_service):
    tools,_=small_service
    request=MultiFactQuery.model_validate(BASE)
    first=tools.plan(request); second=tools.plan(request.model_copy(update={'limit':2}))
    assert first['template_cache']['status']=='miss' and second['template_cache']['status']=='hit'
    assert second['logical_plan']['join_policy']=='aggregate each fact before joining conformed keys'
    assert 'FULL OUTER JOIN' in second['sql'] and 'LIMIT 2' in second['sql']
    assert len(tools.execute(second['plan_id'],second['approval_hash'])['rows'])==2


def test_cache_storage_failure_uses_fresh_compiler(small_service,monkeypatch):
    import sqlite3
    tools,_=small_service
    def broken(*args): raise sqlite3.OperationalError('unavailable')
    monkeypatch.setattr(QueryTemplateCache,'compile',broken)
    plan=tools.plan(query())
    assert plan['template_cache']['status']=='fallback'
    assert float(tools.execute(plan['plan_id'],plan['approval_hash'])['rows'][0][0])==415


def test_cache_disabled_and_illegal_grain_still_rejected(small_service,monkeypatch):
    tools,_=small_service
    monkeypatch.setenv('OWN_AGENT_TEMPLATE_CACHE','off')
    assert tools.plan(query())['template_cache']['status']=='disabled'
    with pytest.raises(ValueError): tools.plan(query(group_by=['category']))


def test_query_vector_memo_copies_values_and_revalidates_weights(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from local_agent.dense_retrieval import LocalEmbeddingProvider,_QUERY_VECTORS
    from local_agent.semantic import file_hash
    _QUERY_VECTORS.clear()
    weights=tmp_path/'model.safetensors'; weights.write_bytes(b'fixture')
    identity={'local_path':str(tmp_path),'files':{weights.name:file_hash(weights)}}
    calls=[]
    def worker(*args,**kwargs):
        calls.append(1); return SimpleNamespace(returncode=0,stdout='{"vectors":[[1.0,0.0]]}')
    monkeypatch.setattr('local_agent.dense_retrieval.subprocess.run',worker)
    provider=LocalEmbeddingProvider(identity)
    first=provider.encode(['query'],'query'); first[0][0]=0
    assert provider.encode(['query'],'query')==[[1.,0.]] and len(calls)==1
    weights.write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum'): provider.encode(['query'],'query')
    _QUERY_VECTORS.clear()


def test_rerank_score_memo_revalidates_weights(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from local_agent.reranking import LocalReranker,_SCORES
    from local_agent.semantic import file_hash
    _SCORES.clear()
    weights=tmp_path/'model.safetensors'; weights.write_bytes(b'fixture')
    identity={'local_path':str(tmp_path),'files':{weights.name:file_hash(weights)}}
    calls=[]
    def worker(*args,**kwargs):
        calls.append(1); return SimpleNamespace(returncode=0,stdout='{"scores":[-1.0,2.0]}')
    monkeypatch.setattr('local_agent.reranking.subprocess.run',worker)
    provider=LocalReranker()
    assert provider.score('query',HITS,identity)[1] is False
    assert provider.score('query',HITS,identity)[1] is True and len(calls)==1
    weights.write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum'): provider.score('query',HITS,identity)
    _SCORES.clear()
