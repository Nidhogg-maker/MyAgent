"""使用可控小事实建立反例：先聚合能避免 Fanout，候选计划不能替换业务目标。"""
import datetime as dt
import json
import duckdb
import pytest
from local_agent.semantic import ROOT, SemanticRegistry, SQLCompiler, file_hash
from local_agent.multi_fact import MultiFactQuery, MultiFactCompiler
from local_agent.service import AgentTools
from local_agent.agent_loop import AgentLoop


BASE = {'metric_ids': ['order_count@1', 'item_count@1'], 'start': '2026-09-01',
        'end': '2026-10-01', 'population': 'union', 'group_by': ['country']}


@pytest.fixture
def small_service(tmp_path):
    # 测试专用发布 fixture，绝不是生产质量凭据。
    service = AgentTools(tmp_path/'agent')
    database = tmp_path/'warehouse.duckdb'
    with duckdb.connect(str(database)) as db:
        db.execute('CREATE SCHEMA commerce')
        db.execute('''CREATE TABLE commerce.fct_orders(order_id INT,user_id INT,order_date DATE,
            country VARCHAR,booked_order_amount DECIMAL(18,4),traffic_source VARCHAR)''')
        db.execute("""INSERT INTO commerce.fct_orders VALUES
            (1,1,'2026-09-10','United States',100,'Search'),
            (2,1,'2026-09-10','United States',200,'Search'),
            (3,2,'2026-09-11','China',90,'Email'),
            (4,3,'2026-09-12',NULL,25,'Search')""")
        db.execute('''CREATE TABLE commerce.fct_order_items(order_item_id INT,order_id INT,
            user_id INT,order_date DATE,country VARCHAR,booked_item_amount DECIMAL(18,4),
            traffic_source VARCHAR)''')
        db.execute("""INSERT INTO commerce.fct_order_items VALUES
            (11,1,1,'2026-09-10','United States',50,'Search'),
            (12,1,1,'2026-09-10','United States',50,'Search'),
            (13,2,1,'2026-09-10','United States',200,'Search'),
            (14,4,3,'2026-09-12',NULL,12.5,'Search'),
            (15,4,3,'2026-09-12',NULL,12.5,'Search'),
            (16,99,4,'2026-09-13','United Kingdom',10,'Email')""")
    manifest = tmp_path/'manifest.json'; manifest.write_text('{}', encoding='utf-8')
    service.catalog.ingest(database, manifest, {'verified_business_owner': False})
    release = {'database': str(database), 'database_sha256': file_hash(database),
        'registry_sha256': service.registry.version, 'catalog_sha256': file_hash(service.catalog.path),
        'quality_generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'release_id': 'fixture-only', 'dbt_tests_passed': 0, 'quality_scope': 'fixture-only',
        'temporal': {}, 'provenance': 'test-fixture'}
    (service.home/'active.json').write_text(json.dumps(release), encoding='utf-8')
    return service, database


def execute(service, **changes):
    q = MultiFactQuery.model_validate({**BASE, **changes})
    plan = service.plan(q)
    return service.execute(plan['plan_id'], plan['approval_hash'])


def test_different_grains_do_not_multiply_order_amount(small_service):
    service, path = small_service
    result = execute(service, metric_ids=['booked_amount@1', 'item_count@1'])
    groups = {r[0]: r[1:] for r in result['rows']}
    assert float(groups['United States'][0]) == 300 and groups['United States'][1] == 3
    with duckdb.connect(str(path), read_only=True) as db:
        naive = db.execute("""SELECT sum(o.booked_order_amount) FROM commerce.fct_orders o
            JOIN commerce.fct_order_items i USING(order_id) WHERE o.country='United States'""").fetchone()[0]
    assert float(naive) == 400


def test_population_null_keys_and_registered_ratio(small_service):
    service, _ = small_service
    result = execute(service, ratio_ids=['items_per_order@1'])
    groups = {r[0]: r[1:] for r in result['rows']}
    assert groups['United States'] == [2, 3, 1.5]
    assert groups[None] == [1, 2, 2.0]  # NULL 安全匹配，不能产生两个 NULL 组。
    assert groups['China'] == [1, None, None]
    assert groups['United Kingdom'] == [None, 1, None]
    inner = execute(service, population='intersection')
    assert {r[0] for r in inner['rows']} == {'United States', None}


