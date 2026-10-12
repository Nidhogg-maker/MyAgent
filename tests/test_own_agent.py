"""自主实现验收：受控编译负例 + 官方数据独立对账 + 真实 MCP 进程。"""
import asyncio
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from importlib.util import find_spec
import duckdb
import pytest
from pydantic import ValidationError
from local_agent.semantic import ROOT, Query, SemanticRegistry, SQLCompiler
from local_agent.service import AgentTools
from local_agent.harness import build_agent

@pytest.fixture(scope='module')
def tools(tmp_path_factory):
    if not (ROOT / 'data/thelook.duckdb').exists():
        pytest.skip('Official TheLook local snapshot unavailable')
    service = AgentTools(tmp_path_factory.mktemp('own-agent'))
    service.publish(ROOT / 'data/thelook.duckdb', ROOT / 'warehouse-commerce/target/manifest.json', ROOT / 'docs/thelook-dbt-run-results.json')
    return service

@pytest.mark.parametrize('payload', [
    {'start':'2026-09-01','end':'2026-11-01'},
    {'start':'2026-09-01','end':'2026-09-01'},
    {'start':'2026-09-01','end':'2026-09-02','principal':'admin'},
    {'start':'2026-09-01','end':'2026-09-02','group_by':['country','country']},
])
def test_invalid_query_contract(payload):
    with pytest.raises(ValidationError):
        Query.model_validate({'metric_id':'order_count@1', **payload})

def test_grain_rejects_order_category():
    with pytest.raises(ValueError, match='Illegal dimension'):
        SQLCompiler(SemanticRegistry()).compile(Query(metric_id='order_count@1', start='2026-09-01', end='2026-09-02', group_by=('category',)))

@pytest.mark.parametrize('metric,baseline', [
    ('order_count@1', 'SELECT count(*) FROM raw.orders WHERE {window}'),
    ('booked_amount@1', 'SELECT sum(cast(i.sale_price as decimal(18,4))) FROM raw.orders o JOIN raw.order_items i USING(order_id) WHERE {window_o}'),
    ('average_order_value@1', 'SELECT sum(amount)::double/count(*) FROM (SELECT o.order_id,sum(cast(i.sale_price as decimal(18,4))) amount FROM raw.orders o JOIN raw.order_items i USING(order_id) WHERE {window_o} GROUP BY o.order_id)'),
    ('buyer_count@1', 'SELECT count(DISTINCT user_id) FROM raw.orders WHERE {window}'),
    ('item_count@1', 'SELECT count(*) FROM raw.order_items i JOIN raw.orders o USING(order_id) WHERE {window_o}'),
    ('complete_item_amount@1', "SELECT sum(case when i.status='Complete' then cast(i.sale_price as decimal(18,4)) else 0 end) FROM raw.order_items i JOIN raw.orders o USING(order_id) WHERE {window_o}"),
])
def test_official_data_six_metrics_independent_raw_baseline(tools, metric, baseline):
    """基准从原始表独立计算，避免用编译器自己的 SQL 自我证明。"""
    query = Query(metric_id=metric, start='2026-09-01', end='2026-10-01')
    result = build_agent(tools).invoke({'query_input':query.model_dump(mode='json')})
    assert result['status'] == 'COMPLETE'
    window = "created_at >= TIMESTAMPTZ '2026-09-01 00:00:00+00' AND created_at < TIMESTAMPTZ '2026-10-01 00:00:00+00'"
    window_o = window.replace('created_at', 'o.created_at')
    with duckdb.connect(str(ROOT / 'data/thelook.duckdb'), read_only=True) as db:
        expected = db.execute(baseline.format(window=window, window_o=window_o)).fetchone()[0]
    assert float(result['result']['rows'][0][0]) == pytest.approx(float(expected))
    assert result['trace'] == ['intent','metadata','quality_and_plan','execute','answer']

def test_literal_injection_cannot_change_sql_structure(tools):
    query = Query(metric_id='order_count@1', start='2026-09-01', end='2026-09-02', filters={'country':"x' OR 1=1; DROP TABLE raw.orders; --"})
    plan = tools.plan(query)
    assert tools.execute(plan['plan_id'], plan['approval_hash'])['rows'] == [[0]]

def test_plan_mutation_stops_execution(tools):
    plan = tools.plan(Query(metric_id='order_count@1', start='2026-09-01', end='2026-09-02'))
    tools.plans[plan['plan_id']]['sql'] = 'SELECT * FROM raw.users'
    with pytest.raises(ValueError, match='tampered'):
        tools.execute(plan['plan_id'], plan['approval_hash'])

def test_illegal_dimension_stops_before_execution(tools):
    result = build_agent(tools).invoke({'query_input':{'metric_id':'order_count@1','start':'2026-09-01','end':'2026-09-02','group_by':['category']}})
    assert result['status'] in ('STOPPED','CLARIFY')
    assert 'execute' not in result['trace']

