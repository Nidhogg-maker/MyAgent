"""统一投影、增量/墓碑、权限前置和索引生命周期；数据发布使用隔离fixture。"""
import json
import shutil
import pytest
from test_multi_plan_fact import small_service
from local_agent.semantic import ROOT,SemanticRegistry,SQLCompiler,Query
from local_agent.assets import AssetBuilder
from local_agent.retrieval import KnowledgeRetriever
from local_agent.retrieval_service import RetrievalService
from local_agent.dense_retrieval import publish_index,read_snapshot
from local_agent.structure import GraphService


class Encoder:
    identity={'model':'test-only','revision':'1'}
    def __init__(self): self.batches=[]
    def encode(self,texts,kind):
        self.batches.append(list(texts))
        return [[1.,0.] for _ in texts]


@pytest.fixture
def assets(small_service,tmp_path,monkeypatch):
    tools,_=small_service
    root=tmp_path/'source'; root.mkdir()
    (root/'knowledge').mkdir()
    shutil.copyfile(ROOT/'knowledge/business.json',root/'knowledge/business.json')
    source=ROOT/'skills/warehouse-anomaly-attribution/references'
    target=root/'skills/warehouse-anomaly-attribution/references'
    shutil.copytree(source,target)
    monkeypatch.setattr('local_agent.retrieval.ROOT',root)
    monkeypatch.setattr('local_agent.semantic_context.ROOT',root)
    directory=tmp_path/'index'
    monkeypatch.setenv('OWN_AGENT_DENSE_INDEX',str(directory))
    monkeypatch.setenv('OWN_AGENT_STRUCTURED_MODE','auto')
    lexical=KnowledgeRetriever(tools); encoder=Encoder()
    manifest=publish_index(tools,lexical,encoder,directory)
    return tools,root,directory,lexical,encoder,manifest


def edit_business(root,change):
    path=root/'knowledge/business.json'; value=json.loads(path.read_text(encoding='utf-8'))
    change(value); path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')


def test_flat_and_structure_share_registered_metric_set(assets):
    tools,root,_,_,_,_=assets
    projection=AssetBuilder(tools,root=root).build()
    flat={d['metric_id'] for d in projection['documents'] if d['kind']=='metric'}
    graph={n['metric_id'] for n in projection['graph']['nodes'] if n['kind']=='metric'}
    assert flat==graph
    assert not projection['graph']['implicit_join_allowed']


def test_no_change_reuses_all_vectors_and_graph(assets):
    tools,_,directory,lexical,encoder,_=assets
    second=publish_index(tools,lexical,encoder,directory)
    assert len(encoder.batches)==1
    assert second['delta']['encoded']==0 and second['delta']['reused']==second['count']
    assert second['delta']['graph']['nodes_upserted']==0


def test_only_changed_case_encoded_and_removed_case_tombstoned(assets):
    tools,root,directory,lexical,encoder,_=assets
    edit_business(root,lambda b:b['cases'][0].update(note='隔离测试更新案例摘要'))
    changed=publish_index(tools,lexical,encoder,directory)
    assert changed['delta']['encoded']==1 and len(encoder.batches[-1])==1
    original=json.loads((root/'knowledge/business.json').read_text(encoding='utf-8'))['cases'][0]
    edit_business(root,lambda b:b['cases'].pop(0))
    removed=publish_index(tools,lexical,encoder,directory)
    folder,_,docs,_=read_snapshot(directory)
    assert removed['delta']['removed']==1 and removed['delta']['encoded']==0
    assert original['id'] not in {d['id'] for d in docs}
    tombstones=json.loads((folder/'tombstones.json').read_text())
    assert any(t['id']==original['id'] for t in tombstones)
    edit_business(root,lambda b:b['cases'].append(original))
    restored=publish_index(tools,lexical,encoder,directory)
    assert restored['delta']['added']==1 and restored['delta']['encoded']==1
    assert restored['delta']['tombstones']==0


def test_new_case_added_without_reencoding_existing_assets(assets):
    tools,root,directory,lexical,encoder,_=assets
    edit_business(root,lambda b:b['cases'].append({'id':'isolated-new','metric_id':'order_count@1',
        'question':'隔离案例订单量','note':'不是生产业务结论'}))
    result=publish_index(tools,lexical,encoder,directory)
    assert result['delta']['added']==1 and result['delta']['encoded']==1


def test_embedding_identity_change_reencodes_all(assets):
    tools,_,directory,lexical,_,_=assets
    encoder=Encoder(); encoder.identity={'model':'test-only','revision':'2'}
    result=publish_index(tools,lexical,encoder,directory)
    assert result['delta']['encoded']==result['count'] and result['delta']['reused']==0


def test_metric_delete_removes_graph_and_blocks_old_id_and_alias(assets):
    tools,root,directory,lexical,encoder,_=assets
    path=root/'registry.json'; contract=json.loads(tools.registry.path.read_text(encoding='utf-8'))
    contract['metrics'].pop('buyer_count@1'); path.write_text(json.dumps(contract),encoding='utf-8')
    tools.registry=SemanticRegistry(path); tools.compiler=SQLCompiler(tools.registry)
    # 仅测试fixture同步签名，不是生产数据发布替代流程。
    release=json.loads((tools.home/'active.json').read_text()); release['registry_sha256']=tools.registry.version
    (tools.home/'active.json').write_text(json.dumps(release))
    result=publish_index(tools,lexical,encoder,directory)
    assert result['delta']['removed']>=1 and result['delta']['graph']['nodes_removed']>=1
    with pytest.raises(ValueError,match='unknown metric ID'):
        RetrievalService(tools).retrieve('buyer_count@1')
    aliases=lexical.business['aliases']['buyer_count@1']
    with pytest.raises(ValueError,match='deleted metric'):
        RetrievalService(tools).retrieve(aliases[0])
    with pytest.raises(ValueError,match='unauthorized'):
        GraphService(tools).query('metric:buyer_count@1')


