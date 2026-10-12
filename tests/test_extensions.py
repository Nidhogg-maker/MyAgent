"""七项扩展的正反例：规则NLU、Mock模型、权限、时间、血缘、历史及诊断。"""
import datetime as dt
import json
from pathlib import Path
import sqlite3
import shutil
import httpx
import pytest
from local_agent.semantic import ROOT,Query,file_hash
from local_agent.service import AgentTools
from local_agent.tasks import Task,TaskInterpreter
from local_agent.retrieval import KnowledgeRetriever
from local_agent.evaluation import evaluate_rules,load_cases
from local_agent.access import AccessDenied
from local_agent.temporal import coverage,check_window,DateResolver
from local_agent.control_lineage import extract_control
from local_agent.history import SnapshotHistory
from local_agent.diagnosis import DiagnosisEngine
from local_agent.harness import build_agent

@pytest.fixture(scope='module')
def tools(tmp_path_factory):
    if not (ROOT/'data/thelook.duckdb').exists():
        pytest.skip('Official snapshot unavailable')
    tools = AgentTools(tmp_path_factory.mktemp('extensions'))
    tools.publish(ROOT/'data/thelook.duckdb',ROOT/'warehouse-commerce/target/manifest.json',ROOT/'docs/thelook-dbt-run-results.json')
    return tools

@pytest.mark.parametrize('case',load_cases(),ids=lambda case:case['id'])
def test_curated_local_intent_cases(tools,case):
    interpreter = TaskInterpreter(tools,now=dt.datetime(2026,10,11,12,tzinfo=dt.timezone.utc))
    if case['expected']=='CLARIFY':
        with pytest.raises(ValueError,match='CLARIFY:'):
            interpreter.parse(case['question'])
    else:
        task = interpreter.parse(case['question'])
        assert task.kind==case['expected'] and task.query.metric_id==case['metric']
        if 'start' in case:assert str(task.query.start)==case['start']
        if 'end' in case:assert str(task.query.end)==case['end']
        if 'groups' in case:assert list(task.query.group_by)==case['groups']
        if 'baseline_start' in case:assert str(task.baseline.start)==case['baseline_start']

def test_retrieval_metric_and_schema_link(tools):
    retriever = KnowledgeRetriever(tools)
    assert retriever.search('2026年9月下单金额')[0]['metric_id']=='booked_amount@1'
    link = retriever.link('booked_amount@1')
    assert link['grain']=='order_id'
    assert any(edge['to'].endswith('raw.order_items:sale_price') for edge in link['lineage']['edges'])

def test_evaluation_is_not_real_llm_accuracy(tools):
    report = evaluate_rules(tools)
    assert report['passed']==report['total']==32
    assert report['real_llm_evaluated'] is False
    assert all(row['hit_at_3'] for row in report['retrieval'])

def test_ambiguous_diagnosis_preserves_partial_intent(tools):
    result=build_agent(tools).invoke({'question':'今天的转化率为什么比昨天低'})
    assert result['status']=='CLARIFY' and result['trace']==['intent']
    assert result['retrieval']['intent_hint']=='diagnose'
    assert result['retrieval']['skill_hint']=='commerce-diagnosis'
    assert result['retrieval']['relative_terms']==['今天','昨天']

def model_parser(tools,monkeypatch,body):
    monkeypatch.setenv('LLM_BASE_URL','https://mock.invalid/v1')
    monkeypatch.setenv('LLM_API_KEY','TEST_SECRET_NOT_FOR_REPORTS')
    monkeypatch.setenv('LLM_MODEL','mock-model')
    def handler(request):
        prompt = json.loads(request.content)
        assert 'retrieved_evidence' in prompt['messages'][0]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(body)}}]})
    return TaskInterpreter(tools,mode='llm',transport=httpx.MockTransport(handler))

def test_mock_model_ir_then_actual_database(tools,monkeypatch):
    body={'kind':'query','query':{'metric_id':'order_count@1','start':'2026-09-01','end':'2026-10-01'}}
    parser = model_parser(tools,monkeypatch,body)
    result = build_agent(tools,parser).invoke({'question':'查询2026年9月订单量'})
    assert result['status']=='COMPLETE' and result['result']['rows'][0][0]>0
    assert 'TEST_SECRET_NOT_FOR_REPORTS' not in json.dumps(result)

