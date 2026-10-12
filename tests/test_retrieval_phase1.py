"""检索是否进入决策、定义是否权威、版本与权限是否继续生效；不做模型准确率评测。"""
import json
import pytest
from test_multi_plan_fact import small_service
from local_agent.retrieval_service import RetrievalService, QueryContextBroker
from local_agent.semantic_context import SemanticContextResolver
from local_agent.agent_loop import AgentLoop
from local_agent.agent_tools import AgentTools as Adapter, ResolveInput
from local_agent.semantic import Query


def test_index_reused_and_exact_ids_recognized(small_service):
    tools, _ = small_service
    service = RetrievalService(tools)
    first = service.retrieve('order_count@1')
    second = service.retrieve('商品件数')
    assert first['candidates'][0]['metric_id'] == 'order_count@1'
    assert first['candidates'][0]['match'] == 'exact'
    assert first['index_version'] == second['index_version']
    assert service.lexical.index_builds == 1
    assert second['trace']['scores_are_probabilities'] is False


def test_ambiguous_terms_are_explicit_not_auto_selected(small_service):
    tools, _ = small_service
    context = QueryContextBroker(tools).prepare('2026年9月销售额是多少')
    assert context['discovery']['status'] == 'CLARIFY'
    assert context['unresolved'] == ['ambiguous_business_term:销售额']
    assert set(context['semantic_context']['metrics']) >= {'booked_amount@1', 'complete_item_amount@1'}


def test_cross_fact_components_and_dimensions_from_registry(small_service):
    tools, _ = small_service
    resolver = SemanticContextResolver(tools)
    context = resolver.resolve(['items_per_order@1'], requested_dimensions=['country', 'category'])
    assert context['components']['items_per_order@1'] == ['item_count@1', 'order_count@1']
    assert context['relationships'][0]['kind'] == 'aggregate_then_join'
    assert context['relationships'][0]['raw_join_allowed'] is False
    assert context['unresolved'] == ['incompatible_dimension:category']
    assert not context['dimension_values']
    values = resolver.resolve(['order_count@1'], value_dimensions=['country'])
    assert 'China' in values['dimension_values']['country']['order_count@1']['values']


def test_stale_discovery_and_model_formula_are_rejected(small_service):
    from pydantic import ValidationError
    tools, _ = small_service
    with pytest.raises(ValueError, match='Stale'):
        SemanticContextResolver(tools).resolve(['order_count@1'], expected_asset_version='old-index')
    with pytest.raises(ValidationError):
        ResolveInput.model_validate({'metric_ids': ['order_count@1'], 'formula': 'SUM(anything)'})
    # 外部文本即使带假公式，也只作为发现候选；resolve完全不接收该公式。
    discovery = RetrievalService(tools).retrieve('下单金额')
    discovery['hits'][0]['formula'] = 'sum(incorrect_column)'
    context = SemanticContextResolver(tools).resolve(['booked_amount@1'])
    assert context['metrics']['booked_amount@1']['column'] == 'booked_order_amount'


def test_authorization_before_candidates_and_structured_context(small_service):
    from local_agent.service import AgentTools
    from local_agent.access import AccessDenied
    tools, _ = small_service
    token = tools.access.issue('us-analyst')
    restricted = AgentTools(tools.home, token=token)
    result = RetrievalService(restricted).retrieve('订单完成率')
    assert all(c['metric_id'] != 'complete_order_rate@1' for c in result['candidates'])
    with pytest.raises(AccessDenied):
        SemanticContextResolver(restricted).resolve(['complete_order_rate@1'])
    context = SemanticContextResolver(restricted).resolve(['order_count@1'])
    assert 'gender' not in context['common_dimensions']
    fields = context['metadata']['commerce.fct_orders']['schema']
    assert all(f['name'] != 'user_id' for f in fields)


def test_first_agent_decision_consumes_non_alias_retrieval(small_service):
    tools, _ = small_service
    def model(context, remaining):
        if not context['observations']:
            retrieved = context['query_context']
            assert retrieved['discovery']['candidates'][0]['match'] == 'lexical'
            # 根据检索到的权威单位选择，而非在脚本里写死指标ID。
            matches = [m for m, definition in retrieved['semantic_context']['metrics'].items()
                       if definition['unit'] == 'source_amount/order']
            assert len(matches) == 1
            return {'action': 'tool', 'tool': 'run_query', 'arguments': {
                'metric_id': matches[0], 'start': '2026-09-01', 'end': '2026-10-01'}}, {'live': False}
        return {'action': 'finish', 'message': '已按检索到的权威口径计算平均下单金额',
                'evidence_ids': ['e1']}, {'live': False}
    loop = AgentLoop(tools, model)
    result = loop.start('2026年9月平均每张订单的金额是多少')
    assert result['status'] == 'COMPLETE', result.get('error')
    assert result['answer']['evidence'][0]['result']['rows'] == [[103.75]]
    assert result['runtime']['queries_used'] == 1
    assert any(e['kind'] == 'retrieval-bootstrap' for e in loop.show(result['session_id'])['events'])


