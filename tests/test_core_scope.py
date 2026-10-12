"""本地链路必要验证，不进行模型准确率评测或Skill内独立测试目录。"""
import json
import time
import httpx
import pytest
from local_agent.semantic import ROOT, Query
from local_agent.service import AgentTools
from local_agent.dimensions import DimensionResolver
from local_agent.skill_resources import PACKAGES, resources
from local_agent.resilience import CircuitBreaker,CircuitOpen,TransientFailure,RetryPolicy,retry_call,retry_after
from local_agent.runtime import HarnessRuntime,SessionStore
from local_agent.tasks import TaskInterpreter
from local_agent.retrieval import KnowledgeRetriever
from local_agent.openai_provider import request_task

@pytest.fixture(scope='module')
def tools(tmp_path_factory):
    tools=AgentTools(tmp_path_factory.mktemp('core-scope'))
    tools.publish(ROOT/'data/thelook.duckdb',ROOT/'warehouse-commerce/target/manifest.json',ROOT/'docs/thelook-dbt-run-results.json')
    return tools

def test_skill_directories_and_linked_references():
    for identifier in PACKAGES:
        loaded=resources(identifier,references=True)
        assert loaded['entry'].endswith('/SKILL.md') and 'description:' in loaded['instructions']
    loaded=resources('anomaly-analysis',references=True)
    assert len(loaded['references'])==3

def test_dimension_values_and_unknown_value_clarifies(tools):
    resolver=DimensionResolver(tools)
    q=Query(metric_id='complete_order_rate@1',start='2026-09-01',end='2026-10-01',filters={'country':'美国','gender':'男性'})
    assert resolver.query(q).filters=={'country':'United States','gender':'M'}
    with pytest.raises(ValueError,match='CLARIFY:'):
        resolver.query(q.model_copy(update={'filters':{'country':'Atlantis'}}))

def test_logical_plan_and_split_retrieval(tools):
    retriever=KnowledgeRetriever(tools)
    hits=retriever.search('订单完成占比为什么变化')
    paths=retriever.paths('订单完成占比为什么变化',hits)
    assert paths['semantic_candidates'] and paths['knowledge_hits']
    compiled=tools.compiler.compile(Query(metric_id='complete_order_rate@1',start='2026-09-01',end='2026-10-01'))
    assert compiled['logical_plan']['components']['denominator']=='order_count@1'

def test_four_endpoints_and_recent_days(tools):
    parser=TaskInterpreter(tools)
    assert len(parser._windows('UTC闭开[2026-09-01,2026-09-08)比[2026-08-01,2026-08-08)'))==2
    start,end=parser._windows('最近7天')[0]
    assert (end-start).days==7
    with pytest.raises(ValueError,match='CLARIFY'):
        parser.parse('2026年9月支付成功率是多少')

def test_transient_retry_and_circuit_reset(tmp_path):
    breaker=CircuitBreaker(tmp_path/'circuit.sqlite',RetryPolicy(base_delay=0))
    attempts=[]
    def operation(remaining):
        attempts.append(remaining)
        if len(attempts)<3: raise TransientFailure('temporary')
        return 'ok'
    assert retry_call(operation,breaker,'worker',time.monotonic()+5,sleep=lambda _:None)=='ok'
    assert len(attempts)==3 and breaker.snapshot()[0]['failures']==0

def test_open_half_open_single_probe_and_permanent_no_retry(tmp_path):
    clock=[100.0]
    breaker=CircuitBreaker(tmp_path/'circuit.sqlite',RetryPolicy(attempts=1,threshold=1,cooldown=10),clock=lambda:clock[0])
    def fail(_): raise TransientFailure('temporary')
    with pytest.raises(TransientFailure): retry_call(fail,breaker,'worker',time.monotonic()+5)
    with pytest.raises(CircuitOpen): breaker.before('worker')
    clock[0]=111
    assert breaker.before('worker')=='HALF_OPEN'
    with pytest.raises(CircuitOpen): breaker.before('worker')
    breaker.success('worker')
    assert breaker.before('worker')=='CLOSED'
    calls=[]
    def invalid(_): calls.append(1); raise ValueError('illegal grain')
    with pytest.raises(ValueError,match='illegal grain'):
        retry_call(invalid,breaker,'worker',time.monotonic()+5)
    assert len(calls)==1 and breaker.snapshot()[0]['failures']==0

