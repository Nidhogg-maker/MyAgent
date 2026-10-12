"""本地可信工具服务：发布、计划、受限执行和审计都由自己的代码完成。"""
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import shutil
import uuid
import time
import duckdb
from .catalog import MetadataCatalog
from .semantic import ROOT, Query, SemanticRegistry, SQLCompiler, file_hash
from .access import AccessController, AccessDenied
from .temporal import coverage, check_window

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

class AgentTools:
    """本地单用户工具边界；身份在服务侧固定，模型不能提交 principal。"""
    def __init__(self, home=ROOT / 'data/own-agent', registry=None, token=None):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.registry = registry or SemanticRegistry()
        self.compiler = SQLCompiler(self.registry)
        self.catalog = MetadataCatalog(self.home / 'catalog.sqlite')
        self.access = AccessController(self.home, token)
        self.principal = self.access.subject
        self.plans = {}

    def publish(self, database, manifest, run_results, coverage_receipt=None):
        """验证真实数据后复制不可变快照；dbt PASS 只是证据之一，仍独立物理对账。"""
        database, manifest, run_results = map(Path, (database, manifest, run_results))
        if not self.access.role()['publish']:
            raise AccessDenied('Publication requires trusted administrator')
        results = json.loads(run_results.read_text(encoding='utf-8'))
        artifacts = json.loads(manifest.read_text(encoding='utf-8'))
        if any(row['status'] not in ('success', 'pass') for row in results['results']):
            raise ValueError('dbt build has failed or incomplete nodes')
        tests = [r for r in results['results'] if r['unique_id'].startswith('test.thelook_lab.')]
        required = {'reconciliation', 'relationships', 'status_and_item_count'}
        present = {r['unique_id'].split('.')[2] for r in tests}
        if len(tests) < 11 or not required <= present or any(r['status'] != 'pass' for r in tests):
            raise ValueError('Missing/failed commerce dbt checks')
        finished = dt.datetime.fromisoformat(results['metadata']['generated_at'].replace('Z', '+00:00'))
        age = (dt.datetime.now(dt.timezone.utc) - finished).total_seconds()
        if not 0 <= age <= 86400:
            raise ValueError('dbt quality evidence stale or future-dated')
        validation_hash=file_hash(database)
        with duckdb.connect(str(database), read_only=True) as db:
            for test in tests:
                # 将可信本地 dbt 测试重跑到当前物理库，避免旧 PASS 与新数据脱节。
                node = artifacts['nodes'].get(test['unique_id'], {})
                if not node.get('compiled_code') or db.execute(node['compiled_code']).fetchmany(1):
                    raise ValueError('Current database failed dbt assertion: ' + test['unique_id'])
            for fact in self.registry.contract['facts'].values():
                grain, table = fact['grain'], fact['table']
                bad = db.execute(f'SELECT count(*)-count(DISTINCT {grain}) FROM {table}').fetchone()[0]
                if bad:
                    raise ValueError('Fact grain is not unique/non-null')
            amounts = db.execute('SELECT (SELECT sum(booked_order_amount) FROM commerce.fct_orders), (SELECT sum(booked_item_amount) FROM commerce.fct_order_items), (SELECT sum(cast(sale_price as decimal(18,4))) FROM raw.order_items)').fetchone()
            if any(v is None for v in amounts) or len(set(amounts)) != 1:
                raise ValueError('Independent amount reconciliation failed')
            # 编译全部指标并以零行查询校验物理列；真实 schema 缺失会阻止发布。
            for metric in self.registry.contract['metrics']:
                plan = self.compiler.compile(Query(metric_id=metric, start='2026-09-01', end='2026-09-02'))
                db.execute(plan['sql']).fetchall()
        release_id = uuid.uuid4().hex
        directory = self.home / 'releases' / release_id
        directory.mkdir(parents=True)
        before = file_hash(database)
        if before!=validation_hash:
            raise ValueError('Database changed between quality verification and snapshot publication')
        temporal = coverage(before, ROOT / 'docs/thelook-source-manifest.json', Path(coverage_receipt) if coverage_receipt else None)
        frozen = directory / 'warehouse.duckdb'
        shutil.copy2(database, frozen)
        if file_hash(frozen) != before or file_hash(database) != before:
            raise ValueError('Source changed during publication')
        self.catalog.ingest(frozen, manifest, self.registry.contract['owner'])
        self.catalog.attach_quality({'release_id': release_id, 'status': 'PASS', 'checks': [t['unique_id'] for t in tests],
                                     'scope': 'snapshot dbt checks rerun locally; no funnel/temporal completeness claim',
                                     'verified_at': dt.datetime.now(dt.timezone.utc).isoformat()})
        release = {'release_id': release_id, 'database': str(frozen.resolve()), 'database_sha256': before,
                   'registry_sha256': self.registry.version, 'catalog_sha256': file_hash(self.catalog.path),
                   'published_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'quality_generated_at': finished.isoformat(), 'dbt_tests_passed': len(tests),
                   'dbt_results_sha256': file_hash(run_results), 'dbt_manifest_sha256': file_hash(manifest),
                   'quality_scope': 'grain, relationships, statuses and amounts; not full temporal/funnel completeness',
                   'provenance': 'official-public-synthetic-thelook', 'coverage_watermark_verified': temporal['verified'], 'temporal': temporal}
        (directory / 'release.json').write_text(json.dumps(release, indent=2), encoding='utf-8')
        temporary = self.home / 'active.partial'
        temporary.write_text(json.dumps(release, indent=2), encoding='utf-8')
        temporary.replace(self.home / 'active.json')
        return release

    def release(self):
        """每次执行重新检查快照、合同和目录，旧计划不能跨版本偷偷复用。"""
        release = json.loads((self.home / 'active.json').read_text(encoding='utf-8'))
        if file_hash(release['database']) != release['database_sha256'] or self.registry.version != release['registry_sha256'] or file_hash(self.registry.path) != self.registry.version:
            raise ValueError('Snapshot/contract changed; republish required')
        if file_hash(self.catalog.path) != release['catalog_sha256']:
            raise ValueError('Catalog changed; republish required')
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(release['quality_generated_at'])).total_seconds()
        if not 0 <= age <= 86400:
            raise ValueError('Quality evidence expired')
        return release

    def context(self, metric_id):
        self.access.metric(metric_id)
        metric = self.registry.describe(metric_id)
        return {'metric': self.describe(metric_id), 'metadata': self.access.redact_metadata(self.catalog.context(metric['fact']['table'])), 'lineage': self.lineage(metric['fact']['table'])}

    def describe(self, metric_id):
        """口径来自注册表，用户可见维度还要经过权限过滤。"""
        role = self.access.metric(metric_id)
        metric = self.registry.describe(metric_id)
        if '*' not in role['dimensions']:
            metric = {**metric, 'fact': {**metric['fact'], 'dimensions': [d for d in metric['fact']['dimensions'] if d in role['dimensions']]}}
        return metric

    def lineage(self, table, column=None):
        """仅对授权指标相关事实开放图查询；敏感字段关系对受限主体遮盖。"""
        allowed = [m['fact']['table'] for key in self.registry.contract['metrics'] if self._metric_allowed(key) for m in [self.registry.describe(key)]]
        if table not in allowed:
            raise AccessDenied('Metadata table access denied')
        if column and '*' not in self.access.role()['dimensions'] and column in self.access.policy['sensitive_fields']:
            raise AccessDenied('Sensitive field metadata access denied')
        graph = self.catalog.field_lineage(table, column) if column else self.catalog.lineage(table)
        if '*' not in self.access.role()['dimensions']:
            original = graph['edges']
            graph['edges'] = [edge for edge in original if not any(edge[end].rsplit(':', 1)[-1] in self.access.policy['sensitive_fields'] for end in ('from', 'to'))]
            graph['redacted_edges'] = len(original) - len(graph['edges'])
            graph['control_dependencies'] = [edge for edge in graph.get('control_dependencies',[]) if edge['to'].rsplit(':',1)[-1] not in self.access.policy['sensitive_fields']]
        return graph

    def _metric_allowed(self, metric_id):
        try:
            self.access.metric(metric_id)
            return True
        except AccessDenied:
            return False

    def plan(self, query):
        """工具只接受 Query；生成计划保存在服务内，调用方不能替换 SQL。"""
        release = self.release()
        requested = query
        query, role = self.enforce_request(query)
        check_window(query, release.get('temporal', {}))
        from .semantic_context import SemanticContextResolver
        semantic_context = SemanticContextResolver(self).resolve_request(query)
        from .query_templates import QueryTemplateCache
        import sqlite3
        try:
            compiled, template_trace = QueryTemplateCache(self.home).compile(self.compiler,query,
                role['minimum_group_size'],semantic_context['binding'])
        except (sqlite3.Error,OSError):
            compiled = self.compiler.compile(query,role['minimum_group_size'])
            template_trace = {'status':'fallback','reason':'local_template_store_unavailable','results_cached':False}
        metadata = self.catalog.context(compiled['table'])
        for table in compiled.get('tables', []):
            self.catalog.context(table)
        plan = {**compiled, 'plan_id': uuid.uuid4().hex, 'query': query.model_dump(mode='json'),
                'principal': self.principal, 'registry_sha256': self.registry.version,
                'requested_query': requested.model_dump(mode='json'), 'policy_hash': self.access.policy_hash,
                'minimum_group_size': role['minimum_group_size'],
                'release_id': release['release_id'], 'metadata_urn': metadata['urn']}
        plan['semantic_resolution'] = {'binding': semantic_context['binding'],
            'metric_ids': semantic_context['requested_metric_ids'],
            'common_dimensions': semantic_context['common_dimensions'],
            'relationships': semantic_context['relationships']}
        plan['template_cache'] = template_trace
        plan['approval_hash'] = fingerprint(plan)
        self.plans[plan['plan_id']] = json.loads(json.dumps(plan))
        if len(self.plans) > 100:
            self.plans.pop(next(iter(self.plans)))
        return plan

    def enforce_request(self, query):
        """多事实每个分支独立授权，并施加同一强制行过滤，不借 Join 扩权。"""
        from .multi_fact import MultiFactQuery
        if not isinstance(query, MultiFactQuery):
            return self.access.enforce(query)
        self.compiler.compile(query)  # 枚举查询前先确认共同维度，不能读取未注册列。
        for metric in query.metric_ids:
            role = self.access.metric(metric)
            if '*' not in role['dimensions'] and not (set(query.group_by) | set(query.filters)) <= set(role['dimensions']):
                raise AccessDenied('Dimension/column access denied')
        from .dimensions import DimensionResolver
        resolver = DimensionResolver(self)
        normalized = {}
        for field, value in query.filters.items():
            found = set()
            for metric in query.metric_ids:
                try:
                    found.add(resolver.resolve(metric, field, value))
                except ValueError as error:
                    if not str(error).startswith('CLARIFY:'):
                        raise
            # 并集允许某事实没有该组，但所有事实都未知的值不能变成伪零。
            if len(found) != 1:
                raise ValueError('CLARIFY: 多事实筛选值未知或无法一致链接：' + field)
            normalized[field] = found.pop()
        query = query.model_copy(update={'filters': normalized})
        effective = [self.access.enforce(query.branch(m)) for m in query.metric_ids]
        filters = effective[0][0].filters
        if any(item.filters != filters for item, _ in effective):
            raise AccessDenied('Multi-fact branches have incompatible authorized row scopes')
        return query.model_copy(update={'filters': filters}), effective[0][1]

    def execute(self, plan_id, approval_hash, timeout_seconds=30, cancel_check=None):
        """重新编译与服务端计划对比；hash 用于完整性，不是远程认证签名。"""
        plan = self.plans.get(plan_id)
        if not plan or plan['approval_hash'] != approval_hash:
            raise ValueError('Unknown or modified plan')
        payload = {k: v for k, v in plan.items() if k != 'approval_hash'}
        if fingerprint(payload) != approval_hash:
            raise ValueError('Plan storage tampered')
        release = self.release()
        from .semantic_context import SemanticContextResolver
        if plan['semantic_resolution']['binding'] != SemanticContextResolver(self).binding():
            raise ValueError('Semantic context version changed; replan required')
        if plan['release_id'] != release['release_id'] or plan['principal'] != self.principal:
            raise ValueError('Plan identity/release mismatch')
        from .multi_fact import parse_query
        effective, role = self.enforce_request(parse_query(plan['requested_query']))
        if plan['policy_hash'] != self.access.policy_hash or effective.model_dump(mode='json') != plan['query']:
            raise AccessDenied('Plan policy/row scope changed')
        check_window(effective, release.get('temporal', {}))
        recomputed = self.compiler.compile(effective, role['minimum_group_size'])
        if recomputed['sql'] != plan['sql']:
            raise ValueError('SQL differs from compiler output')
        try:
            # 专用子进程入口不重新导入 MCP 主模块，避免 Windows spawn 与 stdio 冲突。
            command=[sys.executable, '-m', 'local_agent.worker']
            payload=json.dumps({'database': release['database'], 'sql': plan['sql']})
            if cancel_check is None:
                child = subprocess.run(command,input=payload,capture_output=True,text=True,encoding='utf-8',timeout=min(30,timeout_seconds))
            else:
                # 会话取消传递到实际查询子进程，而非仅改变界面状态。
                process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
                deadline=time.monotonic()+min(30,timeout_seconds)
                first=True
                try:
                    while True:
                        cancel_check()
                        remaining=deadline-time.monotonic()
                        if remaining<=0: raise TimeoutError('Query deadline exceeded')
                        try:
                            stdout,stderr=process.communicate(input=payload if first else None,timeout=min(.25,remaining))
                            child=subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
                            break
                        except subprocess.TimeoutExpired:
                            first=False
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()
        except subprocess.TimeoutExpired:
            raise TimeoutError('Query deadline exceeded') from None
        if child.returncode:
            raise ValueError('Query worker terminated')
        result = json.loads(child.stdout)
        if 'error' in result:
            raise ValueError('Query worker failed: ' + result['error'])
        envelope = {**result, 'metric_id': plan['metric'], 'definition': plan['definition'], 'unit': plan['unit'],
                    'grain': plan['grain'], 'release_id': release['release_id'], 'plan_id': plan_id,
                    'result_may_be_truncated': bool(parse_query(plan['query']).group_by) and len(result['rows']) == plan['query']['limit'],
                    'logical_plan': plan['logical_plan'],
                    'semantic_resolution': plan['semantic_resolution'],
                    'template_cache': plan.get('template_cache',{}),
                    'quality': {'dbt_tests_passed': release['dbt_tests_passed'], 'scope': release['quality_scope']},
                    'permissions': {'subject': self.principal, 'minimum_group_size': role['minimum_group_size'], 'row_scope': role['row_filters']},
                    'temporal': release.get('temporal', {}),
                    'warnings': ['Synthetic source', 'Current dimension/status snapshot; no historical SCD2', 'No verified coverage watermark; no causal attribution'],
                    'provenance': release['provenance']}
        with (self.home / 'audit.jsonl').open('a', encoding='utf-8') as file:
            file.write(json.dumps({'principal': self.principal, 'plan_id': plan_id, 'query': plan['query'], 'release_id': release['release_id'], 'rows': len(result['rows'])}) + '\n')
        return envelope

    def compare(self, baseline: Query, current: Query):
        """双窗口证据比较：保证口径、分组、过滤、时长一致，只报告变化不归因。"""
        if (baseline.metric_id, baseline.group_by, baseline.filters, baseline.limit) != (current.metric_id, current.group_by, current.filters, current.limit):
            raise ValueError('Comparison semantic definitions differ')
        if baseline.end - baseline.start != current.end - current.start:
            raise ValueError('Comparison windows must have equal duration')
        if not (baseline.end <= current.start or current.end <= baseline.start):
            raise ValueError('Comparison windows overlap')
        evidence = []
        for query in (baseline, current):
            plan = self.plan(query)
            evidence.append(self.execute(plan['plan_id'], plan['approval_hash']))
        if any(item['result_may_be_truncated'] for item in evidence):
            raise ValueError('Truncated comparison cannot support full group attribution')
        mapping = [{tuple(row[:-1]): row[-1] for row in item['rows']} for item in evidence]
        observations = []
        for group in sorted(mapping[0].keys() | mapping[1].keys(), key=str):
            old, new = mapping[0].get(group), mapping[1].get(group)
            observations.append({'group': group, 'baseline': old, 'current': new,
                                 'delta': float(new) - float(old) if old is not None and new is not None else None})
        return {'observations': observations, 'evidence': evidence, 'causal_claim': False,
                'conclusion': 'Only observed changes; no proven cause or coverage completeness'}