def test_contexts_cannot_cross_identity_or_metric_scope(small_service):
    tools, _ = small_service
    resolver = SemanticContextResolver(tools)
    context = resolver.resolve(['order_count@1'])
    with pytest.raises(ValueError, match='scope changed'):
        resolver.validate(context, ['item_count@1'])
    context['binding']['subject'] = 'model-selected-user'
    with pytest.raises(ValueError, match='binding'):
        resolver.validate(context, ['order_count@1'])


def test_every_service_plan_has_semantic_binding(small_service):
    tools, _ = small_service
    plan = tools.plan(Query(metric_id='order_count@1', start='2026-09-01', end='2026-10-01'))
    assert plan['semantic_resolution']['binding']['registry_version'] == tools.registry.version
    assert tools.execute(plan['plan_id'], plan['approval_hash'])['semantic_resolution'] == plan['semantic_resolution']


def test_model_cannot_execute_ambiguous_top_hit(small_service):
    tools, _ = small_service
    result = AgentLoop(tools, lambda c, r: ({'action': 'tool', 'tool': 'run_query', 'arguments': {
        'metric_id': 'booked_amount@1', 'start': '2026-09-01', 'end': '2026-10-01'}}, {})).start('2026年9月销售额是多少')
    assert result['status'] == 'CLARIFY' and result['runtime']['queries_used'] == 0


def test_structured_tool_resolves_only_requested_value_dimension(small_service):
    tools, _ = small_service
    class Proxy:
        def __getattr__(self, name): return getattr(tools, name)
        def check_execution(self): return 120
    adapter = Adapter(Proxy())
    result = adapter.call('resolve_semantics', {'metric_ids': ['order_count@1'], 'value_dimensions': ['country']})
    assert set(result['dimension_values']) == {'country'}


def test_semantic_context_formula_tampering_rejected(small_service):
    tools, _ = small_service
    resolver = SemanticContextResolver(tools)
    context = resolver.resolve(['booked_amount@1'])
    context['metrics']['booked_amount@1']['column'] = 'incorrect_column'
    with pytest.raises(ValueError, match='tampered'):
        resolver.validate(context, ['booked_amount@1'])


def test_asset_update_rebuilds_cache_and_invalidates_discovery(small_service, tmp_path, monkeypatch):
    import shutil
    import local_agent.retrieval as lexical_module
    import local_agent.semantic_context as context_module
    from local_agent.semantic import ROOT
    tools, _ = small_service
    assets = tmp_path/'assets'; (assets/'knowledge').mkdir(parents=True)
    refs = assets/'skills/warehouse-anomaly-attribution/references'; refs.mkdir(parents=True)
    shutil.copy2(ROOT/'knowledge/business.json', assets/'knowledge/business.json')
    for source in (ROOT/'skills/warehouse-anomaly-attribution/references').glob('*.md'):
        shutil.copy2(source, refs/source.name)
    monkeypatch.setattr(lexical_module, 'ROOT', assets)
    monkeypatch.setattr(context_module, 'ROOT', assets)
    service = RetrievalService(tools)
    old = service.retrieve('订单数')
    path = assets/'knowledge/business.json'; business = json.loads(path.read_text(encoding='utf-8'))
    business['aliases']['order_count@1'].append('测试业务交易笔数')
    path.write_text(json.dumps(business, ensure_ascii=False), encoding='utf-8')
    new = service.retrieve('测试业务交易笔数')
    assert new['candidates'][0]['match'] == 'exact'
    assert new['index_version'] != old['index_version'] and service.lexical.index_builds == 2
    with pytest.raises(ValueError, match='Stale'):
        SemanticContextResolver(tools).resolve(['order_count@1'], expected_asset_version=old['index_version'])


def test_explicit_id_cannot_be_changed_by_model(small_service):
    tools, _ = small_service
    wrong = Query(metric_id='booked_amount@1', start='2026-09-01', end='2026-10-01')
    with pytest.raises(ValueError, match='明确指标'):
        AgentLoop.guard_request('2026年9月order_count@1', 'run_query', wrong, tools)


def test_task_model_receives_same_typed_context(small_service, monkeypatch):
    import httpx
    from local_agent.tasks import TaskInterpreter
    tools, _ = small_service
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    for name, value in [('LLM_BASE_URL','https://local.invalid/v1'),('LLM_API_KEY','test-only'),('LLM_MODEL','mock')]:
        monkeypatch.setenv(name, value)
    def respond(request):
        instruction = json.loads(json.loads(request.content)['messages'][0]['content'])
        assert instruction['query_context']['semantic_context']['metrics']['order_count@1']['kind'] == 'count'
        assert not instruction['authoritative_contexts'][0]['dimension_values']
        body = {'kind':'query','query':{'metric_id':'order_count@1','start':'2026-09-01','end':'2026-10-01'}}
        return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps(body)}}]})
    parser = TaskInterpreter(tools, mode='llm', transport=httpx.MockTransport(respond))
    assert parser.parse('查询2026年9月订单数').query.metric_id == 'order_count@1'
