"""项目冻结验收：通过实际入口取数、澄清和诊断，保留可学习的完整证据。

不调用付费模型，不修改权威合同或源库。神经检索和真实模型另由集成脚本验收。
"""
import datetime as dt
import json
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import duckdb
from local_agent.semantic import ROOT, Query, file_hash
from local_agent.service import AgentTools
from local_agent.feature_agent import UnifiedRuntime
from local_agent.runtime import HarnessRuntime
from local_agent.agent_tools import AgentTools as DecisionTools
from local_agent.skills import SkillRegistry
from local_agent.dense_retrieval import read_snapshot


def main():
    started = time.monotonic()
    tools = AgentTools()
    release = tools.release()
    runtime = UnifiedRuntime(tools)
    scenarios = []

    def record(name, request, expected_status):
        answer = runtime.start(request)
        assert answer['status'] == expected_status, (name, answer)
        scenarios.append({'name': name, 'expected_status': expected_status,
                          'pass': True, 'request': request, 'response': answer})
        return answer

    query = record('规则理解到真实取数', {'question': '查询2026年9月订单量'}, 'COMPLETE')
    with duckdb.connect(release['database'], read_only=True) as db:
        truth = db.execute("""SELECT count(*) FROM raw.orders WHERE
            created_at >= TIMESTAMPTZ '2026-09-01 00:00:00+00'
            AND created_at < TIMESTAMPTZ '2026-10-01 00:00:00+00'""").fetchone()[0]
        rows = {name: db.execute('SELECT count(*) FROM raw.' + name).fetchone()[0]
                for name in ('distribution_centers', 'products', 'users', 'orders',
                             'order_items', 'inventory_items', 'events')}
    assert query['result']['rows'] == [[truth]]
    record('业务口径歧义', {'question': '2026年9月销售额是多少'}, 'CLARIFY')
    record('缺失支付事实', {'question': '2026年9月支付成功率是多少'}, 'CLARIFY')
    record('订单粒度不能按品类隐式关联', {'query_input': {
        'metric_id': 'order_count@1', 'start': '2026-09-01', 'end': '2026-10-01',
        'group_by': ['category']}}, 'STOPPED')
    today = dt.datetime.now(dt.timezone.utc).date()
    record('未结束日阻断', {'query_input': {'metric_id': 'order_count@1',
        'start': str(today), 'end': str(today + dt.timedelta(days=1))}}, 'CLARIFY')
    diagnostic = record('比率诊断的证据与停止归因', {'task_input': {
        'kind': 'diagnose', 'query': {'metric_id': 'complete_order_rate@1',
            'start': '2026-09-08', 'end': '2026-09-15'},
        'baseline': {'metric_id': 'complete_order_rate@1',
            'start': '2026-09-01', 'end': '2026-09-08'},
        'expected_direction': 'unknown',
        'diagnosis_dimensions': ['traffic_source', 'country']}}, 'INSUFFICIENT_EVIDENCE')
    assert diagnostic['result']['causal_claim'] is False
    assert not diagnostic['result'].get('stopped_reason'), diagnostic['result']
    assert len(diagnostic['result']['evidence']) == 14
    record('空窗口零分母', {'query_input': {'metric_id': 'average_order_value@1',
        'start': '2010-01-01', 'end': '2010-01-02'}}, 'COMPLETE')
    # Workflow恢复复用已授权回执/完成状态；与不支持恢复的自主Agent区分。
    resumed = runtime.resume(query['session_id'])
    assert resumed['already_finished'] and resumed['result']['rows'] == [[truth]]
    feature = json.loads((ROOT/'data/feature-mart/active.json').read_text(encoding='utf-8'))
    with sqlite3.connect(tools.catalog.path) as db:
        catalog = {
            'entity_types': dict(db.execute('SELECT kind,count(*) FROM entities GROUP BY kind')),
            'relationship_types': dict(db.execute('SELECT kind,count(*) FROM relationships GROUP BY kind')),
            'aspect_types': dict(db.execute('SELECT name,count(*) FROM aspects GROUP BY name'))}
    _, index, documents, _ = read_snapshot(ROOT/'data/retrieval-index')
    # 版本/行号自动来自本次源码，学习报告可以直接对照，而非依赖旧文档计数。
    import ast
    symbols = {}
    hashes = {}
    for path in sorted((ROOT/'src/local_agent').glob('*.py')):
        relative = path.relative_to(ROOT).as_posix()
        hashes[relative] = file_hash(path)
        tree = ast.parse(path.read_text(encoding='utf-8'))
        symbols[relative] = {node.name: node.lineno for node in tree.body
                            if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                symbols[relative].update({node.name+'.'+child.name: child.lineno
                    for child in node.body if isinstance(child, ast.FunctionDef)})
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    report = {
        'status': 'PASS', 'generated_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'scope': 'local core-chain acceptance; no statistical model accuracy or production certification',
        'source_commit_before_acceptance_docs': git('rev-parse', 'HEAD'),
        'python': platform.python_version(), 'os': platform.platform(),
        'release': release, 'raw_rows': rows, 'raw_total': sum(rows.values()),
        'registry': {'version': tools.registry.contract['version'], 'sha256': tools.registry.version,
            'standard_metrics': len(tools.registry.contract['metrics']),
            'cross_fact_ratios': len(tools.registry.contract['multi_fact']['ratios'])},
        'tools': {'agent': len(DecisionTools.inputs), 'registered_skills': len(SkillRegistry().specs),
                  'mcp': 13, 'mcp_count_evidence': 'feature-phase2-live-demo.json real stdio discovery'},
        'feature_release': {k: feature[k] for k in ('release_id', 'as_of_date', 'database_sha256',
            'quality', 'repeat_build', 'temporal_completeness_verified')},
        'metadata_catalog': catalog,
        'retrieval_snapshot': {k: index[k] for k in ('snapshot_id', 'format', 'count', 'dimension', 'partitions', 'delta')},
        'raw_independent_order_count': truth, 'scenario_count': len(scenarios), 'scenarios': scenarios,
        'workflow_finished_resume': {'pass': True, 'additional_queries': 0},
        'source_sha256': hashes, 'source_symbols': symbols,
        'elapsed_seconds': time.monotonic() - started,
        'limits': ['no verified source completeness watermark', 'no historical SCD2',
            'no causal root-cause proof', 'AgentLoop resume unsupported',
            'no production CDC/late-data correction', 'no ANN/scale benchmark',
            'no enterprise SSO/multitenancy', 'no measured LLM accuracy']}
    output = ROOT/'docs/project-final-acceptance.json'
    output.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'PASS', 'scenarios': len(scenarios), 'raw_total': sum(rows.values()),
        'diagnostic_queries': len(diagnostic['result']['evidence']), 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