def model_response():
    body={'clarify':None,'task':{'kind':'query','query':{'metric_id':'order_count@1','start':'2026-09-01',
        'end':'2026-10-01','group_by':[],'filters':[],'limit':100},'baseline':None,
        'expected_direction':'unknown','diagnosis_dimensions':[]}}
    return {'status':'completed','model':'test-model','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(body)}]}]}

def test_official_adapter_retry_and_quota_stop(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','mock-secret')
    monkeypatch.setenv('OPENAI_MODEL','test-model')
    calls=[]
    def transport(request):
        calls.append(1)
        return httpx.Response(503,json={'error':{'code':'server_is_overloaded'}},headers={'Retry-After':'0'}) if len(calls)==1 else httpx.Response(200,json=model_response())
    body,evidence=request_task('question',{},httpx.MockTransport(transport))
    assert body['kind']=='query' and len(calls)==2
    assert any(e['kind']=='retry-scheduled' for e in evidence['attempts'])
    quota=[]
    def exhausted(request):
        quota.append(1)
        return httpx.Response(429,json={'error':{'code':'insufficient_quota','type':'insufficient_quota'}})
    with pytest.raises(ValueError,match='MODEL_HTTP_ERROR'):
        request_task('question',{},httpx.MockTransport(exhausted))
    assert len(quota)==1

def test_runtime_retry_consumes_actual_attempts_and_report_template(tools,tmp_path,monkeypatch):
    original=tools.execute
    calls=[]
    def flaky(*args,**kwargs):
        calls.append(1)
        if len(calls)==1: raise ValueError('Query worker terminated')
        return original(*args,**kwargs)
    monkeypatch.setattr(tools,'execute',flaky)
    runtime=HarnessRuntime(tools,store=SessionStore(tmp_path/'sessions.sqlite'))
    result=runtime.start({'query_input':{'metric_id':'order_count@1','start':'2026-09-01','end':'2026-10-01'}})
    assert result['status']=='COMPLETE' and result['runtime']['queries_used']==2
    assert '# 指标查询证据报告' in result['answer']['markdown'] and '{{' not in result['answer']['markdown']
    events=runtime.show(result['session_id'])['events']
    assert any(e['kind']=='retry-scheduled' for e in events)
    assert any(e['payload'].get('entrypoint','').endswith('SKILL.md') for e in events)

def test_retry_after_is_bounded_and_invalid_nan_ignored(tmp_path):
    assert retry_after('nan') is None and retry_after('3')==3
    breaker=CircuitBreaker(tmp_path/'circuit.sqlite')
    calls=[]
    def fail(_): calls.append(1); raise TransientFailure('wait',120)
    with pytest.raises(TransientFailure): retry_call(fail,breaker,'worker',time.monotonic()+5,sleep=lambda _:None)
    assert len(calls)==1

@pytest.mark.parametrize('question,body',[
    ('2026年9月美国订单量是多少',{'kind':'query','query':{'metric_id':'order_count@1','start':'2026-09-01','end':'2026-10-01'}}),
    ('2026年9月订单完成占比为什么变化',{'kind':'diagnose','query':{'metric_id':'complete_order_rate@1','start':'2026-09-01','end':'2026-10-01'},
        'baseline':{'metric_id':'complete_order_rate@1','start':'2026-08-01','end':'2026-08-31'}})])
def test_model_cannot_drop_filter_or_invent_baseline(tools,monkeypatch,question,body):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.setenv('LLM_BASE_URL','https://mock.invalid/v1')
    monkeypatch.setenv('LLM_API_KEY','mock-secret')
    monkeypatch.setenv('LLM_MODEL','mock-model')
    parser=TaskInterpreter(tools,mode='llm',transport=httpx.MockTransport(lambda _:httpx.Response(200,
        json={'choices':[{'message':{'content':json.dumps(body)}}]})))
    with pytest.raises(ValueError,match='CLARIFY:'):
        parser.parse(question)