def test_future_window_stops(tools):
    today = dt.datetime.now(dt.timezone.utc).date()
    result = build_agent(tools).invoke({'query_input':{'metric_id':'order_count@1','start':str(today),'end':str(today+dt.timedelta(days=1))}})
    assert result['status'] == 'CLARIFY'
    assert 'execute' not in result['trace']

def test_zero_denominator_is_null(tools):
    plan = tools.plan(Query(metric_id='average_order_value@1', start='2010-01-01', end='2010-01-02'))
    assert tools.execute(plan['plan_id'], plan['approval_hash'])['rows'] == [[None]]

def test_table_and_field_lineage_are_real_artifact_dependencies(tools):
    graph = tools.catalog.lineage('commerce.fct_orders')
    assert any(edge['to'].endswith('raw.orders') for edge in graph['edges'])
    fields = tools.catalog.field_lineage('commerce.fct_orders','booked_order_amount')
    assert any(edge['to'].endswith('raw.order_items:sale_price') for edge in fields['edges'])
    assert fields['complete'] is False
    assert tools.catalog.lineage('commerce.fct_orders', max_depth=1)['truncated'] is True

def test_comparison_does_not_claim_cause(tools):
    result = tools.compare(Query(metric_id='order_count@1',start='2026-08-01',end='2026-08-08'), Query(metric_id='order_count@1',start='2026-09-01',end='2026-09-08'))
    assert result['causal_claim'] is False and len(result['evidence']) == 2
    with pytest.raises(ValueError, match='duration'):
        tools.compare(Query(metric_id='order_count@1',start='2026-08-01',end='2026-08-08'), Query(metric_id='order_count@1',start='2026-09-01',end='2026-09-09'))

def test_missing_model_is_explicit(tools, monkeypatch):
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    from local_agent.tasks import TaskInterpreter
    result = build_agent(tools,TaskInterpreter(tools,mode='llm')).invoke({'question':'销售额是多少？'})
    assert result['status'] == 'STOPPED' and 'WAITING_FOR_MODEL' in result['error']

def test_upstream_imports_are_not_required():
    assert all(find_spec(name) is None for name in ('metricflow', 'datahub', 'wren'))
    code = '''
import builtins
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.split('.')[0] in {'metricflow','metricflow_semantics','metricflow_semantic_interfaces','datahub','wren'}:
        raise ImportError('Upstream runtime forbidden: '+name)
    return original(name,*args,**kwargs)
builtins.__import__=guarded
from local_agent.service import AgentTools
from local_agent.harness import build_agent
from local_agent.semantic import Query
print('standalone imports passed')
'''
    subprocess.run([sys.executable,'-c',code], check=True, capture_output=True, text=True)

def test_expired_quality_stops(tools):
    active = tools.home / 'active.json'
    original = active.read_text(encoding='utf-8')
    changed = json.loads(original)
    changed['quality_generated_at'] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
    try:
        active.write_text(json.dumps(changed), encoding='utf-8')
        with pytest.raises(ValueError, match='expired'):
            tools.release()
    finally:
        active.write_text(original, encoding='utf-8')

def test_on_disk_contract_change_requires_republish(tools, tmp_path):
    contract = tmp_path / 'commerce.json'
    contract.write_bytes(tools.registry.path.read_bytes())
    previous_registry = tools.registry
    tools.registry = SemanticRegistry(contract)
    try:
        contract.write_text(contract.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        with pytest.raises(ValueError, match='contract changed'):
            tools.release()
    finally:
        tools.registry = previous_registry

def test_real_own_mcp_plan_and_execute(tools):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def check():
        params = StdioServerParameters(command=sys.executable, args=['-m','local_agent.mcp_server'], env={**os.environ,'OWN_AGENT_HOME':str(tools.home)})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                listed = await client.list_tools()
                names={tool.name for tool in listed.tools}
                assert {'get_user_profile','get_product_profile','get_user_product_features',
                        'get_session_profile','describe_data_product'} <= names
                assert len(listed.tools) == 13
                planned = await client.call_tool('plan_query', {'query':{'metric_id':'order_count@1','start':'2026-09-01','end':'2026-09-02'}})
                assert not planned.isError
                plan = json.loads(planned.content[0].text)
                executed = await client.call_tool('execute_query', {'plan_id':plan['plan_id'],'approval_hash':plan['approval_hash']})
                assert not executed.isError
                result = json.loads(executed.content[0].text)
                assert result['metric_id'] == 'order_count@1' and result['rows'][0][0] > 0
                searched=await client.call_tool('search_business',{'question':'下单金额'})
                assert not searched.isError and json.loads(searched.content[0].text)['hits'][0]['metric_id']=='booked_amount@1'
                diagnosed=await client.call_tool('run_diagnosis',{'task':json.loads((ROOT/'config/diagnosis.example.json').read_text(encoding='utf-8'))})
                assert not diagnosed.isError
                diagnostic=json.loads(diagnosed.content[0].text)
                assert diagnostic['causal_claim'] is False and diagnostic['queries_used']==8
    asyncio.run(check())