@pytest.mark.parametrize('body',[
    {'sql':'SELECT * FROM raw.users'},
    {'kind':'query','query':{'metric_id':'unknown@1','start':'2026-09-01','end':'2026-10-01'}},
    {'kind':'query','query':{'metric_id':'order_count@1','start':'2026-09-01','end':'2026-10-01','principal':'admin'}},
    {'kind':'diagnose','query':{'metric_id':'order_count@1','start':'2026-09-01','end':'2026-10-01'}},
])
def test_mock_model_bad_outputs_stop_before_execution(tools,monkeypatch,body):
    result = build_agent(tools,model_parser(tools,monkeypatch,body)).invoke({'question':'查询2026年9月订单量'})
    assert result['status']=='STOPPED' and 'execute' not in result['trace']

def test_mock_model_clarification(tools,monkeypatch):
    result = build_agent(tools,model_parser(tools,monkeypatch,{'clarify':'请选择下单金额还是已完成金额'})).invoke({'question':'销售额是多少'})
    assert result['status']=='CLARIFY' and len(result['trace'])==1

@pytest.mark.parametrize('query',[
    {'metric_id':'booked_amount@1','start':'2026-09-01','end':'2026-10-01'},
    {'metric_id':'order_count@1','start':'2026-08-01','end':'2026-09-01'},
])
def test_mock_model_semantic_mismatch_clarifies(tools,monkeypatch,query):
    parser=model_parser(tools,monkeypatch,{'kind':'query','query':query})
    result=build_agent(tools,parser).invoke({'question':'查询2026年9月订单量'})
    assert result['status']=='CLARIFY' and 'execute' not in result['trace']

def test_token_expiry_after_plan(tools,monkeypatch):
    import local_agent.access as access
    token=tools.access.issue('us-analyst',lifetime=60)
    restricted=AgentTools(tools.home,token=token)
    plan=restricted.plan(Query(metric_id='order_count@1',start='2026-09-01',end='2026-09-02'))
    original=access.time.time
    monkeypatch.setattr(access.time,'time',lambda:original()+120)
    with pytest.raises(AccessDenied):restricted.execute(plan['plan_id'],plan['approval_hash'])

def test_us_row_policy_and_column_metric_denials(tools):
    token = tools.access.issue('us-analyst')
    restricted = AgentTools(tools.home,token=token)
    query = Query(metric_id='order_count@1',start='2026-09-01',end='2026-10-01')
    plan = restricted.plan(query)
    assert plan['query']['filters']=={'country':'United States'}
    assert 'HAVING COUNT(*) >= 5' in plan['sql']
    result = restricted.execute(plan['plan_id'],plan['approval_hash'])
    with __import__('duckdb').connect(str(ROOT/'data/thelook.duckdb'),read_only=True) as db:
        expected = db.execute("SELECT count(*) FROM commerce.fct_orders WHERE order_date>='2026-09-01' AND order_date<'2026-10-01' AND country='United States'").fetchone()[0]
    assert result['rows']==[[expected]]
    with pytest.raises(AccessDenied):restricted.describe('buyer_count@1')
    with pytest.raises(AccessDenied):restricted.plan(Query(metric_id='order_count@1',start='2026-09-01',end='2026-09-02',group_by=('gender',)))
    with pytest.raises(AccessDenied):restricted.plan(Query(metric_id='order_count@1',start='2026-09-01',end='2026-09-02',filters={'country':'China'}))
    with pytest.raises(AccessDenied):restricted.lineage('raw.users')
    assert 'user_id' not in json.dumps(restricted.context('order_count@1'))
    assert not any(hit.get('metric_id')=='buyer_count@1' for hit in KnowledgeRetriever(restricted).search('购买用户数'))

def test_small_aggregate_suppressed(tools):
    restricted = AgentTools(tools.home,token=tools.access.issue('us-analyst'))
    plan = restricted.plan(Query(metric_id='order_count@1',start='2010-01-01',end='2010-01-02'))
    assert restricted.execute(plan['plan_id'],plan['approval_hash'])['rows']==[]

def test_tampered_and_revoked_token(tools):
    token = tools.access.issue('us-analyst')
    with pytest.raises(AccessDenied):AgentTools(tools.home,token=token+'x')
    restricted = AgentTools(tools.home,token=token)
    plan = restricted.plan(Query(metric_id='order_count@1',start='2026-09-01',end='2026-09-02'))
    tools.access.revoke(token)
    with pytest.raises(AccessDenied):restricted.execute(plan['plan_id'],plan['approval_hash'])

def test_source_observation_is_not_watermark():
    state=coverage('hash',ROOT/'docs/thelook-source-manifest.json')
    assert state['verified'] is False and state['complete_through'] is None
    with pytest.raises(ValueError,match='observation'):
        check_window(Query(metric_id='order_count@1',start='2026-11-01',end='2026-11-02'),state,now=dt.datetime(2027,1,1,tzinfo=dt.timezone.utc))