def test_no_branch_limit_and_distinct_recomputed(small_service):
    service, _ = small_service
    result = execute(service, metric_ids=['buyer_count@1', 'item_count@1'], group_by=[])
    assert result['rows'] == [[3, 6]]  # buyer_count 在原事实重算，不累加日 UV。
    limited = execute(service, limit=2)
    assert [r[0] for r in limited['rows']] == ['China', 'United Kingdom']
    assert limited['result_may_be_truncated']


def test_multi_fact_alias_unknown_filter_and_absent_branch(small_service):
    service, _ = small_service
    result = execute(service, filters={'country': '美国'})
    assert result['rows'] == [['United States', 2, 3]]
    result = execute(service, filters={'country': 'China'})
    assert result['rows'] == [['China', 1, None]]
    with pytest.raises(ValueError, match='CLARIFY'):
        execute(service, filters={'country': 'Atlantis'})


@pytest.mark.parametrize('change,match', [
    ({'group_by': ['category']}, 'common dimension'),
    ({'filters': {'item_status': 'Complete'}}, 'common dimension'),
    ({'ratio_ids': ['payment_rate@1']}, 'registered'),
    ({'metric_ids': ['order_count@1', 'booked_amount@1']}, 'different facts')])
def test_unsafe_grain_and_invented_ratios_rejected(change, match):
    with pytest.raises(ValueError, match=match):
        MultiFactCompiler(SemanticRegistry()).compile(MultiFactQuery.model_validate({**BASE, **change}))


def test_incompatible_time_basis_rejected():
    registry = SemanticRegistry()
    registry.contract['multi_fact']['time_basis']['items'] = 'item_created_at'
    with pytest.raises(ValueError, match='time semantics'):
        MultiFactCompiler(registry).compile(MultiFactQuery.model_validate(BASE))


def test_tampered_plan_and_forced_row_scope(small_service):
    service, _ = small_service
    token = service.access.issue('us-analyst')
    restricted = AgentTools(service.home, token=token)
    plan = restricted.plan(MultiFactQuery.model_validate(BASE))
    assert plan['query']['filters'] == {'country': 'United States'}
    assert plan['sql'].count("country = 'United States'") == 2
    assert plan['sql'].count('HAVING COUNT(*) >= 5') == 2
    restricted.plans[plan['plan_id']]['sql'] += ' UNION SELECT 1'
    with pytest.raises(ValueError, match='tampered'):
        restricted.execute(plan['plan_id'], plan['approval_hash'])


def proposals():
    step = {'tool': 'run_multi_fact', 'arguments': {**BASE, 'ratio_ids': ['items_per_order@1']}}
    return {'candidates': [
        {'label': '直接受控查询', 'approach': '已明确口径，直接执行聚合后关联', 'steps': [step]},
        {'label': '先核对目录', 'approach': '先看事实上下文，再执行同一查询', 'steps': [
            {'tool': 'get_context', 'arguments': {'metric_id': 'order_count@1'}}, step]}]}


def test_model_selects_plan_and_observes_each_step(small_service):
    service, _ = small_service
    def model(context, remaining):
        observations = context['observations']
        if not observations:
            decision = {'tool': 'propose_plans', 'arguments': proposals()}
        elif len(observations) == 1:
            ids = observations[0]['result']['candidates']
            decision = {'tool': 'select_plan', 'arguments': {'plan_id': ids[1]['plan_id']}}
        elif len(observations) in (2, 3):
            plan = context['planning']['selected_plan_id']
            decision = {'tool': 'run_plan_step', 'arguments': {'plan_id': plan, 'step_index': len(observations)-2}}
        else:
            assert observations[-1]['result']['result']['rows']
            return {'action': 'finish', 'message': '已执行共同Grain查询；不确认因果。', 'evidence_ids': ['e4']}, {'live': False}
        return {'action': 'tool', **decision}, {'live': False}
    result = AgentLoop(service, model).start('按国家查询订单量与商品件数，保留所有组', multi_plan=True)
    assert result['status'] == 'COMPLETE', (result.get('error'), [(o['tool'],o.get('error'),list(o)) for o in result['observations']])
    assert result['runtime']['queries_used'] == 1
    assert result['planning']['candidates'][1]['status'] == 'COMPLETE'
    assert len(result['model_calls']) == 5


