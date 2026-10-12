"""自主路径、协议与共享查询预算；所有模型响应均为模拟。"""
import json
import httpx
import pytest
from local_agent.agent_loop import AgentLoop, ModelDecision
from local_agent.agent_tools import AgentTools as ToolAdapter
from local_agent.semantic import ROOT
from local_agent.service import AgentTools


@pytest.fixture(scope='module')
def tools(tmp_path_factory):
    target = AgentTools(tmp_path_factory.mktemp('agent-loop'))
    target.publish(ROOT/'data/thelook.duckdb', ROOT/'warehouse-commerce/target/manifest.json',
                   ROOT/'docs/thelook-dbt-run-results.json')
    return target


def scripted(*decisions):
    iterator = iter(decisions)
    def model(context, remaining):
        assert remaining > 0
        return next(iterator), {'live': False}
    return model


QUERY = {'metric_id': 'order_count@1', 'start': '2026-09-01', 'end': '2026-10-01'}


def test_direct_query_without_retrieval_and_persistent_evidence(tools):
    def model(context, remaining):
        if not context['observations']:
            return {'action': 'tool', 'tool': 'run_query', 'arguments': QUERY}, {}
        assert context['observations'][0]['result']['rows']
        return {'action': 'finish', 'message': '查询完成', 'evidence_ids': ['e1']}, {}
    loop = AgentLoop(tools, model)
    result = loop.start('查询订单数')
    assert result['status'] == 'COMPLETE'
    assert result['runtime']['queries_used'] == 1
    assert [o['tool'] for o in result['observations']] == ['run_query']
    assert loop.show(result['session_id'])['queries_used'] == 1


def test_search_observation_drives_next_action(tools):
    def model(context, remaining):
        if not context['observations']:
            return {'action': 'tool', 'tool': 'search_business',
                    'arguments': {'question': '销售额'}}, {}
        assert context['observations'][0]['result']['hits']
        return {'action': 'clarify', 'message': '请选择下单金额或已完成商品金额'}, {}
    result = AgentLoop(tools, model).start('销售额多少')
    assert result['status'] == 'CLARIFY'
    assert result['runtime']['queries_used'] == 0


def test_invalid_tool_can_be_corrected(tools):
    result = AgentLoop(tools, scripted(
        {'action': 'tool', 'tool': 'execute_sql', 'arguments': {}},
        {'action': 'clarify', 'message': '请明确指标'})).start('查询')
    assert result['status'] == 'CLARIFY'
    assert result['observations'][0]['status'] == 'ERROR'


def test_duplicate_calls_do_not_execute_twice(tools):
    call = {'action': 'tool', 'tool': 'run_query', 'arguments': QUERY}
    result = AgentLoop(tools, scripted(call, call,
        {'action': 'finish', 'message': '完成', 'evidence_ids': ['e1']})).start('订单数')
    assert result['status'] == 'COMPLETE'
    assert result['runtime']['queries_used'] == 1
    assert result['observations'][1]['status'] == 'ERROR'


def test_workflow_queries_share_outer_budget(tools):
    result = AgentLoop(tools, scripted({'action': 'tool', 'tool': 'run_comparison',
        'arguments': {'current': QUERY, 'baseline': {**QUERY,
            'start': '2026-08-02', 'end': '2026-09-01'}}})).start('比较订单数', query_limit=1)
    assert result['status'] == 'STOPPED'
    assert result['runtime']['queries_used'] == 1
    assert 'budget' in result['error']


@pytest.mark.parametrize('decision,limits,match', [
    ({'action': 'finish', 'message': '虚构结果', 'evidence_ids': ['missing']}, {}, 'evidence'),
    ({'action': 'tool', 'tool': 'search_business', 'arguments': {'question': '订单'}},
     {'max_searches': 0}, 'Search budget'),
    ({'action': 'tool', 'tool': 'describe_metric', 'arguments': {'metric_id': 'order_count@1'}},
     {'max_steps': 1}, 'decision budget')])
def test_bounded_termination(tools, decision, limits, match):
    result = AgentLoop(tools, scripted(decision)).start('订单', **limits)
    assert result['status'] == 'STOPPED' and match in result['error']


def test_cancellation_stops_before_tool(tools):
    loop = AgentLoop(tools)
    def model(context, remaining):
        with loop.store.connect() as db:
            db.execute('UPDATE sessions SET cancelled=1 WHERE status=?', ('RUNNING',))
        return {'action': 'tool', 'tool': 'run_query', 'arguments': QUERY}, {}
    loop.decision_model = model
    result = loop.start('订单数')
    assert result['status'] == 'STOPPED' and 'cancelled' in result['error']
    assert result['runtime']['queries_used'] == 0


def test_responses_protocol(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setenv('OPENAI_MODEL', 'test-model')
    def response(request):
        sent = json.loads(request.content)
        assert sent['store'] is False
        assert sent['text']['format']['strict'] is True
        body = {'action': 'tool', 'tool': 'search_business',
                'arguments_json': '{"question":"订单"}', 'message': '', 'evidence_ids': []}
        return httpx.Response(200, json={'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(body)}]}]})
    decision, evidence = ModelDecision(httpx.MockTransport(response))({'question': '订单'}, 5)
    assert decision['arguments'] == {'question': '订单'} and evidence['live'] is False


def test_extra_identity_and_sql_are_rejected():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ToolAdapter.inputs['run_query'].model_validate({**QUERY, 'principal': 'admin', 'sql': 'SELECT 1'})


def test_large_observation_is_explicitly_truncated():
    observation = {'id': 'e1', 'status': 'OK', 'tool': 'run_query',
                   'result': {'rows': [['x'*1000] for _ in range(100)], 'columns': ['value']}}
    preview = AgentLoop.model_observation(observation)
    assert preview['context_truncated'] is True
    assert len(json.dumps(preview)) < 12000
    assert len(observation['result']['rows']) == 100


def test_permission_denial_is_terminal(tools):
    from local_agent.access import AccessDenied
    loop = AgentLoop(tools)
    original = tools.access.role
    def model(context, remaining):
        def denied():
            raise AccessDenied('Access denied')
        tools.access.role = denied
        return {'action': 'tool', 'tool': 'search_business', 'arguments': {'question': '订单'}}, {}
    loop.decision_model = model
    try:
        result = loop.start('订单')
    finally:
        tools.access.role = original
    assert result['status'] == 'STOPPED' and 'Access denied' in result['error']
    assert result['observations'] == []


@pytest.mark.parametrize('question', [
    '查询美国用户订单数',
    '查询订单数 UTC闭开[2026-08-01,2026-09-01)',
    '金融支付成功率是多少'])
def test_user_constraints_cannot_be_silently_changed(tools, question):
    result = AgentLoop(tools, scripted({'action': 'tool', 'tool': 'run_query',
                                      'arguments': QUERY})).start(question)
    assert result['status'] == 'CLARIFY'
    assert result['runtime']['queries_used'] == 0