def test_bound_watermark_receipt_and_late_window(tmp_path):
    receipt = tmp_path/'receipt.json'
    receipt.write_text(json.dumps({'database_sha256':'hash','complete_through':'2026-09-03T00:00:00+00:00',
        'observed_at':'2026-09-04T00:00:00+00:00','attested_by':'fixture-pipeline','evidence_refs':['fixture://run-1']}),encoding='utf-8')
    state=coverage('hash',None,receipt)
    assert state['verified']
    with pytest.raises(ValueError,match='hash/time'):coverage('wrong-hash',None,receipt)
    with pytest.raises(ValueError,match='watermark'):
        check_window(Query(metric_id='order_count@1',start='2026-09-03',end='2026-09-04'),state)

def test_relative_utc_boundary():
    resolver=DateResolver(dt.datetime(2026,10,12,1,tzinfo=dt.timezone(dt.timedelta(hours=11))))
    assert resolver.today==dt.date(2026,10,11)
    assert resolver.relative('昨天')==(dt.date(2026,10,10),dt.date(2026,10,11))

def test_join_where_group_control_dependencies():
    schemas={'raw.orders':[{'name':n} for n in ('order_id','user_id','status')], 'raw.users':[{'name':n} for n in ('id','country')]}
    sql="SELECT o.order_id FROM raw.orders o JOIN raw.users u ON o.user_id=u.id WHERE o.status='Complete' GROUP BY o.order_id"
    result=extract_control(sql,schemas)
    edges={(e['table'],e['column'],e['kind']) for e in result['edges']}
    assert ('raw.orders','user_id','join') in edges and ('raw.users','id','join') in edges
    assert ('raw.orders','status','filter') in edges and ('raw.orders','order_id','group') in edges
    assert result['complete_within_supported_scope']

def test_control_ambiguity_not_marked_complete():
    schemas={'raw.a':[{'name':'id'}],'raw.b':[{'name':'id'}]}
    result=extract_control('SELECT a.id FROM raw.a a JOIN raw.b b ON a.id=b.id WHERE id>0',schemas)
    assert result['unresolved'] and not result['complete_within_supported_scope']

def test_actual_model_cte_control_lineage(tools):
    result=tools.catalog.field_lineage('commerce.fct_orders','booked_order_amount')
    assert any(edge['kind']=='control_join' for edge in result['control_dependencies'])
    assert any(edge['to'].endswith('commerce.fct_order_items:order_id') for edge in result['control_dependencies'])

def test_snapshot_history_status_change_late_record_and_rollback(tmp_path):
    history=SnapshotHistory(tmp_path/'history.sqlite')
    first='2026-01-01T00:00:00+00:00';second='2026-01-02T00:00:00+00:00'
    history.capture('orders',[{'id':1,'status':'Processing'}],first,'fixture-1')
    result=history.capture('orders',[{'id':1,'status':'Complete'},{'id':2,'created_at':'2025-12-01'}],second,'fixture-2')
    assert result['changed']==2
    assert history.as_of('orders',1,first)['status']=='Processing'
    assert history.as_of('orders',1,second)['status']=='Complete'
    assert history.as_of('orders',2,first) is None
    with pytest.raises(ValueError,match='Duplicate'):
        history.capture('orders',[{'id':1,'status':'Returned'},{'id':1,'status':'Cancelled'}],'2026-01-03T00:00:00+00:00','fixture-bad')
    assert history.as_of('orders',1,'2026-01-04T00:00:00+00:00')['status']=='Complete'
    with pytest.raises(ValueError,match='chronology'):
        history.capture('orders',[{'id':1}], '2025-01-01T00:00:00+00:00','old')

class FixtureTools:
    """故障真值用的小型工具替身；不标成真实数据或真实模型集成。"""
    def __init__(self,verified=True,truncated=False,new_amount=80):
        self.verified,self.truncated,self.new_amount=verified,truncated,new_amount
        self.calls={}
    def release(self):return {'release_id':'fixture','temporal':{'verified':self.verified,'mode':'test-fixture'}}
    def plan(self,query):
        identifier=str(len(self.calls));self.calls[identifier]=query
        return {'plan_id':identifier,'approval_hash':'fixture'}
    def execute(self,identifier,approval_hash,timeout_seconds=30):
        q=self.calls[identifier];old=q.start.month==8
        counts=10 if old else 8;amount=100 if old else self.new_amount
        value={'order_count@1':counts,'booked_amount@1':amount,'average_order_value@1':amount/counts}[q.metric_id]
        rows=[['A',value*0.7],['B',value*0.3]] if q.group_by else [[value]]
        return {'rows':rows,'columns':['group','value'] if q.group_by else ['value'],
                'release_id':'fixture','plan_id':identifier,'result_may_be_truncated':self.truncated,'temporal':{'verified':self.verified}}