def test_candidate_cannot_change_objective_or_population(small_service):
    from local_agent.agent_tools import AgentTools as Adapter
    from local_agent.multi_plan import MultiPlanManager, Proposals
    service, _ = small_service
    manager = MultiPlanManager(Adapter(service), lambda n, d: None)
    # 深复制教学 fixture，独立改变第二候选。
    bad = json.loads(json.dumps(proposals()))
    bad['candidates'][1]['steps'][-1]['arguments']['population'] = 'intersection'
    with pytest.raises(ValueError, match='same objective'):
        manager.propose(Proposals.model_validate(bad))


def test_replan_supersedes_old_id_and_preserves_evidence(small_service):
    from local_agent.agent_tools import AgentTools as Adapter
    from local_agent.multi_plan import MultiPlanManager, Proposals, PlanSelection, StepRequest
    service, _ = small_service
    class Proxy:
        def __getattr__(self, name): return getattr(service, name)
        def check_execution(self): return 120
    adapter = Adapter(Proxy()); manager = MultiPlanManager(adapter, lambda n, d: None)
    manager.propose(Proposals.model_validate(proposals()))
    old = list(manager.candidates)[1]
    manager.select(PlanSelection(plan_id=old))
    manager.execute_step(StepRequest(plan_id=old, step_index=0))
    manager.propose(Proposals.model_validate(proposals()))
    assert manager.history[0]['next_step'] == 1
    with pytest.raises(ValueError, match='unknown'):
        manager.select(PlanSelection(plan_id=old))


def test_plan_mode_cannot_bypass_planner_or_finish_with_proposals(small_service):
    service, _ = small_service
    turns = iter([{'action': 'tool', 'tool': 'run_multi_fact', 'arguments': BASE},
                  {'action': 'clarify', 'message': '请明确计划'}])
    result = AgentLoop(service, lambda c, r: (next(turns), {})).start('查询', multi_plan=True)
    assert result['status'] == 'CLARIFY' and result['runtime']['queries_used'] == 0


def test_group_population_and_ratio_must_preserve_user_intent(small_service):
    from local_agent.multi_fact import MultiFactQuery
    service, _ = small_service
    query = MultiFactQuery.model_validate(BASE)
    with pytest.raises(ValueError, match='并集还是交集'):
        AgentLoop.guard_request('按国家查询订单量和商品件数', 'run_multi_fact', query, service)
    with pytest.raises(ValueError, match='注册组件'):
        AgentLoop.guard_request('每单商品件数，保留所有组', 'run_multi_fact', query, service)


def test_proposal_observation_does_not_mutate(small_service):
    from local_agent.agent_tools import AgentTools as Adapter
    from local_agent.multi_plan import MultiPlanManager, Proposals, PlanSelection
    service, _ = small_service
    manager = MultiPlanManager(Adapter(service), lambda n, d: None)
    observation = manager.propose(Proposals.model_validate(proposals()))
    manager.select(PlanSelection(plan_id=observation['candidates'][0]['plan_id']))
    assert observation['candidates'][0]['status'] == 'VALIDATED'


def test_multi_fact_reuses_authorized_receipt_and_honors_query_budget(small_service):
    from local_agent.runtime import RuntimeTools, SessionStore
    service, _ = small_service
    store = SessionStore(service.home/'test-sessions.sqlite')
    identifier = store.create({'release': 'fixture-only'}, {}, query_limit=1)
    proxy = RuntimeTools(service, store, identifier, lambda: 120)
    query = MultiFactQuery.model_validate(BASE)
    plan = proxy.plan(query); first = proxy.execute(plan['plan_id'], plan['approval_hash'])
    plan = proxy.plan(query); second = proxy.execute(plan['plan_id'], plan['approval_hash'])
    assert second['rows'] == first['rows'] and second['receipt_reused']
    assert store.get(identifier)['queries'] == 1
    plan = proxy.plan(query.model_copy(update={'group_by': ()}))
    with pytest.raises(ValueError, match='budget'):
        proxy.execute(plan['plan_id'], plan['approval_hash'])
