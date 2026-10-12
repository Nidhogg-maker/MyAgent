"""核心链路测试：真实数据库、持久回执、跨实例恢复和有界 Skill 编排。"""
import json
import subprocess
import pytest
from local_agent.service import AgentTools
from local_agent.semantic import ROOT, Query
from local_agent.runtime import HarnessRuntime, SessionStore
from local_agent.skills import SkillRegistry, SkillExecutor

@pytest.fixture(scope='module')
def tools(tmp_path_factory):
    tools=AgentTools(tmp_path_factory.mktemp('runtime-skills'))
    tools.publish(ROOT/'data/thelook.duckdb',ROOT/'warehouse-commerce/target/manifest.json',ROOT/'docs/thelook-dbt-run-results.json')
    return tools

def request():
    return {'query_input':{'metric_id':'order_count@1','start':'2026-09-01','end':'2026-10-01'}}

def test_skill_contract_cycle_and_illegal_drilldown(tools):
    registry=SkillRegistry()
    assert len(registry.specs)==7
    assert 'profile-query' in registry.specs
    assert registry.specs['metric-query'].input_schema['additionalProperties'] is False
    registry.specs['metric-query']=registry.specs['metric-query'].model_copy(update={'dependencies':('comparison',)})
    with pytest.raises(ValueError,match='cycle'): registry.validate()
    with pytest.raises(ValueError,match='requires a dimension'):
        SkillExecutor(tools).run('drilldown',request()['query_input'])

def test_persistent_session_and_replay_without_repeat_execution(tools,tmp_path,monkeypatch):
    store=SessionStore(tmp_path/'sessions.sqlite')
    runtime=HarnessRuntime(tools,store=store)
    result=runtime.start(request())
    assert result['status']=='COMPLETE' and result['runtime']['queries_used']==1
    identifier=result['session_id']
    saved=store.get(identifier)
    # 模拟节点输出失败后恢复：保留Task和查询回执，丢弃旧进程plan_id。
    store.finish(identifier,'STOPPED',saved['state'],saved['elapsed'])
    replacement=AgentTools(tools.home)
    def forbidden(*args,**kwargs): raise AssertionError('Completed query must not be executed twice')
    monkeypatch.setattr(replacement,'execute',forbidden)
    resumed=HarnessRuntime(replacement,store=SessionStore(store.path)).resume(identifier)
    assert resumed['status']=='COMPLETE'
    assert resumed['result']['receipt_reused'] is True
    assert resumed['runtime']['queries_used']==1
    events=runtime.show(identifier)['events']
    assert any(event['kind']=='query-reused' for event in events)
    assert any(event['payload'].get('skill')=='metric-query' for event in events)

def test_resume_refuses_changed_binding(tools,tmp_path):
    runtime=HarnessRuntime(tools,store=SessionStore(tmp_path/'sessions.sqlite'))
    identifier=runtime.store.create(runtime.binding(),request())
    with runtime.store.connect() as db:
        binding=runtime.binding(); binding['release']='old-release'
        db.execute('UPDATE sessions SET binding=? WHERE id=?',(json.dumps(binding),identifier))
    with pytest.raises(ValueError,match='version changed'): runtime.resume(identifier)

def test_budget_cancellation_and_lease(tools,tmp_path):
    runtime=HarnessRuntime(tools,store=SessionStore(tmp_path/'sessions.sqlite'))
    identifier=runtime.store.create(runtime.binding(),request(),query_limit=1)
    runtime.cancel(identifier)
    stopped=runtime.resume(identifier)
    assert stopped['status']=='STOPPED' and 'cancelled' in stopped['error']
    assert runtime.store.get(identifier)['queries']==0
    busy=runtime.store.create(runtime.binding(),request())
    runtime.store.acquire(busy)
    with pytest.raises(ValueError,match='already running'): runtime.resume(busy)
    limited=runtime.store.create(runtime.binding(),request(),query_limit=1)
    runtime.store.reserve_query(limited)
    with pytest.raises(ValueError,match='budget'): runtime.store.reserve_query(limited)

