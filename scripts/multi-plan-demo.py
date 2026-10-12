"""模拟模型决策 + 真实本地 TheLook 查询；不调用收费模型，不覆盖默认 Agent 发布。"""
import json
from pathlib import Path
import duckdb
from local_agent.semantic import ROOT
from local_agent.service import AgentTools
from local_agent.agent_loop import AgentLoop


def main():
    service = AgentTools(ROOT/'data/multi-plan-demo')
    release = service.publish(ROOT/'data/thelook.duckdb', ROOT/'warehouse-commerce/target/manifest.json',
                              ROOT/'docs/thelook-dbt-run-results.json')
    query = json.loads((ROOT/'config/multi-fact-query.example.json').read_text(encoding='utf-8'))
    execution = {'tool': 'run_multi_fact', 'arguments': query}
    proposals = {'candidates': [
        {'label': '直接语义关联', 'approach': '已知目标与合法共同维度，直接执行受控多事实查询', 'steps': [execution]},
        {'label': '先核对事实上下文', 'approach': '先查看订单事实来源与质量，再执行相同口径查询', 'steps': [
            {'tool': 'get_context', 'arguments': {'metric_id': 'order_count@1'}}, execution]}]}
    def model(context, remaining):
        observed = context['observations']
        if not observed:
            decision = {'tool': 'propose_plans', 'arguments': proposals}
        elif len(observed) == 1:
            decision = {'tool': 'select_plan', 'arguments': {'plan_id': context['planning']['candidates'][1]['plan_id']}}
        elif len(observed) in (2, 3):
            decision = {'tool': 'run_plan_step', 'arguments': {
                'plan_id': context['planning']['selected_plan_id'], 'step_index': len(observed)-2}}
        else:
            return {'action': 'finish', 'message': '已分别聚合订单与商品事实后关联；返回观察数值，不确认因果。',
                    'evidence_ids': ['e4']}, {'live': False, 'provider': 'scripted-demo'}
        return {'action': 'tool', **decision}, {'live': False, 'provider': 'scripted-demo'}
    question = 'UTC闭开[2026-09-01,2026-10-01)按国家和渠道查询订单量、商品件数与每单商品件数，保留分组并集'
    result = AgentLoop(service, model).start(question, multi_plan=True)
    if result['status'] != 'COMPLETE':
        raise RuntimeError(result.get('error', result))
    evidence = result['observations'][-1]['result']['result']
    checks = []
    with duckdb.connect(release['database'], read_only=True) as db:
        # 独立从 raw 回算返回的每个组，避免只复用编译器表达式做 expected。
        for country, channel, orders, items, ratio in evidence['rows']:
            arguments = [query['start'], query['end'], country, channel]
            expected_orders = db.execute('''SELECT count(*) FROM raw.orders o LEFT JOIN raw.users u ON o.user_id=u.id
                WHERE cast(timezone('UTC',o.created_at) AS DATE)>=? AND cast(timezone('UTC',o.created_at) AS DATE)<?
                AND u.country IS NOT DISTINCT FROM ? AND u.traffic_source IS NOT DISTINCT FROM ?''', arguments).fetchone()[0]
            expected_items = db.execute('''SELECT count(*) FROM raw.order_items i JOIN raw.orders o ON i.order_id=o.order_id
                LEFT JOIN raw.users u ON i.user_id=u.id
                WHERE cast(timezone('UTC',o.created_at) AS DATE)>=? AND cast(timezone('UTC',o.created_at) AS DATE)<?
                AND u.country IS NOT DISTINCT FROM ? AND u.traffic_source IS NOT DISTINCT FROM ?''', arguments).fetchone()[0]
            # GROUP BY 没有分支组时是 NULL，而不是 scalar COUNT 的0。
            assert orders == (expected_orders or None) and items == (expected_items or None)
            expected_ratio = expected_items/expected_orders if expected_orders and expected_items else None
            assert ratio is None if expected_ratio is None else abs(ratio-expected_ratio) < 1e-12
            checks.append({'country': country, 'traffic_source': channel, 'orders': expected_orders, 'items': expected_items, 'pass': True})
    report = {'mode': 'scripted model decisions; real local data; no live model request',
              'semantic_version': service.registry.contract['version'], 'result': result,
              'independent_raw_checks': checks, 'checks_scope': 'all returned groups; not an untruncated population claim'}
    output = ROOT/'docs/multi-plan-live-demo.json'
    output.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
    print(json.dumps({'status': result['status'], 'model_calls_live': False,
        'queries_used': result['runtime']['queries_used'], 'groups_checked': len(checks),
        'truncated': evidence['result_may_be_truncated'], 'output': str(output)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