def test_field_impact_and_component_dependencies(assets):
    tools,*_=assets
    graph=GraphService(tools)
    impact=graph.query('field:commerce.fct_orders:booked_order_amount','impact',4)
    assert set(impact['affected_metrics'])=={'booked_amount@1','average_order_value@1'}
    dependencies=graph.query('metric:average_order_value@1','dependencies',4)
    assert {'metric:booked_amount@1','metric:order_count@1'} <= {n['id'] for n in dependencies['nodes']}
    assert not dependencies['implicit_join_allowed']


def test_graph_acl_filters_before_traversal(assets):
    from local_agent.service import AgentTools
    tools,*_=assets
    restricted=AgentTools(tools.home,token=tools.access.issue('us-analyst'))
    result=GraphService(restricted).query('dataset:commerce.fct_orders','impact',5)
    assert 'buyer_count@1' not in result['affected_metrics']
    assert all(n.get('column') not in ('user_id','gender','age_band') for n in result['nodes'])
    with pytest.raises(ValueError,match='unauthorized'):
        GraphService(restricted).query('metric:buyer_count@1')


def test_graph_budget_and_unknown_node(assets):
    tools,*_=assets
    result=GraphService(tools).query('metric:average_order_value@1',max_nodes=1)
    assert len(result['nodes'])==1 and result['truncated']
    with pytest.raises(ValueError,match='budget'): GraphService(tools).query('metric:order_count@1',max_depth=7)
    with pytest.raises(ValueError,match='unauthorized'): GraphService(tools).query('SELECT * FROM raw.users')


def test_stale_projection_falls_back_only_to_current_registry(assets,monkeypatch):
    from local_agent.semantic_context import SemanticContextResolver
    tools,root,*_=assets
    edit_business(root,lambda b:b['aliases']['order_count@1'].append('隔离订单笔数'))
    with pytest.raises(ValueError,match='Stale'): GraphService(tools).query('metric:order_count@1')
    context=SemanticContextResolver(tools).resolve(['order_count@1'])
    assert context['index_evidence']['status']=='registry_fallback'
    monkeypatch.setenv('OWN_AGENT_STRUCTURED_MODE','required')
    with pytest.raises(ValueError,match='required'): SemanticContextResolver(tools).resolve(['order_count@1'])


def test_partition_filter_and_explicit_scope_conflict(assets):
    tools,*_=assets
    result=RetrievalService(tools).retrieve('订单数',partition='orders')
    assert all(h['partition']=='orders' for h in result['hits'])
    with pytest.raises(ValueError,match='outside requested partition'):
        RetrievalService(tools).retrieve('item_count@1',partition='orders')


def test_corrupt_old_index_never_used_for_incremental_reuse(assets):
    tools,_,directory,lexical,encoder,_=assets
    folder,*_=read_snapshot(directory)
    pointer=(directory/'active.json').read_bytes(); (folder/'vectors.json').write_text('[]')
    with pytest.raises(ValueError,match='checksum'): publish_index(tools,lexical,encoder,directory)
    assert (directory/'active.json').read_bytes()==pointer


def test_concurrent_publication_detected_before_outer_switch(assets):
    tools,root,directory,lexical,_,_=assets
    edit_business(root,lambda b:b['cases'][0].update(note='强制生成新向量'))
    class Concurrent(Encoder):
        def encode(self,texts,kind):
            publish_index(tools,lexical,Encoder(),directory)
            return super().encode(texts,kind)
    with pytest.raises(ValueError,match='Concurrent'):
        publish_index(tools,lexical,Concurrent(),directory)
    _,manifest,_,_=read_snapshot(directory)
    assert manifest['delta']['encoded']==1


def test_old_plan_rejected_after_snapshot_switch(assets):
    tools,_,directory,lexical,encoder,_=assets
    plan=tools.plan(Query(metric_id='order_count@1',start='2026-09-01',end='2026-10-01'))
    publish_index(tools,lexical,encoder,directory)
    with pytest.raises(ValueError,match='version changed'):
        tools.execute(plan['plan_id'],plan['approval_hash'])


def test_live_shaped_tool_narration_stops_before_query(small_service,monkeypatch):
    import httpx
    from local_agent.agent_loop import AgentLoop,ModelDecision
    tools,_=small_service
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    monkeypatch.setenv('OPENAI_MODEL','test-only')
    def response(request):
        payload={'action':'tool','tool':'run_query','arguments_json':json.dumps({
            'metric_id':'order_count@1','start':'2026-09-01','end':'2026-10-01'}),
            'message':'不合法的工具叙述','evidence_ids':[]}
        return httpx.Response(200,json={'status':'completed','output':[
            {'type':'message','content':[{'type':'output_text','text':json.dumps(payload)}]}]})
    result=AgentLoop(tools,ModelDecision(httpx.MockTransport(response))).start('2026年9月订单数')
    assert result['status']=='STOPPED' and result['runtime']['queries_used']==0
    assert result['observations']==[]