def test_clarification_reply_creates_child_and_preserves_question(tools,tmp_path):
    runtime=HarnessRuntime(tools,store=SessionStore(tmp_path/'sessions.sqlite'))
    first=runtime.start({'question':'2026年9月销售额是多少'})
    assert first['status']=='CLARIFY'
    second=runtime.followup(first['session_id'],'下单金额')
    assert second['status']=='COMPLETE'
    assert second['query']['metric_id']=='booked_amount@1'
    assert runtime.store.get(second['session_id'])['request']['parent_session']==first['session_id']
    assert runtime.store.get(first['session_id'])['status']=='CLARIFY'

def test_session_timeout_stops_before_query(tools,tmp_path,monkeypatch):
    runtime=HarnessRuntime(tools,store=SessionStore(tmp_path/'sessions.sqlite'))
    identifier=runtime.store.create(runtime.binding(),request(),seconds_limit=1)
    with runtime.store.connect() as db: db.execute('UPDATE sessions SET elapsed=2 WHERE id=?',(identifier,))
    result=runtime.resume(identifier)
    assert result['status']=='STOPPED' and 'deadline' in result['error']
    assert runtime.store.get(identifier)['queries']==0

def test_continuation_keeps_window_metric_and_filters(tools,tmp_path):
    runtime=HarnessRuntime(tools,store=SessionStore(tmp_path/'sessions.sqlite'))
    first=runtime.start({'query_input':{**request()['query_input'],'filters':{'country':'United States'}}})
    second=runtime.start({'question':'按渠道','context_session':first['session_id']})
    assert second['status']=='COMPLETE'
    assert second['query']['filters']=={'country':'United States'}
    assert second['query']['group_by']==['traffic_source']
    assert second['query']['start']=='2026-09-01'

def test_full_ratio_workflow_quality_and_dimension_contributions(tools,tmp_path):
    runtime=HarnessRuntime(tools,store=SessionStore(tmp_path/'sessions.sqlite'))
    current={'metric_id':'complete_order_rate@1','start':'2026-09-01','end':'2026-09-08','filters':{'gender':'M'}}
    baseline={**current,'start':'2026-08-01','end':'2026-08-08'}
    result=runtime.start({'task_input':{'kind':'diagnose','query':current,'baseline':baseline,'expected_direction':'unknown'}})
    assert result['status']=='INSUFFICIENT_EVIDENCE',result
    report=result['result']
    assert report['queries_used']==14 and result['runtime']['queries_used']<=14
    assert report['quality_check']['quality']['status']=='PASS'
    groups=[d for d in report['decompositions'] if d['kind']=='weighted-ratio-group-contribution']
    assert len(groups)==2 and all(abs(d['residual'])<1e-9 for d in groups)
    assert all(abs(sum(g['contribution'] for g in d['groups'])-report['change']['delta'])<1e-9 for d in groups)
    assert 'ratio_dimension_drilldown_not_implemented' not in report['unresolved']
    assert report['causal_claim'] is False
    skill_ids={e['payload'].get('skill') for e in runtime.show(result['session_id'])['events']}
    assert {'comparison','drilldown','quality-check','evidence-report','anomaly-analysis'}<=skill_ids

@pytest.mark.parametrize('cancel',[True,False])
def test_running_query_child_is_terminated(tools,monkeypatch,cancel):
    import sys
    import local_agent.service as service
    real_popen=subprocess.Popen
    processes=[]
    def sleeper(command,**kwargs):
        child=real_popen([sys.executable,'-c','import time; time.sleep(30)'],**kwargs)
        processes.append(child)
        return child
    monkeypatch.setattr(service.subprocess,'Popen',sleeper)
    calls=0
    def check():
        nonlocal calls
        calls+=1
        if cancel and calls>=2: raise ValueError('Session cancelled')
    plan=tools.plan(Query.model_validate(request()['query_input']))
    with pytest.raises((ValueError,TimeoutError),match='cancelled|deadline'):
        tools.execute(plan['plan_id'],plan['approval_hash'],timeout_seconds=.4,cancel_check=check)
    assert processes and processes[0].poll() is not None