def fixture_task(metric='booked_amount@1',direction='unknown'):
    return Task(kind='diagnose',query=Query(metric_id=metric,start='2026-09-01',end='2026-09-08'),
                baseline=Query(metric_id=metric,start='2026-08-01',end='2026-08-08'),expected_direction=direction)

def test_diagnosis_algebra_and_counter_evidence():
    report=DiagnosisEngine(FixtureTools()).run(fixture_task())
    assert report['status']=='OBSERVATIONS_ONLY' and report['queries_used']==8
    assert abs(report['decompositions'][0]['residual'])<1e-8
    assert report['decompositions'][0]['volume_contribution']==-20
    assert report['decompositions'][0]['basket_value_contribution']==0
    assert any(h['status']=='REFUTED_NO_CHANGE' for h in report['hypotheses'])
    assert report['causal_claim'] is False

def test_diagnosis_ratio_components_reconcile():
    report=DiagnosisEngine(FixtureTools()).run(fixture_task('average_order_value@1'))
    assert report['queries_used']==6 and abs(report['decompositions'][0]['residual'])<1e-8

def test_user_premise_refuted():
    report=DiagnosisEngine(FixtureTools(new_amount=120)).run(fixture_task(direction='decrease'))
    assert report['status']=='PREMISE_REFUTED' and len(report['evidence'])==2

@pytest.mark.parametrize('tools,budget,reason',[
    (FixtureTools(verified=False),8,None), (FixtureTools(truncated=True),8,'Truncated'),
    (FixtureTools(),2,'budget'),
])
def test_diagnosis_insufficient_evidence_stops(tools,budget,reason):
    report=DiagnosisEngine(tools,max_queries=budget).run(fixture_task())
    assert report['status']=='INSUFFICIENT_EVIDENCE' and report['causal_claim'] is False
    if reason:assert reason in report['stopped_reason']

def test_actual_diagnosis_routes_skill_and_preserves_watermark_gap(tools):
    task=Task.model_validate_json((ROOT/'config/diagnosis.example.json').read_text(encoding='utf-8'))
    result=build_agent(tools).invoke({'task_input':task.model_dump(mode='json')})
    assert result['skill']=='commerce-diagnosis' and result['trace']==['intent','metadata','diagnosis','answer']
    assert result['status']=='INSUFFICIENT_EVIDENCE'
    assert result['result']['queries_used']==8 and result['result']['causal_claim'] is False

def test_actual_staged_data_fault_rejects_old_dbt_pass(tmp_path):
    """只在副本注入重复明细，证明旧PASS不能发布已变化数据；上游数据保持原样。"""
    source=ROOT/'data/thelook.duckdb'
    if not source.exists():pytest.skip('Official source unavailable')
    original_hash=file_hash(source)
    sandbox=tmp_path/'thelook.duckdb'
    shutil.copy2(source,sandbox)
    import duckdb
    with duckdb.connect(str(sandbox)) as db:
        db.execute('INSERT INTO raw.order_items SELECT * FROM raw.order_items LIMIT 1')
    service=AgentTools(tmp_path/'fault-release')
    with pytest.raises(ValueError,match='Current database failed dbt assertion'):
        service.publish(sandbox,ROOT/'warehouse-commerce/target/manifest.json',ROOT/'docs/thelook-dbt-run-results.json')
    assert not (service.home/'active.json').exists()
    assert file_hash(source)==original_hash


def test_model_country_value_linking(tools,monkeypatch):
    body={'kind':'query','query':{'metric_id':'order_count@1','start':'2026-09-01',
          'end':'2026-10-01','filters':{'country':'美国'}}}
    parser=model_parser(tools,monkeypatch,body)
    result=build_agent(tools,parser).invoke({'question':'2026年9月只看美国的订单数是多少'})
    assert result['query']['filters']['country']=='United States'
    assert result['status']=='COMPLETE'
    import duckdb
    with duckdb.connect(str(tools.release()['database']),read_only=True) as connection:
        expected=connection.execute("SELECT count(*) FROM raw.orders o JOIN raw.users u ON o.user_id=u.id WHERE u.country='United States' AND cast(timezone('UTC', o.created_at) as date)>=DATE '2026-09-01' AND cast(timezone('UTC', o.created_at) as date)<DATE '2026-10-01'").fetchone()[0]
    assert result['result']['rows'][0][0]==expected==1420
